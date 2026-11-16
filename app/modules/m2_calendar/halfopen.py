"""半开区间运算与本地时刻定位。

两条硬规则：
1. 区间一律 ``[start, end)``：相邻区间首尾相接，不重不漏；
2. 本地时刻先定位到具体 UTC 瞬间再排序：夏令时重叠段取较早的一次（fold=0），
   跳过段顺延到合法时刻，两种情况都打标记，绝不静默改值。
"""
from __future__ import annotations

import datetime as dt

from ... import config


def intersect(a_start: dt.date, a_end: dt.date,
              b_start: dt.date, b_end: dt.date) -> tuple[dt.date, dt.date] | None:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return (start, end) if start < end else None


def overlaps(a_start: dt.date, a_end: dt.date,
             b_start: dt.date, b_end: dt.date) -> bool:
    return intersect(a_start, a_end, b_start, b_end) is not None


def merge(intervals: list[tuple[dt.date, dt.date]]) -> list[tuple[dt.date, dt.date]]:
    """合并重叠/相接的半开区间；空输入返回空列表。"""
    ordered = sorted((start, end) for start, end in intervals if start < end)
    merged: list[tuple[dt.date, dt.date]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def covered_days(intervals: list[tuple[dt.date, dt.date]]) -> int:
    return sum((end - start).days for start, end in merge(intervals))


def _localize(naive: dt.datetime, zone: dt.tzinfo) -> tuple[dt.datetime, str | None]:
    """把不带时区的本地时刻定位到带时区的瞬间，返回 (时刻, 标记码)。"""
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)
    if first.utcoffset() == second.utcoffset():
        return first, None
    round_trip = first.astimezone(dt.timezone.utc).astimezone(zone).replace(tzinfo=None)
    if round_trip != naive:
        # 本地时刻不存在（春季跳过段）：按偏移差顺延到第一个合法时刻
        shifted = naive + (second.utcoffset() - first.utcoffset())
        return shifted.replace(tzinfo=zone, fold=0), "R_DST_GAP"
    # 本地时刻出现两次（秋季重叠段）：取较早的一次，标记后由人工复核
    return first, "R_DST_AMBIGUOUS"


def resolve_instant(naive: dt.datetime, zone: dt.tzinfo) -> tuple[dt.datetime, str | None]:
    """本地时刻 → UTC 瞬间（入库统一 UTC）。"""
    localized, flag = _localize(naive, zone)
    return localized.astimezone(config.UTC), flag


def resolve_offset(naive: dt.datetime, offset: dt.tzinfo) -> dt.datetime:
    """带固定偏移的时刻 → UTC。"""
    return naive.replace(tzinfo=offset).astimezone(config.UTC)


def local_date(moment: dt.datetime, zone: dt.tzinfo) -> dt.date:
    return moment.astimezone(zone).date()


def local_midnight(day: dt.date, zone: dt.tzinfo) -> dt.datetime:
    """本地日 0 点对应的 UTC 瞬间；跨夏令时也取当日真实 0 点。"""
    base = dt.datetime.combine(day, dt.time(0, 0))
    localized, _ = _localize(base, zone)
    return localized.astimezone(config.UTC)
