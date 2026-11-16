"""M6 对账：四本账、行数恒等、金额单位、天数合计。"""
from __future__ import annotations

from decimal import Decimal

import expected
from app.modules.m6_invoices import reconcile


def test_all_ledgers_balanced(run_id, store):
    ledgers = store.list_reconciliations(run_id)
    assert [row["ledger"] for row in ledgers] == ["rows", "days", "amount", "invoices"]
    for row in ledgers:
        assert row["status"] == "ok", row
        assert row["diff_text"] in {"0", "0E-8"}
    assert reconcile.overall(ledgers)["status"] == "ok"


def test_rows_ledger_identity(run_id, store):
    # TRAP-18：三态空行与隔离行都要在行数账里各归各位
    counters = store.get_run(run_id)["counters"]
    assert counters["rows_read"] == expected.ROWS_READ
    assert counters["quarantined_rows"] == expected.QUARANTINED_ROWS
    left = counters["rows_read"]
    right = (counters["subs_kept"] + counters["changes_kept"]
             + counters["quarantined_rows"] + counters["dropped_dup"]
             + counters["blank_rows"] + counters["repeated_headers"])
    assert left == right == 31
    assert counters["subs_kept"] + counters["changes_kept"] == 23


def test_amount_ledger_cents(run_id, store):
    # TRAP-10：单位是「分」，整数相加，不允许浮点误差
    totals = store.list_totals(run_id)
    charge = int(totals["charge_cents"])
    credit = int(totals["credit_cents"])
    invoices = int(totals["invoice_cents"])
    assert charge - credit == invoices == expected.TOTAL_CENTS
    assert charge == 1688212 and credit == 613929
    ledger = [row for row in store.list_reconciliations(run_id)
              if row["ledger"] == "amount"][0]
    assert ledger["left_text"] == str(charge)
    assert ledger["right_text"] == str(credit + invoices)
    assert "精确额差" in ledger["note"]


def test_day_ledger_totals(run_id, store):
    # TRAP-23：账单层天数合计等于期间天数合计
    totals = store.list_totals(run_id)
    assert int(totals["period_days"]) == int(totals["billed_days"]) + int(totals["free_days"])
    assert int(totals["period_days"]) == expected.PERIOD_DAYS
    ledger = [row for row in store.list_reconciliations(run_id)
              if row["ledger"] == "days"][0]
    assert ledger["left_text"] == ledger["right_text"] == "283"


def test_exact_gap_zero(run_id, store):
    segments = store.list_segments(run_id)
    invoices = store.list_invoices(run_id)
    exact_segments = sum((Decimal(row["amount_exact"]) for row in segments), Decimal("0"))
    exact_invoices = sum((Decimal(row["exact_total"]) for row in invoices), Decimal("0"))
    assert exact_segments - exact_invoices == Decimal("0E-8")
    assert exact_segments > 0


def test_reconcile_api_shape(seeded_client):
    data = seeded_client.get("/api/reconcile").json()
    assert len(data["ledgers"]) == 4
    assert data["totals"]["invoices"] == "10"
    assert all(row["status"] == "ok" for row in data["ledgers"])
