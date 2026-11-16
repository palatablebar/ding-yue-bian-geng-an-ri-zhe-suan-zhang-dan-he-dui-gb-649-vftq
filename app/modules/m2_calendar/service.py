"""M2 期间日历：天数、闰年、半开区间、本地日边界。

上游是 M3 归一后的订阅行；下游给 M4 折算（日价分母）与 M5 分段（生效日归属）。
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from ... import config
from ...errors import BadRequest
from . import days as days_mod
from . import halfopen


def zone_info(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception as exc:  # noqa: BLE001 - 非法时区名统一转 400
        raise BadRequest(f"时区无法解析：{name}", code="E_TZ_UNKNOWN") from exc


def period_of(period_start: str, period_end: str) -> tuple[dt.date, dt.date]:
    return dt.date.fromisoformat(period_start), dt.date.fromisoformat(period_end)


def period_days(period_start: str, period_end: str) -> int:
    start, end = period_of(period_start, period_end)
    return days_mod.days(start, end)


def leap_of(period_start: str, period_end: str) -> bool:
    start, end = period_of(period_start, period_end)
    return days_mod.contains_leap_day(start, end)


def period_rows(store, run_id: str) -> list[dict]:
    """按订阅输出期间日历行：天数、闰日、半开区间标签。"""
    rows = []
    for sub in store.list_subscriptions(run_id):
        start, end = period_of(sub["period_start"], sub["period_end"])
        length = days_mod.days(start, end)
        rows.append({
            "sub_id": sub["sub_id"],
            "account": sub["account"],
            "plan": sub["plan"],
            "timezone": sub["tz"],
            "period_start": sub["period_start"],
            "period_end": sub["period_end"],
            "range_label": days_mod.range_label(start, end),
            "days": length,
            "month_days": days_mod.month_days(start.year, start.month),
            "leap": days_mod.contains_leap_day(start, end),
            "leap_year": days_mod.is_leap(start.year),
            "cross_month": (start.month != end.month or start.year != end.year),
            "row_no": sub["row_no"],
            "flags": list(sub["flags"]),
        })
    return rows


def period_totals(rows: list[dict]) -> dict:
    return {
        "subscriptions": len(rows),
        "days": sum(row["days"] for row in rows),
        "leap_periods": sum(1 for row in rows if row["leap"]),
        "cross_month": sum(1 for row in rows if row["cross_month"]),
    }


def days_query(start: str, end: str) -> dict:
    """任意区间的天数核算（页面与接口共用，含闰日与半开说明标签）。"""
    try:
        left = dt.date.fromisoformat(start)
        right = dt.date.fromisoformat(end)
    except ValueError as exc:
        raise BadRequest("日期格式应为 YYYY-MM-DD", code="E_BAD_DATE") from exc
    length = days_mod.days(left, right)
    if length == 0:
        raise BadRequest("期间止必须晚于期间起", code="E_PERIOD_REVERSED")
    return {
        "start": left.isoformat(),
        "end": right.isoformat(),
        "range_label": days_mod.range_label(left, right),
        "days": length,
        "half_open": True,
        "leap": days_mod.contains_leap_day(left, right),
        "leap_year": days_mod.is_leap(left.year),
        "month_days": days_mod.month_days(left.year, left.month),
    }


def month_query(year: int, month: int) -> dict:
    if not 1 <= month <= 12:
        raise BadRequest("月份应在 1..12 之间", code="E_BAD_MONTH")
    if not 1970 <= year <= 2200:
        raise BadRequest("年份超出可计费范围", code="E_BAD_YEAR")
    first, last = days_mod.month_bounds(year, month)
    return {
        "year": year,
        "month": month,
        "label": days_mod.month_label(year, month),
        "start": first.isoformat(),
        "end": last.isoformat(),
        "days": days_mod.month_days(year, month),
        "leap_year": days_mod.is_leap(year),
    }


def resolve_effective(naive: dt.datetime, tz: dt.tzinfo) -> tuple[dt.datetime, str | None]:
    return halfopen.resolve_instant(naive, tz)


def effective_date(moment_utc: dt.datetime, tz: dt.tzinfo) -> dt.date:
    return halfopen.local_date(moment_utc, tz)


def timezone_of(name: str | None) -> ZoneInfo:
    return zone_info(name or config.DISPLAY_TZ)
