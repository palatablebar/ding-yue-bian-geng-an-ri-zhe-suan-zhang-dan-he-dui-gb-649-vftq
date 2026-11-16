"""变更抵扣：预缴整期 + 每次变更「抵扣旧套餐剩余额度、补收新套餐剩余额度」。

净额恒等式（望远镜求和）：
    账单 = 整期预缴 − Σ抵扣 + Σ补收 = Σ(各段费率 × 段天数)
任何一张账单都必须满足这条恒等式，测试拿它当不变量。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..m4_proration import prorate
from .segments import Segment


@dataclass
class Component:
    seq: int
    kind: str            # charge / credit
    source: str          # base / change:<变更号>
    label: str
    days: int
    monthly: Decimal
    exact: Decimal
    flags: list[str] = field(default_factory=list)


def _rate(segment: Segment) -> Decimal:
    return prorate.rate_for(segment.monthly, segment.state)


def build_components(segments: list[Segment], period_days: int) -> list[Component]:
    """按段序列生成「预缴 / 抵扣 / 补收」三类行；金额一律精确 Decimal。"""
    if not segments:
        return []
    components: list[Component] = []
    first = segments[0]
    base_rate = _rate(first)
    components.append(Component(
        seq=0, kind="charge", source="base", label="整期预缴",
        days=period_days, monthly=first.monthly,
        exact=prorate.share(base_rate, period_days, period_days),
    ))
    for index in range(1, len(segments)):
        previous = segments[index - 1]
        current = segments[index]
        # 剩余天数 = 期间天数 − 已经走过的段天数（等价于 current.start 到期间止）
        remaining = period_days - sum(segment.days for segment in segments[:index])
        credit_exact = prorate.share(_rate(previous), remaining, period_days)
        charge_exact = prorate.share(_rate(current), remaining, period_days)
        change_id = current.change_id or f"seg{index}"
        components.append(Component(
            seq=len(components), kind="credit", source=f"change:{change_id}",
            label="抵扣剩余", days=remaining, monthly=previous.monthly,
            exact=-credit_exact, flags=list(current.flags),
        ))
        components.append(Component(
            seq=len(components), kind="charge", source=f"change:{change_id}",
            label="补收剩余", days=remaining, monthly=current.monthly,
            exact=charge_exact, flags=list(current.flags),
        ))
    return components


def net_exact(components: list[Component]) -> Decimal:
    return prorate.net_exact([component.exact for component in components])


def segment_exact(segments: list[Segment], period_days: int) -> Decimal:
    return prorate.net_exact([
        prorate.share(_rate(segment), segment.days, period_days) for segment in segments
    ])


def verify(components: list[Component], segments: list[Segment],
           period_days: int) -> dict:
    """恒等式核对：净额与分段合计的差额（应为 0E-8）。"""
    net = prorate.quantize_exact(net_exact(components))
    by_segment = prorate.quantize_exact(segment_exact(segments, period_days))
    return {"net": net, "by_segment": by_segment, "diff": net - by_segment}


def charged_days(components: list[Component]) -> int:
    """补收行覆盖的天数（不含预缴整期），用于页面复核。"""
    return sum(component.days for component in components
               if component.kind == "charge" and component.source != "base")
