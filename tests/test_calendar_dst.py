"""M2 本地时刻定位：夏令时重叠/跳过、同一瞬间两种写法。"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from app.modules.m2_calendar import halfopen
from app.modules.m3_quality import rules

NEW_YORK = ZoneInfo("America/New_York")
SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_dst_ambiguous_takes_earlier_offset():
    # TRAP-12：11 月 1 日 01:30 在纽约出现两次，取较早的一次并打标记
    utc, flag = halfopen.resolve_instant(dt.datetime(2026, 11, 1, 1, 30), NEW_YORK)
    assert flag == "R_DST_AMBIGUOUS"
    assert utc == dt.datetime(2026, 11, 1, 5, 30, tzinfo=dt.timezone.utc)


def test_dst_gap_shifts_forward():
    # TRAP-12：3 月 8 日 02:30 在纽约不存在，顺延到 03:30 并打标记
    utc, flag = halfopen.resolve_instant(dt.datetime(2026, 3, 8, 2, 30), NEW_YORK)
    assert flag == "R_DST_GAP"
    assert utc == dt.datetime(2026, 3, 8, 7, 30, tzinfo=dt.timezone.utc)


def test_same_instant_two_spellings():
    # TRAP-11：Z 与 +08:00 写的是同一瞬间，必须落到同一个本地日
    with_z = rules.parse_instant("2026-02-05T00:00:00Z").value
    with_offset = rules.parse_instant("2026-02-05T08:00:00+08:00").value
    first = with_z.naive.replace(tzinfo=with_z.offset).astimezone(dt.timezone.utc)
    second = with_offset.naive.replace(tzinfo=with_offset.offset).astimezone(
        dt.timezone.utc)
    assert first == second
    assert first.astimezone(SHANGHAI).date() == dt.date(2026, 2, 5)


def test_offset_forms_equal():
    compact = rules.parse_instant("2026-02-05T08:00:00+0800").value
    colon = rules.parse_instant("2026-02-05T08:00:00+08:00").value
    assert compact.offset.utcoffset(None) == colon.offset.utcoffset(None) == dt.timedelta(
        hours=8)


def test_zone_name_in_field_and_subscription_zone(sample_dir):
    # 字段自带时区名优先；没有偏移时用订阅时区
    parsed = rules.parse_instant("2026-11-01 01:30:00 America/New_York").value
    assert parsed.zone_name == "America/New_York"
    zone = rules.parse_zone("America/New_York").value
    assert zone is not None
    utc, flag = halfopen.resolve_instant(parsed.naive, zone)
    assert flag == "R_DST_AMBIGUOUS"
    assert rules.parse_zone("+08:00").value.utcoffset(None) == dt.timedelta(hours=8)
    assert rules.parse_zone("Mars/Olympus").code == "R_TZ_UNKNOWN"
