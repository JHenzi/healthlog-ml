"""Sleep timing (reflection-and-prediction.md §4d) and clock-time display. Synthetic sessions only (R4)."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app import clock
from app.features import assemble
from app.sleeptiming import FAMILY, nights, timing_features
from app.upstream import SleepSession

NY = ZoneInfo("America/New_York")


def _at(day: dt.date, h: int, m: int = 0) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, h, m, tzinfo=NY)


def _night(wake: dt.date, bed=(23, 0), up=(7, 0), source="Watch") -> SleepSession:
    """A night from ``bed`` the evening before ``wake`` to ``up`` on it (bed after midnight if before 18:00)."""
    evening = wake - dt.timedelta(days=1)
    start = _at(evening if bed[0] >= 18 else wake, *bed)
    end = _at(wake, *up)
    return SleepSession(start, end, source, (end - start).total_seconds() / 3600 - 0.5)


W = dt.date(2026, 10, 16)


def test_bedtime_wake_time_and_midpoint():
    f = timing_features([_night(W, (23, 30), (7, 30))], NY)
    assert f["sleep.bedtime"] == {W: 330.0}  # 23:30 is 5 h 30 min after 18:00
    assert f["sleep.wake_time"] == {W: 450.0}  # 7:30
    assert f["sleep.midpoint"] == {W: 570.0}  # 03:30


def test_bedtime_after_midnight_sorts_after_one_before_it():
    late = timing_features([_night(W, (1, 30), (8, 0))], NY)["sleep.bedtime"][W]
    early = timing_features([_night(W, (23, 30), (8, 0))], NY)["sleep.bedtime"][W]
    assert late == 450.0 and late > early


def test_a_night_split_by_a_short_wake_is_one_night():
    first = SleepSession(_at(W - dt.timedelta(days=1), 23, 0), _at(W, 3, 0), "Watch", 4.0)
    second = SleepSession(_at(W, 3, 40), _at(W, 7, 0), "Watch", 3.2)
    n = nights([first, second], NY)[W]
    assert n.start == first.start and n.end == second.end and n.total_h == pytest.approx(7.2)


def test_a_nap_is_not_the_night():
    nap = SleepSession(_at(W, 14, 0), _at(W, 15, 0), "Watch", 1.0)
    f = timing_features([_night(W), nap], NY)
    assert f["sleep.wake_time"] == {W: 420.0}  # 7:00, not 15:00


def test_a_day_with_only_a_nap_has_no_timing():
    nap = SleepSession(_at(W, 14, 0), _at(W, 15, 30), "Watch", 1.5)
    assert all(not v for v in timing_features([nap], NY).values())  # missing, not an afternoon wake (R7)


def test_one_source_per_night_the_one_with_most_sleep():
    phone = SleepSession(_at(W - dt.timedelta(days=1), 22, 0), _at(W, 5, 0), "iPhone", 4.0)
    f = timing_features([phone, _night(W, (23, 0), (7, 0), "Watch")], NY)
    assert f["sleep.bedtime"] == {W: 300.0}  # the Watch's 23:00, never a blend of the two


def test_dst_night_keeps_the_wall_clock():
    fall_back = dt.date(2026, 11, 1)  # clocks go back at 2:00 in New York
    f = timing_features([_night(fall_back, (23, 0), (7, 0))], NY)
    assert f["sleep.bedtime"][fall_back] == 300.0 and f["sleep.wake_time"][fall_back] == 420.0


def test_usual_and_spread_need_enough_nights_and_use_only_the_past():
    days = [W + dt.timedelta(days=i) for i in range(20)]
    sessions = [_night(d, (23, 0), (7, 0)) for d in days[:-1]] + [_night(days[-1], (0, 0), (8, 0))]
    f = timing_features(sessions, NY)
    assert days[12] not in f["sleep.midpoint_vs_usual"]  # 12 nights before it: too few
    assert f["sleep.midpoint_vs_usual"][days[-1]] == 60.0  # an hour later than the usual 03:00
    assert f["sleep.midpoint_vs_usual"][days[-2]] == 0.0  # the late night after it isn't in its usual
    assert days[3] not in f["sleep.timing_spread"] and f["sleep.timing_spread"][days[5]] == 0.0
    assert f["sleep.timing_spread"][days[-1]] > 0


def test_assemble_adds_timing_in_its_own_family():
    fs = assemble([], {}, [], [], {}, [], [], NY, dt.time(4, 0), [_night(W)])
    assert fs.defs["sleep.bedtime"].family == FAMILY != "sleep"
    assert fs.defs["sleep.bedtime"].unit == clock.AFTER_EVENING
    assert "sleep.midpoint_vs_usual" not in fs.defs  # no values yet -> no feature


def test_clock_text_and_shift_text():
    assert clock.clock_text(330, clock.AFTER_EVENING) == "23:30"
    assert clock.clock_text(450, clock.AFTER_EVENING) == "1:30"
    assert clock.clock_text(450, clock.AFTER_MIDNIGHT) == "7:30"
    assert clock.shift_text(35) == "35 min later"
    assert clock.shift_text(-70) == "1 h 10 min earlier"


def test_wall_minutes_refuses_naive_times():
    with pytest.raises(ValueError):
        clock.wall_minutes(dt.datetime(2026, 1, 1), NY, W, clock.EVENING)  # noqa: DTZ001
