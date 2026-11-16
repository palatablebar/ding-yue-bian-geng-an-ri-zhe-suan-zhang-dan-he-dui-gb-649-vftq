"""M2 期间日历：半开区间、闰日、相邻段不重不漏、接口返回结构。"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import expected
from app.modules.m2_calendar import days as days_mod
from app.modules.m2_calendar import halfopen

FIXTURES = Path(__file__).parent / "fixtures"


def _plan_cases() -> list[dict]:
    lines = (FIXTURES / "plan_cases.csv").read_text(encoding="utf-8").splitlines()
    head = lines[0].split(",")
    return [dict(zip(head, line.split(","))) for line in lines[1:] if line.strip()]


def test_plan_cases_from_fixture():
    # TRAP-23：日期区间一律半开，端点归属固定
    for case in _plan_cases():
        start = dt.date.fromisoformat(case["start"])
        end = dt.date.fromisoformat(case["end"])
        assert days_mod.days(start, end) == int(case["days"]), case
        assert int(days_mod.contains_leap_day(start, end)) == int(case["leap"]), case
        assert int(days_mod.is_leap(start.year)) == int(case["leap_year"]), case


def test_adjacent_segments_cover_period(run_id, store):
    # TRAP-23：相邻段首尾相接，天数合计等于期间天数
    subs = {row["sub_id"]: row for row in store.list_subscriptions(run_id)}
    grouped: dict[str, list[dict]] = {}
    for segment in store.list_segments(run_id):
        grouped.setdefault(segment["invoice_id"], []).append(segment)
    for invoice_id, rows in grouped.items():
        rows.sort(key=lambda item: item["seq"])
        sub = subs[rows[0]["sub_id"]]
        assert sum(row["days"] for row in rows) == sub["period_days"]
        for left, right in zip(rows, rows[1:]):
            assert left["end_date"] == right["start_date"]
        assert rows[0]["start_date"] == sub["period_start"]
        assert rows[-1]["end_date"] == sub["period_end"]


def test_leap_day_boundary():
    leap_day = dt.date(2028, 2, 29)
    assert days_mod.contains_leap_day(leap_day, dt.date(2028, 3, 1))
    # 半开区间：右端不含，[2-01, 2-29) 不含 2 月 29 日
    assert not days_mod.contains_leap_day(dt.date(2028, 2, 1), leap_day)
    assert not days_mod.contains_leap_day(dt.date(2028, 3, 1), dt.date(2028, 3, 2))


def test_overlap_and_merge():
    jan = (dt.date(2026, 2, 1), dt.date(2026, 2, 11))
    feb = (dt.date(2026, 2, 5), dt.date(2026, 3, 1))
    assert halfopen.overlaps(*jan, *feb)
    assert halfopen.covered_days([jan, feb]) == 28
    assert halfopen.intersect(*jan, *feb) == (dt.date(2026, 2, 5), dt.date(2026, 2, 11))
    assert halfopen.intersect(dt.date(2026, 2, 1), dt.date(2026, 2, 5),
                              dt.date(2026, 2, 5), dt.date(2026, 3, 1)) is None


def test_period_rows_api(client, run_data):
    response = client.get("/api/calendar")
    assert response.status_code == 200
    data = response.json()
    assert data["half_open"] is True
    assert data["totals"]["subscriptions"] == expected.INVOICE_COUNT
    assert data["totals"]["days"] == expected.PERIOD_DAYS
    assert data["totals"]["leap_periods"] == 1


def test_days_query_and_month(client):
    response = client.get("/api/calendar/days", params={"start": "2028-02-01",
                                                       "end": "2028-03-01"})
    assert response.status_code == 200
    assert response.json()["days"] == 29
    month = client.get("/api/calendar/month", params={"year": 2028, "month": 2})
    assert month.json()["days"] == 29
    bad = client.get("/api/calendar/days", params={"start": "2026-03-01",
                                                  "end": "2026-02-01"})
    assert bad.status_code == 400
