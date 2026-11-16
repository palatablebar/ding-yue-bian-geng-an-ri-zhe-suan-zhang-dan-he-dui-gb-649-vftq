"""按日折算：日价 = 月价 / 期间实际天数，含闰日。

所有中间值用 Decimal（34 位上下文），只在记账时才量化到分；
``share`` 是唯一的份额公式，分段金额、抵扣额度、补收额度都走它。
"""
from __future__ import annotations

import decimal
from decimal import Decimal

from ... import config

ZERO = Decimal("0")
EXACT_SCALE = Decimal("0.00000001")


def daily_rate(monthly: Decimal, period_days: int) -> Decimal:
    """日价：不做四舍五入，保留完整精度，避免逐日累加放大误差。"""
    if period_days <= 0:
        raise ValueError("期间天数必须为正")
    with decimal.localcontext() as ctx:
        ctx.prec = config.DECIMAL_PREC
        return Decimal(monthly) / Decimal(period_days)


def share(monthly: Decimal, days: int, period_days: int) -> Decimal:
    """一段区间的精确金额：月价 × 天数 / 期间天数（同一分母，先乘后除）。"""
    if period_days <= 0:
        raise ValueError("期间天数必须为正")
    if days <= 0:
        return ZERO
    with decimal.localcontext() as ctx:
        ctx.prec = config.DECIMAL_PREC
        return (Decimal(monthly) * Decimal(days)) / Decimal(period_days)


def rate_for(monthly: Decimal, state: str) -> Decimal:
    """零费率状态（暂停/试用/取消）返回 0，但天数照常记录。"""
    return ZERO if state in config.ZERO_RATE_STATES else Decimal(monthly)


def segment_amount(monthly: Decimal, days: int, period_days: int, state: str) -> Decimal:
    return share(rate_for(monthly, state), days, period_days)


def quantize_exact(value: Decimal) -> Decimal:
    """入库精度 8 位小数：够证据用，又不把 34 位精度铺进数据库。"""
    return Decimal(value).quantize(EXACT_SCALE, rounding=decimal.ROUND_HALF_UP)


def exact_text(value: Decimal) -> str:
    return str(quantize_exact(value))


def net_exact(values) -> Decimal:
    with decimal.localcontext() as ctx:
        ctx.prec = config.DECIMAL_PREC
        return sum((Decimal(value) for value in values), ZERO)
