"""M1 列契约：列数、别名、缺列、重复行、空行。"""
from __future__ import annotations

from dataclasses import replace

import expected
from app import config
from app.modules.m1_ingest import columns
from app.modules.m1_ingest import service as ingest_service


def _write(tmp_path, name: str, text: str) -> None:
    (tmp_path / name).write_text(text, encoding="utf-8")


def test_column_count_mismatch_quarantined(run_id, store):
    # TRAP-05：多一列不能静默补空，必须整行进隔离区并带列数事实
    entries = [row for row in store.list_quarantine(run_id)
               if row["code"] == "R_COLUMN_COUNT"]
    assert len(entries) == 1
    assert entries[0]["row_no"] == 7
    assert entries[0]["raw_value"] == "9列/表头8列"
    subs = {row["sub_id"] for row in store.list_subscriptions(run_id)}
    assert "SUB-1005" not in subs


def test_duplicate_identical_row_dropped(tmp_path):
    _write(tmp_path, "subs.csv",
           "订阅号,账户,套餐,月价(元),期间起,期间止,时区,状态\n"
           "SUB-4001,同值客户,标准版,600.00,2026-02-01,2026-03-01,+08:00,active\n"
           "SUB-4001,同值客户,标准版,600.00,2026-02-01,2026-03-01,+08:00,active\n")
    _write(tmp_path, "changes.csv",
           "变更号,订阅号,生效时间,类型,新套餐,新月价(元)\n")
    settings = replace(config.Settings(), db_path=str(tmp_path / "t.sqlite"),
                       sample_dir=str(tmp_path))
    from app.store import Store

    store = Store(settings.db_path)
    data = ingest_service.import_sample(store, settings, "subs.csv", "changes.csv")
    # 完全相同的一行属于重复行：丢弃并计 info，不算隔离
    assert data["counters"]["dropped_dup"] == 1
    assert data["counters"]["subs_kept"] == 1
    codes = {row["code"] for row in store.list_quarantine(data["run_id"])}
    assert "R_DUP_SUB_ROW" in codes
    assert data["totals"]["invoices"] == "1"


def test_missing_required_column_isolates_file(tmp_path):
    _write(tmp_path, "subs.csv",
           "订阅号,账户,套餐,期间起,期间止,时区,状态\n"
           "SUB-4101,缺价客户,标准版,2026-02-01,2026-03-01,+08:00,active\n")
    _write(tmp_path, "changes.csv",
           "变更号,订阅号,生效时间,类型,新套餐,新月价(元)\n")
    settings = replace(config.Settings(), db_path=str(tmp_path / "t.sqlite"),
                       sample_dir=str(tmp_path))
    from app.store import Store

    store = Store(settings.db_path)
    data = ingest_service.import_sample(store, settings, "subs.csv", "changes.csv")
    entries = store.list_quarantine(data["run_id"])
    header_entries = [row for row in entries
                      if row["file"] == "subs.csv" and row["code"] == "R_HEADER_MISSING"]
    assert header_entries and header_entries[0]["row_no"] == 0
    # 只有表头的变更文件是另一种空态，两个原因码不能混用
    assert any(row["file"] == "changes.csv" and row["code"] == "R_HEADER_ONLY"
               for row in entries)
    # 整份文件不可用时，行数账仍要平：数据行全部计隔离
    assert data["counters"]["subs_kept"] == 0
    assert data["counters"]["quarantined_rows"] == 1
    assert data["ledgers"][0]["status"] == "ok"


def test_header_aliases_mapped():
    mapping = columns.sub_header(["订阅ID", "客户名称", "月价", "计费起", "计费止", "时区", "状态"])
    assert mapping.canonical.get("sub_id") == 0
    assert mapping.canonical.get("price") == 2
    assert mapping.missing == ["plan"]
    assert mapping.unknown == []


def test_blank_rows_counted_not_quarantined(run_id, store):
    # TRAP-18 的第二态：空行只计数，不产生行级隔离
    row_entries = [row for row in store.list_quarantine(run_id)
                   if row["code"] == "R_BLANK_ROWS"]
    assert len(row_entries) == 1
    assert row_entries[0]["row_no"] == 0
    counters = store.get_run(run_id)["counters"]
    assert counters["blank_rows"] == expected.BLANK_ROWS
    assert counters["quarantined_rows"] == expected.QUARANTINED_ROWS
