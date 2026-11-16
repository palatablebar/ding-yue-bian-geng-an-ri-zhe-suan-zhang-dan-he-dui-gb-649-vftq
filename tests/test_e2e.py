"""端到端：HTTP 采信 → 六个页面 → 导出，数字与对账结论一致。"""
from __future__ import annotations

import csv
import io

import expected

PAGES = ("/", "/subscriptions", "/calendar", "/proration", "/changes", "/invoices")


def test_full_flow_from_dirty_sample(client):
    response = client.post("/api/subscriptions/import", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["totals"]["invoice_cents"] == str(expected.TOTAL_CENTS)
    assert data["totals"]["invoices"] == str(expected.INVOICE_COUNT)
    assert [row["status"] for row in data["ledgers"]] == ["ok"] * 4
    for path in PAGES:
        page = client.get(path)
        assert page.status_code == 200, path
        assert "subbill" in page.text
    assert "隔离行" in client.get("/").text
    assert "抵扣行" in client.get("/changes").text


def test_quarantine_csv_matches_api(client):
    client.post("/api/subscriptions/import", json={})
    api = client.get("/api/quarantine").json()
    text = client.get("/api/quarantine.csv").text
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    assert len(rows) - 1 == api["totals"]["entries"]
    assert api["totals"]["error"] == expected.QUARANTINED_ROWS


def test_export_has_data_after_import(client):
    client.post("/api/subscriptions/import", json={})
    invoices = client.get("/api/export/invoices.csv")
    segments = client.get("/api/export/segments.csv")
    manifest = client.get("/api/export/manifest.json")
    assert invoices.headers["x-row-count"] == str(expected.INVOICE_COUNT)
    assert segments.headers["x-row-count"] == str(expected.SEGMENTS)
    assert len(invoices.content) > 500
    assert '"inputs"' in manifest.text or '"inputs":' in manifest.text


def test_recompute_endpoints_idempotent(client):
    client.post("/api/subscriptions/import", json={})
    before = client.get("/api/invoices").json()["totals"]
    first = client.post("/api/changes")
    second = client.post("/api/proration")
    assert first.status_code == 200 and second.status_code == 200
    after = client.get("/api/invoices").json()["totals"]
    assert after["invoice_cents"] == before["invoice_cents"]
    assert after["segments"] == before["segments"]
    assert all(row["status"] == "ok" for row in client.get("/api/reconcile").json()["ledgers"])


def test_home_page_shows_totals(client):
    client.post("/api/subscriptions/import", json={})
    html = client.get("/").text
    assert "10742.83" in html
    assert "对账" in html
    assert "采信" in html
