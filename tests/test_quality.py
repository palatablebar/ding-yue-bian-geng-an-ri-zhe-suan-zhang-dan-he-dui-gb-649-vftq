"""M3 质量隔离：原因码、重复键冲突、原因分布、证据导出。"""
from __future__ import annotations

import expected
from app.modules.m3_quality import quarantine, rules


def test_error_codes_on_dirty_sample(run_id, store):
    codes = {row["code"] for row in store.list_quarantine(run_id)}
    for code in expected.REQUIRED_CODES:
        assert code in codes, f"缺少原因码 {code}"


def test_duplicate_key_conflict_keeps_first_row(run_id, store):
    # TRAP-14：同一业务键取值冲突时保留行号最小的那条，另一条进隔离区可导出
    subs = {row["sub_id"]: row for row in store.list_subscriptions(run_id)}
    kept = subs["SUB-1003"]
    assert kept["monthly"] in {"600.00", "600"}
    assert kept["row_no"] == 4
    conflicts = [row for row in store.list_quarantine(run_id)
                 if row["code"] == "R_DUP_SUB_KEY"]
    assert len(conflicts) == 1
    assert conflicts[0]["row_no"] == 5
    assert "保留前者" in conflicts[0]["detail"]
    assert "R_DUP_SUB_KEY" in kept["flags"]


def test_reason_distribution_sorted_by_level(run_id, store):
    entries = store.list_quarantine(run_id)
    distribution = quarantine.distribution(entries)
    levels = [row["level"] for row in distribution]
    assert levels == sorted(levels, key=lambda level: {"error": 0, "warn": 1,
                                                      "info": 2}[level])
    total = sum(row["count"] for row in distribution)
    assert total == len(entries)
    error_rows = [row for row in distribution if row["level"] == "error"]
    assert {row["code"] for row in error_rows} >= {
        "R_COLUMN_COUNT", "R_PERIOD_REVERSED", "R_TZ_UNKNOWN", "R_STATE_UNKNOWN",
        "R_PRICE_MISSING", "R_DUP_SUB_KEY", "R_CHANGE_UNKNOWN_SUB"}


def test_quarantine_csv_export(client, run_id, store):
    response = client.get("/api/quarantine.csv")
    assert response.status_code == 200
    assert response.text.startswith("\ufeff")
    lines = response.text.lstrip("\ufeff").splitlines()
    assert lines[0].startswith("文件,行号,级别,原因码")
    assert len(lines) - 1 == len(store.list_quarantine(run_id))
    assert "R_COLUMN_COUNT" in response.text


def test_reason_catalog_complete():
    from app import reasons

    rows = reasons.catalog()
    assert len(rows) == len(reasons.REASONS)
    assert {row["level"] for row in rows} == {"error", "warn", "info"}
    assert all(row["label"] for row in rows)
    # 未登记的原因码按隔离处理，不允许静默放过
    assert reasons.level_of("R_NOT_REGISTERED") == "error"
    assert rules.normalize_kind("升配").value == "upgrade"
