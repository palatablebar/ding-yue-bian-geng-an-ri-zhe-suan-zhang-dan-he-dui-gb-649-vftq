"""不变量：幂等、守恒、顺序无关、单位稳定。"""
from __future__ import annotations

from decimal import Decimal

import expected
from app.modules.m1_ingest import service as ingest_service
from app.modules.m5_changes import segments as segment_mod


def test_rerun_same_rows_and_totals(store, settings, run_data):
    # TRAP-10：同输入重跑，行数与合计逐字不变（不靠浮点碰运气）
    before = dict(store.list_totals(run_data["run_id"]))
    again = ingest_service.import_sample(store, settings)
    after = dict(store.list_totals(again["run_id"]))
    assert before == after
    assert again["reused"] is True
    assert len(store.list_runs()) == 1
    assert before["invoice_cents"] == str(expected.TOTAL_CENTS)


def test_segment_cents_conservation(run_id, store):
    # TRAP-24：分段分合计 = 抵扣分合计 + 账单额分合计，逐张成立
    invoices = {row["invoice_id"]: row for row in store.list_invoices(run_id)}
    segment_sum: dict[str, int] = {}
    for segment in store.list_segments(run_id):
        segment_sum[segment["invoice_id"]] = (segment_sum.get(segment["invoice_id"], 0)
                                             + int(segment["amount_cents"]))
    assert sum(segment_sum.values()) == expected.TOTAL_CENTS
    for invoice_id, cents in segment_sum.items():
        assert cents == invoices[invoice_id]["total_cents"]


def test_change_order_independence(run_id, store):
    # TRAP-25：把变更行顺序打乱，分段结果不变（只由生效时刻与变更号决定）
    subs = {row["sub_id"]: row for row in store.list_subscriptions(run_id)}
    changes = store.list_changes(run_id)
    for sub_id in ("SUB-1001", "SUB-1008", "SUB-1010", "SUB-1015"):
        sub = subs[sub_id]
        own = [row for row in changes if row["sub_id"] == sub_id]
        forward = segment_mod.build_segments(sub, own)
        backward = segment_mod.build_segments(sub, list(reversed(own)))
        assert [(item.days, item.start, item.plan) for item in forward] == [
            (item.days, item.start, item.plan) for item in backward]


def test_period_days_conservation(run_id, store):
    # TRAP-23：逐张账单与合计两层，计费 + 免费都等于期间天数
    invoices = store.list_invoices(run_id)
    assert sum(row["period_days"] for row in invoices) == expected.PERIOD_DAYS
    assert all(row["billed_days"] + row["free_days"] == row["period_days"]
               for row in invoices)
    assert sum(row["billed_days"] for row in invoices) == expected.BILLED_DAYS


def test_export_totals_match_invoices(client):
    client.post("/api/subscriptions/import", json={})
    import csv
    import io

    text = client.get("/api/export/invoices.csv").text
    rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    total = sum((Decimal(row["账单额(元)"]) for row in rows), Decimal("0"))
    assert total == Decimal(expected.TOTAL_CENTS) / 100
    assert len(rows) == expected.INVOICE_COUNT


def test_json_amounts_are_strings(client):
    # 金额与分在 JSON 里是字符串/整数，不经过 float 往返
    client.post("/api/subscriptions/import", json={})
    totals = client.get("/api/reconcile").json()["totals"]
    assert isinstance(totals["invoice_cents"], str)
    assert totals["invoice_cents"] == str(expected.TOTAL_CENTS)
    assert isinstance(totals["charge_cents"], str)
