"""Streaks and records (descriptive notes): what counts, what's unknown, and the wording (R7, R10, R13)."""

from __future__ import annotations

import datetime as dt

from app.highlights import RECORD_MIN_DAYS, Def, fmt_value, highlights, record, streak

TODAY = dt.date(2026, 10, 20)
YESTERDAY = TODAY - dt.timedelta(days=1)
STEPS = Def("Steps", None, "healthlog", "continuous")
SLEEP = Def("Sleep (total)", "h", "sleep", "continuous")
MEDITATED = Def("Meditated", None, "tracker", "count")


def _days(values: list[float], last: dt.date) -> dict[dt.date, float]:
    return {last - dt.timedelta(days=len(values) - 1 - i): v for i, v in enumerate(values)}


def test_a_record_needs_enough_history_and_a_new_extreme():
    base = [5000.0 + (i % 7) * 100 for i in range(RECORD_MIN_DAYS - 1)]
    note = record("hl.step_count", STEPS, _days([*base, 9000.0], YESTERDAY), YESTERDAY, TODAY)
    assert note.text == f"Steps: 9,000 yesterday, the highest in {RECORD_MIN_DAYS} days of data."
    assert record("hl.step_count", STEPS, _days([*base[1:], 9000.0], YESTERDAY), YESTERDAY, TODAY) is None
    assert record("hl.step_count", STEPS, _days([*base, 5600.0], YESTERDAY), YESTERDAY, TODAY) is None  # a tie
    low = record("hl.step_count", STEPS, _days([*base, 10.0], YESTERDAY), YESTERDAY, TODAY)
    assert "the lowest in" in low.text and "best" not in low.text and "worst" not in low.text


def test_sleep_records_are_last_night():
    values = _days([7.0] * (RECORD_MIN_DAYS - 1) + [9.25], TODAY)
    assert record("sleep.total_h", SLEEP, values, TODAY, TODAY).text.startswith("Sleep (total): 9 h 15 min last night")


def test_a_streak_counts_recorded_days_only():
    run = _days([0, 1, 1, 1], YESTERDAY)
    assert streak("t", MEDITATED, run, YESTERDAY, TODAY).text == "Meditated: 3 days in a row, through yesterday."
    gap = {**_days([1, 1], YESTERDAY), YESTERDAY - dt.timedelta(days=3): 1.0}  # day -2 unknown: not a streak of 3
    assert streak("t", MEDITATED, gap, YESTERDAY, TODAY) is None
    quiet = _days([1] + [0] * 7, YESTERDAY)
    assert streak("t", MEDITATED, quiet, YESTERDAY, TODAY).text == "Meditated: none for 7 recorded days in a row."
    assert streak("t", MEDITATED, _days([0] * 9, YESTERDAY), YESTERDAY, TODAY) is None  # never used: nothing to say


def test_highlights_put_streaks_first_and_cap_the_list():
    series = {"tracker.meditated.any": _days([1, 1, 1], YESTERDAY)}
    defs = {"tracker.meditated.any": MEDITATED}
    for i in range(6):
        f = f"hl.m{i}"
        series[f] = _days([1.0] * (RECORD_MIN_DAYS - 1) + [2.0], YESTERDAY)
        defs[f] = Def(f"Metric {i}", None, "healthlog", "continuous")
    notes = highlights(series, defs, TODAY)
    assert len(notes) == 4 and notes[0].kind == "streak" and {n.kind for n in notes[1:]} == {"record"}


def test_fmt_value():
    assert fmt_value(18402.0, "count") == "18,402 count"
    assert fmt_value(12.5, "°C") == "12.5 °C" and fmt_value(3.0, None) == "3"
