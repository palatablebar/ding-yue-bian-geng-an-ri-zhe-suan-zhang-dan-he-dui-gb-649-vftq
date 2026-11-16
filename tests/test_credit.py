"""M5 抵扣：望远镜恒等式、旧价抵扣、暂停零费率、分账一致。"""
from __future__ import annotations

from decimal import Decimal

from app.modules.m4_proration import prorate
from app.modules.m5_changes import credit
from app.modules.m5_changes import segments as segment_mod


def _built(store, run_id, sub_id):
    subs = {row["sub_id"]: row for row in store.list_subscriptions(run_id)}
    changes = [row for row in store.list_changes(run_id) if row["sub_id"] == sub_id]
    return subs[sub_id], segment_mod.build_segments(subs[sub_id], changes)


def test_telescope_identity(run_id, store):
    # TRAP-24：预缴 − 抵扣 + 补收，必须精确等于各段费率 × 段天数
    for sub in store.list_subscriptions(run_id):
        sub_row, built = _built(store, run_id, sub["sub_id"])
        components = credit.build_components(built, sub_row["period_days"])
        check = credit.verify(components, built, sub_row["period_days"])
        assert check["diff"] == Decimal("0E-8"), sub["sub_id"]
        assert check["net"] == check["by_segment"]


def test_credit_uses_previous_monthly(run_id, store):
    sub_row, built = _built(store, run_id, "SUB-1002")
    components = credit.build_components(built, sub_row["period_days"])
    credit_row = [row for row in components if row.kind == "credit"][0]
    expected = -(Decimal("2400") * 24 / 28)
    assert abs(credit_row.exact - expected) < Decimal("0.000001")
    assert credit_row.days == 24
    # 暂停补收为 0：暂停段计 0 但天数保留
    charge_row = [row for row in components if row.kind == "charge"][-1]
    assert charge_row.exact == 0


def test_zero_rate_base_charge_zero(run_id, store):
    # 试用期整期预缴为 0，升级后从变更日补收
    sub_row, built = _built(store, run_id, "SUB-1011")
    components = credit.build_components(built, sub_row["period_days"])
    base = [row for row in components if row.source == "base"][0]
    assert base.exact == 0
    assert base.days == 28
    charge = [row for row in components if row.kind == "charge" and row.source != "base"][0]
    assert charge.days == 9
    assert abs(charge.exact - Decimal("2400") * 9 / 28) < Decimal("0.000001")


def test_resume_charges_remaining_days(run_id, store):
    sub_row, built = _built(store, run_id, "SUB-1010")
    components = credit.build_components(built, sub_row["period_days"])
    assert [(row.kind, row.days) for row in components] == [
        ("charge", 30), ("credit", 30), ("charge", 30), ("credit", 16), ("charge", 16)]
    assert components[-1].exact == Decimal("600") * 16 / 30
    assert credit.charged_days(components) == 46


def test_component_cents_sum_to_invoice(run_id, store):
    # TRAP-24：抵扣行按分分配后，与账单额逐张相等
    invoices = {row["invoice_id"]: row for row in store.list_invoices(run_id)}
    grouped: dict[str, int] = {}
    for component in store.list_components(run_id):
        grouped[component["invoice_id"]] = (grouped.get(component["invoice_id"], 0)
                                            + int(component["cents"]))
    assert set(grouped) == set(invoices)
    for invoice_id, cents in grouped.items():
        assert cents == invoices[invoice_id]["total_cents"]


def test_component_exact_quantized(run_id, store):
    # 入库精度 8 位小数，既能复核又不把 34 位精度铺进数据库
    for component in store.list_components(run_id):
        value = Decimal(component["exact_text"])
        assert value.as_tuple().exponent >= -8
        assert prorate.quantize_exact(value) == value
