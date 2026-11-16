"""M1 采信：编码回退、BOM、重复表头、引号换行、空态、幂等重跑。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import BadRequest
from app.modules.m1_ingest import reader
from app.modules.m1_ingest import service as ingest_service
from app.modules.m3_quality import rules

FIXTURES = Path(__file__).parent / "fixtures"


def test_encoding_chain_reads_gbk(sample_dir):
    table = reader.load(sample_dir, "subscriptions_gbk.csv")
    assert table.encoding == "gb18030"
    assert table.header[0] == "订阅号"
    assert len(table.rows) == 1
    assert "国标编码客户" in table.rows[0].fields


def test_bom_and_thousand_separator(sample_dir):
    table = reader.load(sample_dir, "subscriptions_dirty.csv")
    assert table.encoding == "utf-8-sig"
    # TRAP-02 类问题：BOM 被剥掉，首列名可以按列名取值
    assert table.header[0] == "订阅号"
    first = table.rows[0]
    # TRAP-06：千分位与全角数字必须归一，而不是 float() 崩掉
    thousand = rules.normalize_money(first.fields[3])
    assert thousand.value is not None
    assert thousand.value == rules.normalize_money("1200.00").value
    assert "R_PRICE_THOUSANDS" in thousand.flags


def test_truncated_tail_rejected(sample_dir):
    table = reader.load(sample_dir, "subscriptions_truncated.csv")
    # 引号未闭合的半行不计入有效数据，单独计截断
    assert table.truncated_rows == 1
    assert len(table.rows) == 1
    assert table.state_code is None


def test_quoted_newline_keeps_logical_rows():
    data = (FIXTURES / "dirty_rows.csv").read_bytes()
    table = reader.parse_table("dirty_rows.csv", data)
    # 第 2 行账户里有换行，物理 5 行、逻辑 3 条；行号按记录起始行保留
    assert len(table.rows) == 3
    assert [row.row_no for row in table.rows] == [2, 4, 5]
    assert "\n" in table.rows[0].fields[1]


def test_empty_states_distinct(sample_dir):
    # TRAP-18：0 行 / 全空行 / 仅表头是三种不同结论
    header_only = reader.load(sample_dir, "subscriptions_header_only.csv")
    blank = reader.load(sample_dir, "subscriptions_blank.csv")
    empty = reader.parse_table("empty.csv", b"")
    assert header_only.state_code == "R_HEADER_ONLY"
    assert blank.state_code == "R_BLANK_ROWS"
    assert empty.state_code == "R_EMPTY_FILE"


def test_import_reuses_batch(store, settings, run_data):
    again = ingest_service.import_sample(store, settings)
    assert again["reused"] is True
    assert again["run_id"] == run_data["run_id"]
    assert len(store.list_runs()) == 1
    assert again["totals"]["invoices"] == run_data["totals"]["invoices"]


def test_bad_file_name_rejected(store, settings):
    with pytest.raises(BadRequest) as excinfo:
        ingest_service.import_sample(store, settings, "../etc/passwd", None)
    assert excinfo.value.code == "E_BAD_FILE_NAME"
