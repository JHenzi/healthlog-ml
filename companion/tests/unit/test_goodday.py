"""The good-day score: ranked against your own history, equal parts, missing never zero (R7, R13, R17)."""

from __future__ import annotations

import datetime as dt

import pytest

from app import goodday
from app.goodday import MIN_COMPONENT_DAYS, MIN_SCORED_DAYS, best_days, built_from, percentiles, scores
from app.models import FeatureDef, Insight

TODAY = dt.date(2026, 10, 20)


def _days(values: list[float], last: dt.date = TODAY - dt.timedelta(days=1)) -> dict[dt.date, float]:
    return {last - dt.timedelta(days=len(values) - 1 - i): v for i, v in enumerate(values)}


def test_percentiles_rank_within_the_history_and_ties_share_a_rank():
    ranks = percentiles(_days([1.0, 2.0, 2.0, 3.0]))
    assert sorted(ranks.values()) == [12.5, 50.0, 50.0, 87.5]


def test_a_day_needs_two_parts_and_each_part_two_weeks_of_history():
    n = MIN_COMPONENT_DAYS
    steps = _days([float(i) for i in range(n)])
    sleep = _days([7.0 + i / 10 for i in range(n)])
    assert scores({"hl.step_count": steps}) == {}  # one part alone is not a day's score
    assert scores({"hl.step_count": steps, "sleep.total_h": dict(list(sleep.items())[1:])}) == {}  # 13 nights
    both = scores({"hl.step_count": steps, "sleep.total_h": sleep})
    assert len(both) == n
    top = both[TODAY - dt.timedelta(days=1)]
    assert set(top.parts) == {"active", "sleep"} and top.score == pytest.approx(100 - 50 / n)


def test_a_missing_part_is_left_out_not_counted_as_zero():
    n = MIN_COMPONENT_DAYS
    series = {
        "hl.step_count": _days([float(i) for i in range(n)]),
        "sleep.total_h": _days([float(i) for i in range(n)]),
        "mood.valence_mean": _days([float(i) for i in range(n)], TODAY - dt.timedelta(days=2)),  # not yesterday
    }
    last = scores(series)[TODAY - dt.timedelta(days=1)]
    assert "mood" not in last.parts and last.score == pytest.approx(last.parts["active"])


def test_active_is_the_mean_of_its_components():
    n = MIN_COMPONENT_DAYS
    up = [float(i) for i in range(n)]
    series = {"hl.step_count": _days(up), "hl.apple_exercise_time": _days(up[::-1]), "sleep.total_h": _days(up)}
    assert scores(series)[TODAY - dt.timedelta(days=1)].parts["active"] == pytest.approx(50.0)


def test_best_days_are_the_top_quarter_once_there_are_enough():
    n = MIN_SCORED_DAYS
    series = {"hl.step_count": _days([float(i) for i in range(20)]), "sleep.total_h": _days([5.0] * 20)}
    threshold, best = best_days(scores(series))
    assert len(best) == 5 and min(best) == TODAY - dt.timedelta(days=5) and threshold is not None
    few = {d: s for d, s in list(scores(series).items())[: n - 1]}
    assert best_days(few) == (None, set())


def test_the_score_is_linked_by_definition_to_the_families_it_is_built_from():
    families = {"hl.step_count": "activity", "sleep.total_h": "sleep", "hrv": "vital"}
    assert built_from(families) == ("activity", "sleep")


def test_the_view_shows_parts_best_days_and_what_they_have_in_common():
    n = 20
    up = [float(i) for i in range(n)]
    series = {"hl.step_count": _days(up), "sleep.total_h": _days(up), "hl.hrv": _days([v * 2 for v in up])}
    defs = {"hl.hrv": FeatureDef(feature="hl.hrv", label="HRV", unit="ms", source="healthlog", kind="continuous")}
    insight = Insight(id=1, kind="association", feature_a=goodday.FEATURE, feature_b="hl.hrv", lag=0, n=n)
    v = goodday.view(series, defs, [insight], TODAY)
    assert v.yesterday.score == pytest.approx(97.5) and v.yesterday.best and v.rank == 95
    assert [p.label for p in v.yesterday.parts] == ["Active", "Sleep", "Water", "Mood"]
    assert v.yesterday.parts[2].value is None  # no water: shown as no data
    assert v.present == ("Active", "Sleep") and v.scored == n and len(v.recent) == goodday.RECENT_DAYS
    (c,) = v.common
    assert (c.label, c.n_best, c.n_rest) == ("HRV", 5, 15)
    assert c.best == pytest.approx(34.0) and c.rest == pytest.approx(14.0)
