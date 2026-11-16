"""M8 更正补入服务层：定向补入、四账可解释、幂等、失败回滚、旧结果冻结。"""
from __future__ import annotations

import pytest

import expected
from app.errors import Unprocessable
from app.modules.m8_correction import service as correction_service

CORRECTION_FILE = "subscriptions_correction.csv"
CORRECTED_SUBS = ("SUB-1004", "SUB-1005", "SUB-1014")
# 三个补入订阅的期间都是 2026-02 整月 28 天、无变更，账单额 = 月价
EXPECTED_NEW_CENTS = {
    "INV-202602-SUB-1004": 90000,
    "INV-202602-SUB-1005": 150000,
    "INV-202602-SUB-1014": 80000,
}


def _publish(store, settings):
    return correction_service.publish_correction(
        store, settings, file_name=CORRECTION_FILE)


def test_correction_adds_only_quarantined_invoices(store, settings, run_data):
    base_id = run_data["run_id"]
    out = _publish(store, settings)

    # 账单从 10 张增到 13 张，新增的恰好是三条隔离订阅
    assert out["totals"]["invoices"] == str(expected.INVOICE_COUNT + 3)
    new_invoices = {row["invoice_id"]: row["total_cents"]
                    for row in store.list_invoices(out["run_id"])}
    for invoice_id, cents in EXPECTED_NEW_CENTS.items():
        assert new_invoices[invoice_id] == cents

    # 合计增量只来自补入的三张账单
    assert int(out["totals"]["invoice_cents"]) == expected.TOTAL_CENTS + sum(
        EXPECTED_NEW_CENTS.values())

    # 旧版十张账单逐字不变（已确认结果不被改写）
    old = {row["invoice_id"]: row["total_cents"]
           for row in store.list_invoices(base_id)}
    for invoice_id, cents in old.items():
        assert new_invoices[invoice_id] == cents


def test_four_ledgers_balanced_and_explainable(store, settings, run_data):
    out = _publish(store, settings)
    assert [row["status"] for row in out["ledgers"]] == ["ok"] * 4

    # 行数账：7 个 error 隔离里有 3 个转为可用
    counters = out["counters"]
    assert counters["corrected_rows"] == 3
    assert counters["quarantined_rows"] == expected.QUARANTINED_ROWS - 3
    assert counters["subs_kept"] == expected.INVOICE_COUNT + 3

    # 隔离区在新版本里被标记结案，基线版本仍未结案
    new_q = store.list_quarantine(out["run_id"])
    resolved = {(q["row_no"], q["resolved"]) for q in new_q if q["resolved"]}
    assert {row for row, flag in resolved if flag} == {6, 7, 16}
    base_q = store.list_quarantine(run_data["run_id"])
    assert all(not q.get("resolved") for q in base_q)


def test_rerun_same_correction_is_idempotent(store, settings, run_data):
    first = _publish(store, settings)
    again = _publish(store, settings)
    assert again["reused"] is True
    assert again["run_id"] == first["run_id"]
    # 只产生一个更正版本、一条发布记录
    runs = [r for r in store.list_runs(50) if r.get("kind") == "correction"]
    assert len(runs) == 1
    releases = store.list_correction_releases()
    assert len(releases) == 1 and releases[0]["status"] == "published"


def test_lineage_keeps_base_and_correction_versions(store, settings, run_data):
    base_id = run_data["run_id"]
    out = _publish(store, settings)
    lineage = store.list_lineage(out["run_id"])
    assert [(item["version_no"], item["kind"]) for item in lineage] == [
        (1, "ingest"), (2, "correction")]
    assert lineage[0]["run_id"] == base_id
    # 不指定 run 时，当前批次指向最新已发布更正版，失败的 running 不会顶替
    assert store.latest_run()["run_id"] == out["run_id"]


def test_three_way_entries_record_base_patch_final(store, settings, run_data):
    out = _publish(store, settings)
    data = correction_service.overview(store, out["run_id"])
    entries = {item["sub_id"]: item for item in data["entries"]}
    assert set(entries) == set(CORRECTED_SUBS)
    for sub_id in CORRECTED_SUBS:
        item = entries[sub_id]
        assert item["base_cents"] == 0  # 隔离时没有账单
        assert item["final_cents"] == EXPECTED_NEW_CENTS[item["invoice_id"]]
        assert item["corrected"]["sub_id"] == sub_id
        assert "R_CORRECTED_ROW" in item["corrected"]["flags"]


def test_replace_mode_is_rejected(store, settings, run_data):
    with pytest.raises(Unprocessable) as exc:
        correction_service.publish_correction(
            store, settings, file_name=CORRECTION_FILE, mode="replace")
    assert exc.value.code == "E_CORRECTION_MODE"
    # 拒绝后没有任何新版本
    assert len(store.list_runs(50)) == 1


def test_correction_for_healthy_sub_is_whole_rejected(store, settings, run_data):
    base_totals = store.list_totals(run_data["run_id"])
    bad = ("订阅号,账户,套餐,月价(元),期间起,期间止,时区,状态\n"
           "SUB-1001,杭州云帆,标准版,1200.00,2026-02-01,2026-03-01,+08:00,active\n"
           ).encode()
    with pytest.raises(Unprocessable) as exc:
        correction_service.publish_correction(
            store, settings, file_name="bad.csv", content=bad)
    assert exc.value.code == "E_CORRECTION_INVALID"
    assert exc.value.detail["rejected"][0]["code"] == "R_CORRECTION_NO_QUARANTINE"
    # 基线完整：无新 run、合计不变、无发布记录
    assert len(store.list_runs(50)) == 1
    assert store.list_totals(run_data["run_id"]) == base_totals
    assert store.list_correction_releases() == []


def test_one_bad_row_rejects_whole_file(store, settings, run_data):
    from pathlib import Path

    good = (Path(settings.sample_dir) / CORRECTION_FILE).read_bytes()
    mixed = good + ("SUB-1099,幽灵,标准版,abc,2026-02-01,2026-03-01,+08:00,active\n"
                    ).encode()
    with pytest.raises(Unprocessable) as exc:
        correction_service.publish_correction(
            store, settings, file_name="mixed.csv", content=mixed)
    assert exc.value.code == "E_CORRECTION_INVALID"
    assert len(store.list_runs(50)) == 1


def test_publish_failure_rolls_back_and_keeps_old_version(store, settings, run_data,
                                                          monkeypatch):
    base_id = run_data["run_id"]
    base_totals = store.list_totals(base_id)

    def boom(_ledgers):
        raise Unprocessable("模拟对账不平", code="E_CORRECTION_LEDGER")

    monkeypatch.setattr(correction_service, "_assert_ledgers_balanced", boom)
    with pytest.raises(Unprocessable):
        correction_service.publish_correction(
            store, settings, file_name=CORRECTION_FILE)

    # 没有 done 孤儿 run；当前版本仍是基线，合计不动
    statuses = {run["status"] for run in store.list_runs(50)}
    assert statuses == {"done"}
    assert store.latest_run()["run_id"] == base_id
    assert store.list_totals(base_id) == base_totals
    # 失败留痕存在且标记 failed
    releases = store.list_correction_releases()
    assert len(releases) == 1 and releases[0]["status"] == "failed"


SECOND_CORRECTION = (
    "订阅号,账户,套餐,月价(元),期间起,期间止,时区,状态,原行号\n"
    "SUB-1012,未知时区,标准版,900.00,2026-02-01,2026-03-01,+08:00,active,14\n"
    "SUB-1013,状态异常,标准版,900.00,2026-02-01,2026-03-01,+08:00,active,15\n"
).encode()


def test_chained_corrections_build_unbroken_lineage(store, settings, run_data):
    base_id = run_data["run_id"]
    v2 = correction_service.publish_correction(
        store, settings, file_name=CORRECTION_FILE)
    v3 = correction_service.publish_correction(
        store, settings, file_name="second.csv", content=SECOND_CORRECTION)

    # v3 直接挂在 v2 上，版本链 v1→v2→v3 不断
    assert v3["base_run_id"] == v2["run_id"]
    lineage = store.list_lineage(v3["run_id"])
    assert [(item["version_no"], item["kind"]) for item in lineage] == [
        (1, "ingest"), (2, "correction"), (3, "correction")]
    # 旧版本冻结：10 / 13 / 15 张账单
    assert len(store.list_invoices(base_id)) == 10
    assert len(store.list_invoices(v2["run_id"])) == 13
    assert len(store.list_invoices(v3["run_id"])) == 15
    assert [row["status"] for row in v3["ledgers"]] == ["ok"] * 4

    # 两份更正各自幂等，重跑都复用，不新增 run
    again_v3 = correction_service.publish_correction(
        store, settings, file_name="second.csv", content=SECOND_CORRECTION)
    again_v2 = correction_service.publish_correction(
        store, settings, file_name=CORRECTION_FILE)
    assert again_v3["reused"] and again_v3["run_id"] == v3["run_id"]
    assert again_v2["reused"] and again_v2["run_id"] == v2["run_id"]
    assert len(store.list_runs(50)) == 3
    assert len(store.list_correction_releases()) == 2
