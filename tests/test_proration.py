"""M4 按日折算：日价精度、整期守恒、零费率、分段合计。"""
from __future__ import annotations

from decimal import Decimal

import expected
from app import config
from app.modules.m4_proration import prorate
from app.modules.m4_proration import rounding


def test_daily_rate_exact():
    daily = prorate.daily_rate(Decimal("1200.00"), 28)
    # 日价不预先四舍五入，保留完整精度
    assert daily * 28 == Decimal("1200.00")
    assert str(daily).startswith("42.857142857142857")


def test_share_keeps_total():
    total = sum(prorate.share(Decimal("1200.00"), days, 28) for days in (2, 8, 18))
    assert prorate.quantize_exact(total) == Decimal("1200.00000000")


def test_invoice_totals_match_expected(run_id, store):
    # TRAP-10：全程 Decimal 与整数分，不允许浮点累加误差
    invoices = {row["invoice_id"]: row for row in store.list_invoices(run_id)}
    assert set(invoices) == set(expected.INVOICE_CENTS)
    for invoice_id, cents in expected.INVOICE_CENTS.items():
        assert invoices[invoice_id]["total_cents"] == cents, invoice_id
    assert sum(row["total_cents"] for row in invoices.values()) == expected.TOTAL_CENTS


def test_zero_rate_states():
    for state in ("paused", "trial", "cancelled"):
        assert prorate.rate_for(Decimal("2400.00"), state) == 0
        assert prorate.segment_amount(Decimal("2400.00"), 10, 28, state) == 0
    assert prorate.segment_amount(Decimal("2400.00"), 10, 28, "active") > 0


def test_segment_cents_sum_equals_invoice(run_id, store):
    # TRAP-24：每张账单的分段分合计必须等于账单额（尾差已按最大余额分掉）
    invoices = {row["invoice_id"]: row for row in store.list_invoices(run_id)}
    grouped: dict[str, int] = {}
    for segment in store.list_segments(run_id):
        grouped[segment["invoice_id"]] = (grouped.get(segment["invoice_id"], 0)
                                          + int(segment["amount_cents"]))
    for invoice_id, cents in grouped.items():
        assert cents == invoices[invoice_id]["total_cents"], invoice_id
    assert sum(grouped.values()) == expected.TOTAL_CENTS


def test_segment_rows_carry_daily_price(run_id, store):
    from app.modules.m4_proration import service as proration_service

    rows = proration_service.segment_rows(store, run_id)
    leap = [row for row in rows if row["invoice_id"] == "INV-202802-SUB-1007"]
    # 闰年 29 天：第一段 1160/29
    assert leap[0]["period_days"] == 29
    assert Decimal(leap[0]["daily"]) * 29 == Decimal("1160.00")
    # 1160/29 = 40.00 每天，前 14 天正好 560.00
    assert leap[0]["days"] == 14
    assert rounding.cents_text(leap[0]["amount_cents"]) == "560.00"
    assert config.MONEY_UNIT == "元"
