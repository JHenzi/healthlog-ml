"""Daily feature assembly (pure): source policy (R16), aggregation, bounds, missing-not-zero (R7)."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from app.features import MetricRule, assemble, metric_features, pick_metric_value, sleep_features
from app.metrics_view import sparkline, summarize, window
from app.upstream import MetricDayRow, SleepDayRow, SourceDay

D = dt.date(2026, 10, 16)
NY = ZoneInfo("America/New_York")


def _row(source: str, n: int = 10, *, s=100.0, a=10.0, lo=1.0, hi=20.0, metric="m", day=D) -> MetricDayRow:
    return MetricDayRow(day, metric, source, s, a, lo, hi, n)


def test_merged_stream_wins_by_default():
    assert pick_metric_value([_row("Watch", 900, s=9.0), _row("", 5, s=5.0)], MetricRule("sum")) == 5.0


def test_busiest_source_without_merged_stream_and_never_a_sum_across_sources():
    rows = [_row("Watch", 900, s=9.0), _row("iPhone", 10, s=4.0)]
    assert pick_metric_value(rows, MetricRule("sum")) == 9.0


def test_explicit_priority_beats_the_default():
    rows = [_row("", 5, a=1.0), _row("iPhone", 10, a=2.0), _row("Watch", 900, a=3.0)]
    assert pick_metric_value(rows, MetricRule("avg", source_priority=("Ring", "iPhone"))) == 2.0


def test_aggregation_choice():
    rows = [_row("")]
    assert [pick_metric_value(rows, MetricRule(a)) for a in ("sum", "avg", "min", "max")] == [100.0, 10.0, 1.0, 20.0]


def test_bounds_make_a_day_missing_not_clipped():
    rows = [_row("", a=250.0)]
    assert pick_metric_value(rows, MetricRule("avg", max_value=220)) is None
    assert pick_metric_value(rows, MetricRule("avg", min_value=300)) is None
    assert pick_metric_value(rows, MetricRule("avg", min_value=30, max_value=300)) == 250.0


def test_metric_features_name_and_label():
    fs = metric_features([_row("", metric="step_count")], {"step_count": MetricRule("sum", display_name="Steps")})
    assert fs.values == {"hl.step_count": {D: 100.0}}
    assert fs.defs["hl.step_count"].label == "Steps" and fs.defs["hl.step_count"].source == "healthlog"


def test_sleep_takes_the_fullest_source_per_night():
    rows = [SleepDayRow(D, "iPhone", 5.0, None, None, None, None, 1), SleepDayRow(D, "Watch", 7.0, 1.0, 4, 2, 0.5, 1)]
    fs = sleep_features(rows)
    assert fs.values["sleep.total_h"] == {D: 7.0}
    assert fs.values["sleep.deep_h"] == {D: 1.0}


def test_assemble_covers_every_source():
    fs = assemble(
        [_row("", metric="step_count")],
        {"step_count": MetricRule("sum")},
        [SleepDayRow(D, "Watch", 7.0, 1.0, 4.0, 1.5, 0.5, 1)],
        [SourceDay(D, "", 30.0, 600)],
        {D: (20, 80)},
        [SourceDay(D, "Watch", 45.0, 1)],
        [],
        NY,
        dt.time(4, 0),
    )
    assert {"hl.step_count", "sleep.total_h", "stress.mean", "energy.low", "energy.high", "workout.minutes"} <= set(
        fs.defs
    )
    assert not any(f.startswith("mood.") for f in fs.defs)  # no entries -> no mood features at all


def test_window_and_summary():
    today = dt.date(2026, 10, 17)
    values = {today - dt.timedelta(days=i): (10.0 if i <= 30 else 5.0) for i in range(1, 61)}
    assert window(values, today - dt.timedelta(days=1)).n == 30
    s = summarize(values, today)
    assert s.recent.mean == 10.0 and s.prior.mean == 5.0 and round(s.change_pct) == 100
    assert all(w is not None for w in s.weekday)
    assert summarize({}, today).days == 0


def test_window_needs_minimum_days():
    assert window({D: 1.0}, D) is None


def test_sparkline_keeps_gaps():
    values = {D - dt.timedelta(days=i): float(i) for i in (0, 1, 2, 10, 11)}
    assert len(sparkline(values, D, days=20).split("|")) == 2
    assert sparkline({D: 1.0}, D) == ""


def test_coverage_marks_unrecorded_days():
    from app.metrics_view import coverage

    end = dt.date(2026, 10, 16)
    cells = coverage({end, end - dt.timedelta(days=2)}, end, days=4)
    assert cells == [
        (dt.date(2026, 10, 13), False),
        (dt.date(2026, 10, 14), True),
        (dt.date(2026, 10, 15), False),
        (dt.date(2026, 10, 16), True),
    ]


def test_whole_numbers_print_without_decimals():
    from app.metrics_view import fmt

    assert fmt(3.0, "cups") == "3 cups"
    assert fmt(2.5) == "2.50"
    assert fmt(12.25) == "12.2"
    assert fmt(None) == "–"
