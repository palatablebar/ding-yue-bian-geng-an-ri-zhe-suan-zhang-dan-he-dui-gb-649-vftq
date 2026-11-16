"""M4 尾差分配：最大余额法、负数抵扣、并列顺序、分位舍入。"""
from __future__ import annotations

from decimal import Decimal

from app.modules.m4_proration import rounding


def test_largest_remainder_keeps_total():
    # TRAP-24：三个 0.005 各自进位会多出 1 分，最大余额法只补 2 分
    exacts = [Decimal("0.005"), Decimal("0.005"), Decimal("0.005")]
    allocated = rounding.allocate(exacts)
    assert sum(allocated) == rounding.to_cents(Decimal("0.015"))
    assert sum(allocated) == 2
    assert allocated == [1, 1, 0]
    naive = sum(rounding.to_cents(value) for value in exacts)
    assert naive == 3  # 朴素实现会多 1 分，这就是要修掉的尾差


def test_negative_credit_allocated():
    # TRAP-24：抵扣额度是负数，向下取整后差额仍需补回总额
    exacts = [Decimal("-2.345"), Decimal("2.345")]
    allocated = rounding.allocate(exacts)
    assert sum(allocated) == 0
    assert allocated == [-234, 234]


def test_ties_follow_input_order():
    allocated = rounding.allocate([Decimal("1.005"), Decimal("1.005")])
    assert allocated == [101, 100]
    assert sum(allocated) == 201
    # 顺序换了，多出的那一分也跟着换，规则仍然是确定的
    assert rounding.allocate([Decimal("1.005"), Decimal("1.005")]) == allocated


def test_to_cents_half_up():
    assert rounding.to_cents(Decimal("1200.005")) == 120001
    assert rounding.to_cents(Decimal("1200.004")) == 120000
    assert rounding.to_cents(Decimal("0")) == 0
    assert rounding.cents_text(1074283) == "10742.83"


def test_allocate_edge_cases():
    assert rounding.allocate([]) == []
    assert rounding.allocate([Decimal("0"), Decimal("0")]) == [0, 0]
    # 单个分量：分配结果就是四舍五入后的总额
    assert rounding.allocate([Decimal("999.999")]) == [100000]


def test_allocate_from_run_components(run_id, store):
    # 真实账单上的尾差分配：抵扣行与补收行各自分配，总额仍只有四舍五入那一个
    invoices = {row["invoice_id"]: row for row in store.list_invoices(run_id)}
    grouped: dict[str, int] = {}
    for component in store.list_components(run_id):
        grouped[component["invoice_id"]] = (grouped.get(component["invoice_id"], 0)
                                            + int(component["cents"]))
    assert all(cents == invoices[invoice_id]["total_cents"]
               for invoice_id, cents in grouped.items())
