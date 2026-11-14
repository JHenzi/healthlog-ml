"""Momentum notes: workout runs, the week's count, above-your-usual runs and week-on-week rises (R7, R13)."""

from __future__ import annotations

import datetime as dt

from app.momentum import ACTIVITY, MAX_NOTES, WORKOUT, above_usual, momentum, week_on_week, workout_notes

TODAY = dt.date(2026, 11, 13)  # a Friday
YESTERDAY = TODAY - dt.timedelta(days=1)


def _ago(*days: int, minutes: float = 30.0) -> dict[dt.date, float]:
    return {TODAY - dt.timedelta(days=d): minutes for d in days}


def _days(values: list[float], last: dt.date) -> dict[dt.date, float]:
    return {last - dt.timedelta(days=len(values) - 1 - i): v for i, v in enumerate(values)}


def test_a_workout_run_counts_through_today_or_yesterday():
    assert workout_notes(_ago(0, 1, 2, 20), TODAY)[0] == "3 workout days in a row, through today. Keep it going."
    # No workout yet today: the run through yesterday still stands.
    assert workout_notes(_ago(1, 2, 20), TODAY)[0] == "2 workout days in a row, through yesterday. Keep it going."


def test_a_gap_is_a_gentle_restart_only_for_a_while():
    assert workout_notes(_ago(3, 20), TODAY)[0] == "Your last workout was Tuesday. One today starts a new run."
    assert workout_notes(_ago(10, 20), TODAY) == []  # long gaps aren't nagged about
    assert workout_notes({}, TODAY) == []


def test_the_week_against_the_one_before_and_the_best_so_far():
    most = workout_notes(_ago(0, 2, 4, 6, 9, 30), TODAY)
    assert "4 workout days in the last 7, your most in any 7 days since Oct 14." in most
    up = workout_notes(_ago(1, 3, 8, 9, 10, 11, 12, 30), TODAY)
    assert "2 workout days in the last 7" not in " ".join(up)  # fewer than the week before: no week note
    more = workout_notes(_ago(1, 3, 5, 8, 9, 15, 16, 17, 18, 30), TODAY)
    assert "3 workout days in the last 7, up from 2 the 7 days before." in more


def test_a_young_record_counts_since_the_start():
    assert workout_notes(_ago(0, 1, 5), TODAY)[-1] == "3 workout days since you started recording workouts on Nov 8."


def test_above_your_usual_needs_a_usual_and_a_run():
    values = _days([1000.0] * 20 + [3000.0] * 3, YESTERDAY)
    expected = "Steps above your usual (1,000) 3 days in a row, through yesterday."
    assert above_usual("steps", None, values, YESTERDAY) == expected
    assert above_usual("steps", None, _days([1000.0] * 20 + [3000.0] * 2, YESTERDAY), YESTERDAY) is None
    assert above_usual("steps", None, _days([1000.0] * 10 + [3000.0] * 3, YESTERDAY), YESTERDAY) is None  # no usual
    gap = _days([1000.0] * 20 + [3000.0] * 3, YESTERDAY - dt.timedelta(days=1))  # yesterday unknown (R7)
    assert above_usual("steps", None, gap, YESTERDAY) is None


def test_week_on_week_only_says_rises():
    values = _days([5.0] * 7 + [20.0] * 7, YESTERDAY)
    assert week_on_week("exercise", "min", values, YESTERDAY) == (
        "Exercise: 20 min a day over the last 7 days, up from 5 min the 7 days before."
    )
    assert week_on_week("exercise", "min", _days([20.0] * 7 + [5.0] * 7, YESTERDAY), YESTERDAY) is None
    assert week_on_week("exercise", "min", _days([5.0] * 7 + [20.0] * 4, YESTERDAY), YESTERDAY) is None


def test_momentum_puts_workouts_first_and_stays_short():
    rising = _days([5.0] * 7 + [20.0] * 7, YESTERDAY)
    series = {WORKOUT: _ago(0, 1, 2), **{f: rising for f in ACTIVITY}}
    notes = momentum(series, TODAY)
    assert notes[0].startswith("3 workout days in a row") and len(notes) == MAX_NOTES
