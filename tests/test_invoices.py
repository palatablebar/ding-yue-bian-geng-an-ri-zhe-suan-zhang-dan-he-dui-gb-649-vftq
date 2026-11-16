"""M6 账单：出账规则、天数拆分、金额恒等、尾差标记、明细接口。"""
from __future__ import annotations

import expected


def test_invoice_ids_and_count(run_id, store):
    invoices = {row["invoice_id"]: row for row in store.list_invoices(run_id)}
    assert len(invoices) == expected.INVOICE_COUNT
    assert set(invoices) == set(expected.INVOICE_CENTS)
    assert invoices["INV-202602-SUB-1001"]["sub_id"] == "SUB-1001"
    assert invoices["INV-202802-SUB-1007"]["period_start"] == "2028-02-01"


def test_days_split_per_invoice(run_id, store):
    # TRAP-23：期间天数 = 计费天数 + 免费/暂停天数，端点不重不漏
    for invoice in store.list_invoices(run_id):
        assert invoice["billed_days"] + invoice["free_days"] == invoice["period_days"]
    invoices = {row["sub_id"]: row for row in store.list_invoices(run_id)}
    assert invoices["SUB-1002"]["free_days"] == 24
    assert invoices["SUB-1010"]["free_days"] == 14
    assert invoices["SUB-1011"]["free_days"] == 19


def test_total_equals_charge_minus_credit(run_id, store):
    for invoice in store.list_invoices(run_id):
        assert invoice["total_cents"] == invoice["charge_cents"] - invoice["credit_cents"]
    totals = store.list_totals(run_id)
    assert int(totals["invoice_cents"]) == expected.TOTAL_CENTS
    assert int(totals["billed_days"]) == expected.BILLED_DAYS
    assert int(totals["free_days"]) == expected.FREE_DAYS


def test_round_adjust_flag(run_id, store):
    # TRAP-24：这张账单的分量各自四舍五入会差 1 分，必须留下补差标记
    invoices = {row["invoice_id"]: row for row in store.list_invoices(run_id)}
    assert "R_ROUND_ADJUST" in invoices["INV-202602-SUB-1008"]["flags"]
    assert invoices["INV-202602-SUB-1008"]["total_cents"] == 184286


def test_invoice_flags_follow_changes(run_id, store):
    invoices = {row["invoice_id"]: row for row in store.list_invoices(run_id)}
    for invoice_id, code in expected.INVOICE_FLAGS.items():
        assert code in invoices[invoice_id]["flags"], invoice_id


def test_invoice_detail_api(seeded_client, run_id):
    response = seeded_client.get("/api/invoices/INV-202602-SUB-1001")
    assert response.status_code == 200
    data = response.json()
    assert data["invoice"]["total_cents"] == expected.INVOICE_CENTS["INV-202602-SUB-1001"]
    assert [row["days"] for row in data["segments"]] == [2, 8, 18]
    kinds = [row["kind"] for row in data["components"]]
    assert kinds == ["charge", "credit", "charge", "credit", "charge"]
    assert data["components"][0]["label"] == "整期预缴"
    missing = seeded_client.get("/api/invoices/INV-199901-SUB-0000")
    assert missing.status_code == 404
    assert missing.json()["error"] == "E_NO_INVOICE"


def test_invoice_detail_components_balance(seeded_client):
    data = seeded_client.get("/api/invoices/INV-202611-SUB-1010").json()
    charge = sum(row["cents"] for row in data["components"] if row["kind"] == "charge")
    credit = sum(row["cents"] for row in data["components"] if row["kind"] == "credit")
    assert charge + credit == data["invoice"]["total_cents"] == 32000
