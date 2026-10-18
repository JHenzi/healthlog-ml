"""The Companion day: time zone + day boundary, DST-safe (R14, risks.md B1/B2)."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app.timeutil import boundary_interval, day_bounds, local_day

NY = ZoneInfo("America/New_York")
FOUR = dt.time(4, 0)


def test_boundary_0359_belongs_to_previous_day():
    assert local_day(dt.datetime(2026, 10, 17, 3, 59, tzinfo=NY), NY, FOUR) == dt.date(2026, 10, 16)
    assert local_day(dt.datetime(2026, 10, 17, 4, 0, tzinfo=NY), NY, FOUR) == dt.date(2026, 10, 17)


def test_utc_timestamp_lands_on_local_day():
    # 05:30 UTC = 01:30 EDT: still the previous evening's day.
    assert local_day(dt.datetime(2026, 10, 17, 5, 30, tzinfo=dt.UTC), NY, FOUR) == dt.date(2026, 10, 16)


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValueError):
        local_day(dt.datetime(2026, 10, 17, 12, 0), NY, FOUR)  # noqa: DTZ001 - the point of the test


def _hours(day: dt.date) -> float:
    start, end = day_bounds(day, NY, FOUR)
    # Same-zone subtraction in Python is wall-clock; compare real elapsed time in UTC.
    return (end.astimezone(dt.UTC) - start.astimezone(dt.UTC)) / dt.timedelta(hours=1)


def test_dst_days_are_23_and_25_hours():
    # The 02:00 switch falls before the 04:00 boundary, so it lands in the *previous* Companion day.
    assert _hours(dt.date(2026, 3, 7)) == 23  # 04:00 Mar 7 -> 04:00 Mar 8 (spring forward)
    assert _hours(dt.date(2026, 10, 31)) == 25  # 04:00 Oct 31 -> 04:00 Nov 1 (fall back)
    assert _hours(dt.date(2026, 3, 8)) == 24
    assert _hours(dt.date(2026, 11, 1)) == 24


def test_bounds_and_local_day_agree():
    start, end = day_bounds(dt.date(2026, 11, 1), NY, FOUR)
    assert local_day(start, NY, FOUR) == dt.date(2026, 11, 1)
    assert local_day(end - dt.timedelta(seconds=1), NY, FOUR) == dt.date(2026, 11, 1)
    assert local_day(end, NY, FOUR) == dt.date(2026, 11, 2)


def test_boundary_interval():
    assert boundary_interval(dt.time(4, 30)) == "4 hours 30 minutes"
