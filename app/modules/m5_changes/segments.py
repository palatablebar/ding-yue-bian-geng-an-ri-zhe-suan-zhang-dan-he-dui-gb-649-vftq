"""变更分段：把一张订阅的一个计费期间切成互不重叠的连续区间。

三条硬规则：
1. 区间半开 ``[start, end)``：相邻段首尾相接，不重不漏；
2. 生效时刻先归一成本地日，再按日切段：同日多次变更由 M3 定出唯一生效条；
3. 段的顺序只由 (本地日, UTC, 变更号) 决定，与文件里的行序无关。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from ... import config, reasons


@dataclass
class Segment:
    seq: int
    start: dt.date
    end: dt.date
    days: int
    plan: str
    state: str
    monthly: Decimal
    flags: list[str] = field(default_factory=list)
    change_id: str = ""


def parse_price(value) -> Decimal:
    text = str(value or "").strip()
    if not text:
        return Decimal("0")
    return Decimal(text)


def initial_state(sub: dict) -> tuple[str, str, Decimal]:
    return sub["plan"], sub["state"], parse_price(sub["monthly"])


def apply_change(plan: str, monthly: Decimal, change: dict) -> tuple[str, str, Decimal]:
    """按变更类型推出新的 (套餐, 状态, 月价)。"""
    kind = change["kind"]
    state = config.KIND_EFFECT[kind]
    new_plan = change["new_plan"] or plan
    price = parse_price(change["new_price"]) if change["new_price"] not in ("", None) else monthly
    if kind in {"pause", "cancel"}:
        new_plan = plan
        price = monthly
    return new_plan, state, price


def applicable_changes(sub: dict, changes: list[dict]) -> list[dict]:
    start = dt.date.fromisoformat(sub["period_start"])
    end = dt.date.fromisoformat(sub["period_end"])
    picked = [
        change for change in changes
        if change["applied"] and start <= dt.date.fromisoformat(change["local_date"]) < end
    ]
    picked.sort(key=lambda item: (item["local_date"], item["effective_utc"],
                                  item["change_id"], item["seq"]))
    return picked


def build_segments(sub: dict, changes: list[dict]) -> list[Segment]:
    """返回含零天段的完整切分（零天段用于表达「期间首日就变更」）。"""
    start = dt.date.fromisoformat(sub["period_start"])
    end = dt.date.fromisoformat(sub["period_end"])
    plan, state, monthly = initial_state(sub)
    segments: list[Segment] = []
    cursor = start
    for change in applicable_changes(sub, changes):
        day = dt.date.fromisoformat(change["local_date"])
        segments.append(Segment(
            seq=len(segments), start=cursor, end=day, days=max((day - cursor).days, 0),
            plan=plan, state=state, monthly=monthly,
        ))
        plan, state, monthly = apply_change(plan, monthly, change)
        cursor = day
    segments.append(Segment(
        seq=len(segments), start=cursor, end=end, days=max((end - cursor).days, 0),
        plan=plan, state=state, monthly=monthly,
    ))
    # 段标记：段由哪条变更开启就带上那条变更的复核标记（info 级留在订阅与价格层）
    flag_by_day: dict[str, tuple[str, list[str]]] = {}
    for change in applicable_changes(sub, changes):
        review = [code for code in change["flags"] if reasons.level_of(code) == "warn"]
        flag_by_day[change["local_date"]] = (change["change_id"], review)
    for segment in segments[1:]:
        change_id, flags = flag_by_day.get(segment.start.isoformat(), ("", []))
        segment.change_id = change_id
        segment.flags = flags
    return segments


def billable_segments(segments: list[Segment]) -> list[Segment]:
    """落库与展示只保留有正天数的段；零天段已在变更表里可查。"""
    return [segment for segment in segments if segment.days > 0]


def segment_rows(invoice_id: str, sub: dict, segments: list[Segment]) -> list[dict]:
    rows = []
    for index, segment in enumerate(billable_segments(segments)):
        rows.append({
            "invoice_id": invoice_id,
            "sub_id": sub["sub_id"],
            "seq": index,
            "start_date": segment.start.isoformat(),
            "end_date": segment.end.isoformat(),
            "days": segment.days,
            "plan": segment.plan,
            "state": segment.state,
            "monthly": str(segment.monthly),
            "amount_exact": "0",
            "amount_cents": 0,
            "flags": segment.flags,
        })
    return rows


def day_ledger(segments: list[Segment]) -> dict:
    """计费天数 / 免费暂停天数：两者之和必须等于期间天数。"""
    billed = sum(segment.days for segment in segments
                 if segment.state not in config.ZERO_RATE_STATES)
    free = sum(segment.days for segment in segments
               if segment.state in config.ZERO_RATE_STATES)
    return {"billed_days": billed, "free_days": free, "days": billed + free}
