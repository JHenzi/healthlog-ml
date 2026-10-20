"""Streaks and records (descriptive notes): what counts, what's unknown, and the wording (R7, R10, R13)."""

from __future__ import annotations

import datetime as dt

from app.highlights import RECORD_MIN_DAYS, Def, fmt_value, highlights, record, season, streak

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


STRESS = Def("Stress (mean of measured minutes)", None, "stress", "continuous")
SLEEP_H = Def("Sleep (total)", "h", "sleep", "continuous")
CHRISTMAS = {dt.date(2026, 12, 25): "Christmas"}


def _season_series(base: float, runup: float) -> dict[str, dict[dt.date, float]]:
    start = dt.date(2026, 12, 11)  # 14 days before Christmas
    stress = {start - dt.timedelta(days=k): base for k in range(1, 29)}
    stress |= {start + dt.timedelta(days=k): runup for k in range(14)}
    sleep = {d: 7.0 for d in stress}
    return {"stress.mean": stress, "sleep.total_h": sleep}


def test_season_compares_the_run_up_with_the_four_weeks_before():
    series, defs = _season_series(30.0, 40.0), {"stress.mean": STRESS, "sleep.total_h": SLEEP_H}
    note = season(series, defs, CHRISTMAS, dt.date(2026, 12, 21))
    assert (
        note.text
        == "Leading up to Christmas (the last 10 days): stress averaged 40, up from 30 in the four weeks before."
    )
    after = season(series, defs, CHRISTMAS, dt.date(2026, 12, 28))
    assert after.text == "In the two weeks before Christmas: stress averaged 40, up from 30 in the four weeks before."
    assert "because" not in note.text and "caused" not in note.text  # R10
    notes = highlights(series, defs, dt.date(2026, 12, 21), CHRISTMAS)
    assert notes[0].kind == "season"


def test_season_stays_quiet_when_too_early_too_late_too_small_or_too_sparse():
    defs = {"stress.mean": STRESS, "sleep.total_h": SLEEP_H}
    series = _season_series(30.0, 40.0)
    assert season(series, defs, CHRISTMAS, dt.date(2026, 12, 16)) is None  # 5 days in
    assert season(series, defs, CHRISTMAS, dt.date(2027, 1, 5)) is None  # long past
    assert season(_season_series(30.0, 32.0), defs, CHRISTMAS, dt.date(2026, 12, 21)) is None  # under 10%
    sparse = {k: {d: v for d, v in vals.items() if d.day % 3 == 0} for k, vals in series.items()}
    assert season(sparse, defs, CHRISTMAS, dt.date(2026, 12, 21)) is None  # most days unknown (R7)
    assert highlights(series, defs, dt.date(2026, 12, 21)) == []  # no country, no holidays
