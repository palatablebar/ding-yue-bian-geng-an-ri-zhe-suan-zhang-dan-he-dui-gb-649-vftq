"""尾差分配：最大余额法，把精确金额分到「分」，保证合计等于四舍五入后的总额。

规则：
- 每个分量先向下取整到分（负数按数轴向下，抵扣额度是负数也成立）；
- 差额按「小数余额从大到小」逐分补，余额相同按序号先后，结果与输入顺序确定相关；
- 分配后 Σ分量（分）= 四舍五入后的总额（分），不允许出现 1 分钱对不平的账单。
"""
from __future__ import annotations

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, localcontext

from ... import config

CENT_FACTOR = Decimal("100")
ONE = Decimal("1")


def to_cents(exact: Decimal) -> int:
    """精确金额 → 分（四舍五入）。"""
    return int((Decimal(exact) * CENT_FACTOR).quantize(ONE, rounding=ROUND_HALF_UP))


def total_cents(exacts) -> int:
    with localcontext() as ctx:
        ctx.prec = config.DECIMAL_PREC
        return to_cents(sum((Decimal(value) for value in exacts), Decimal("0")))


def allocate(exacts) -> list[int]:
    """最大余额法：返回每个分量应记的「分」。"""
    values = [Decimal(value) for value in exacts]
    if not values:
        return []
    cents = [value * CENT_FACTOR for value in values]
    floors = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in cents]
    remainders = [value - Decimal(floor) for value, floor in zip(cents, floors)]
    target = total_cents(values)
    diff = target - sum(floors)
    if not 0 <= diff <= len(values):
        raise ValueError(f"尾差分配越界：diff={diff} n={len(values)}")
    order = sorted(range(len(values)), key=lambda index: (-remainders[index], index))
    result = floors[:]
    for index in order[:diff]:
        result[index] += 1
    return result


def cents_text(cents: int) -> str:
    return f"{Decimal(int(cents)) / CENT_FACTOR:.2f}"


def sum_cents(values) -> int:
    return sum(int(value) for value in values)
