"""My Metrics tiles: colour bands and the glance over a series (pure)."""

from __future__ import annotations

import datetime as dt

from app import metrics_view

TODAY = dt.date(2026, 11, 4)


def test_bands_split_ranks_into_fifths():
    assert [metrics_view.band(r) for r in (None, 0, 19.9, 20, 50, 80, 100)] == [None, 0, 0, 1, 2, 4, 4]


def test_glance_ranks_the_latest_day_and_keeps_gaps():
    values = {TODAY - dt.timedelta(days=i): float(100 - i) for i in range(1, 41) if i != 5}
    g = metrics_view.glance(values, metrics_view.summarize(values, TODAY), TODAY)
    assert g.latest_rank is not None and metrics_view.band(g.latest_rank) == 4  # yesterday is the highest day
    assert len(g.spark) == 2 and g.dot is not None  # the missing day splits the line
    assert len(g.cells) == metrics_view.WINDOW_DAYS and g.cells[-1][0] == TODAY - dt.timedelta(days=1)
    missing = [c for c in g.cells if c[0] == TODAY - dt.timedelta(days=5)][0]
    assert missing[1] is None and missing[2] is None  # missing is no data, never a colour


def test_too_few_days_get_no_colour():
    values = {TODAY - dt.timedelta(days=i): 1.0 for i in range(1, 10)}
    g = metrics_view.glance(values, metrics_view.summarize(values, TODAY), TODAY)
    assert g.latest_rank is None and all(c[2] is None for c in g.cells)


def test_mood_bars_colour_by_side_and_keep_gaps():
    mean = {TODAY - dt.timedelta(days=1): 0.8, TODAY - dt.timedelta(days=2): -0.9}
    low = {TODAY - dt.timedelta(days=1): -0.2}
    bars = metrics_view.mood_bars(mean, low, TODAY)
    assert len(bars) == metrics_view.WINDOW_DAYS
    assert (bars[-1].band, bars[-1].low) == (4, -0.2)  # pleasant: moss, with its lowest moment
    assert bars[-2].band == 0  # unpleasant: clay
    assert bars[0].mean is None and bars[0].band is None  # nothing logged is no bar, not neutral


def test_fluid_chart_stacks_water_and_coffee_puts_alcohol_below_and_keeps_missing_missing():
    today = dt.date(2026, 11, 4)
    d1, d2, d3 = (today - dt.timedelta(days=n) for n in (3, 2, 1))
    c = metrics_view.fluid_chart({d1: 500.0, d2: 300.0}, {d1: 142.0}, {d2: -308.0}, today)
    by_day = {d.day: d for d in c.days}
    assert len(c.days) == 30 and c.days[-1].day == d3
    assert by_day[d1].net == 642.0 and by_day[d2].net == -8.0
    assert by_day[d3].net is None  # nothing recorded is not zero (R7)
    assert c.top == 642.0 and c.bottom == 308.0


def test_fluid_chart_is_none_without_data():
    assert metrics_view.fluid_chart({}, {}, {}, dt.date(2026, 11, 4)) is None
