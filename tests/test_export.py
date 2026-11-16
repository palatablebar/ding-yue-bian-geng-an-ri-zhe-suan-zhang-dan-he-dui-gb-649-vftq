"""M7 导出：账单 CSV 与分段 CSV 的表头、行数、证据列、金额一致。"""
from __future__ import annotations

import csv
import io
from decimal import Decimal

import expected


def _rows(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    return list(reader)


def test_invoices_csv_bom_and_header(seeded_client):
    response = seeded_client.get("/api/export/invoices.csv")
    assert response.status_code == 200
    assert response.text.startswith("\ufeff")
    assert response.headers["content-type"].startswith("text/csv")
    header = response.text.lstrip("\ufeff").splitlines()[0]
    assert header.startswith("账单号,订阅号,账户,期间起")
    assert "账单额(元)" in header and "校验位" in header


def test_invoices_csv_rows_match_api(seeded_client):
    response = seeded_client.get("/api/export/invoices.csv")
    rows = _rows(response.text)
    assert len(rows) == expected.INVOICE_COUNT
    assert response.headers["x-row-count"] == str(expected.INVOICE_COUNT)
    api = seeded_client.get("/api/invoices").json()
    assert len(api["invoices"]) == len(rows)
    by_id: dict[str, dict] = {row["账单号"]: row for row in rows}
    assert by_id["INV-202602-SUB-1001"]["账单额(元)"] == "1742.86"
    assert by_id["INV-202602-SUB-1009"]["账单额(元)"] == "1200.01"


def test_export_sum_matches_totals(seeded_client):
    rows = _rows(seeded_client.get("/api/export/invoices.csv").text)
    total = sum((Decimal(row["账单额(元)"]) for row in rows), Decimal("0"))
    assert total == Decimal(expected.TOTAL_CENTS) / 100
    totals = seeded_client.get("/api/invoices").json()["totals"]
    assert int(totals["invoice_cents"]) == expected.TOTAL_CENTS


def test_segments_csv_evidence_columns(seeded_client):
    response = seeded_client.get("/api/export/segments.csv")
    rows = _rows(response.text)
    assert len(rows) == expected.SEGMENTS
    required = {"账单号", "段序", "起", "止", "天数", "日价(元)", "原始行号", "标记"}
    assert required <= set(rows[0])
    late = [row for row in rows if "R_LATE_CHANGE" in row["标记"]]
    assert late and late[0]["账单号"] == "INV-202602-SUB-1001"
    assert response.headers["x-row-count"] == str(expected.SEGMENTS)


def test_export_requires_run(client):
    # 没有批次时导出给 404，而不是空文件
    assert client.get("/api/export/invoices.csv").status_code == 404
