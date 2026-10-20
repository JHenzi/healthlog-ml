"""Engine building blocks and wording (R10, R13)."""

from __future__ import annotations

import datetime as dt
import re

import numpy as np
import pandas as pd
import pytest

from app.analysis.engine import FeatureMeta, Finding
from app.analysis.pure import (
    as_daily,
    benjamini_hochberg,
    cliffs_delta,
    effective_n,
    lag1_autocorr,
    mean_shift_test,
    residualize,
    shift_days,
)
from app.analysis.sentences import happening, sentence

FORBIDDEN = re.compile(r"\b(cause[sd]?|causing|because|leads? to|due to|results? in|diagnos\w*)\b", re.IGNORECASE)


def test_benjamini_hochberg_matches_the_textbook_example():
    p = [0.01, 0.04, 0.03, 0.005]
    assert benjamini_hochberg(p) == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert benjamini_hochberg([]) == []


def test_effective_n_shrinks_with_shared_autocorrelation():
    none = np.zeros(10)
    ar = 0.5 ** np.arange(1, 11)
    assert effective_n(100, none, ar) == 100
    assert effective_n(100, ar, ar) == pytest.approx(100 / (1 + 2 * float(np.dot(ar, ar))))
    assert effective_n(10, np.full(10, 0.99), np.full(10, 0.99)) >= 3


def test_mean_shift_test_is_stricter_on_autocorrelated_data():
    recent, base = np.array([2.0, 2.5, 3.0, 2.2, 2.8, 2.6, 2.4]), np.linspace(0, 1, 28)
    assert mean_shift_test(recent, base, 0.0) < mean_shift_test(recent, base, 0.7)
    assert mean_shift_test(np.ones(7), np.ones(28), 0.3) == 1.0


def test_cliffs_delta_extremes():
    assert cliffs_delta(np.array([3, 4]), np.array([1, 2])) == 1.0
    assert cliffs_delta(np.array([1, 2]), np.array([1, 2])) == 0.0


def test_residualize_removes_the_weekday_profile():
    start = dt.date(2026, 6, 1)
    values = {
        start + dt.timedelta(days=i): 10.0 + (5.0 if (start + dt.timedelta(days=i)).weekday() >= 5 else 0.0)
        for i in range(70)
    }
    resid = residualize(as_daily(values))
    assert resid.abs().max() < 1e-9


def test_lag1_autocorr_uses_consecutive_days_only():
    s = as_daily({dt.date(2026, 6, 1) + dt.timedelta(days=i): float(i) for i in range(30)})
    assert lag1_autocorr(s) == pytest.approx(1.0)
    gappy = s.iloc[::2]  # no consecutive days left
    assert lag1_autocorr(gappy) == 0.0


def test_shift_days_moves_values_forward():
    s = pd.Series([1.0], index=pd.to_datetime(["2026-06-01"]))
    assert shift_days(s, 1).index[0] == pd.Timestamp("2026-06-02")


META = {
    "hl.step_count": FeatureMeta("Steps", "count", family="activity"),
    "sleep.total_h": FeatureMeta("Sleep (total)", "h", family="sleep"),
    "mood.label.anxious": FeatureMeta("Feeling: anxious", None, "count", family="mood"),
    "mood.assoc.work": FeatureMeta("Mood about: work", None, "count", family="mood"),
}


def _findings() -> list[Finding]:
    mw = {"median_with": 6.2, "median_without": 6.9}
    return [
        Finding(
            "association", "day", "hl.step_count", "sleep.total_h", 0, "spearman", 0.42, 0.001, 64, strength="moderate"
        ),
        Finding(
            "association", "day", "hl.step_count", "sleep.total_h", 1, "spearman", -0.31, 0.01, 63, strength="moderate"
        ),
        Finding(
            "association",
            "day",
            "mood.label.anxious",
            "sleep.total_h",
            0,
            "mann_whitney",
            -0.4,
            0.01,
            75,
            14,
            61,
            strength="moderate",
            details={**mw, "flag_side": "a"},
        ),
        Finding(
            "association",
            "day",
            "mood.label.anxious",
            "sleep.total_h",
            1,
            "mann_whitney",
            -0.4,
            0.01,
            75,
            14,
            61,
            strength="moderate",
            details={**mw, "flag_side": "a"},
        ),
        Finding(
            "association",
            "day",
            "sleep.total_h",
            "mood.label.anxious",
            0,
            "mann_whitney",
            -0.4,
            0.01,
            75,
            14,
            61,
            strength="moderate",
            details={**mw, "flag_side": "b"},
        ),
        Finding(
            "association",
            "day",
            "sleep.total_h",
            "mood.label.anxious",
            1,
            "mann_whitney",
            -0.4,
            0.01,
            75,
            14,
            61,
            strength="moderate",
            details={**mw, "flag_side": "b"},
        ),
        Finding(
            "association",
            "day",
            "mood.label.anxious",
            "mood.assoc.work",
            1,
            "fisher",
            0.3,
            0.01,
            80,
            14,
            66,
            strength="moderate",
            details={"rate_with": 0.31, "rate_without": 0.11},
        ),
        Finding(
            "change",
            "week",
            "hl.step_count",
            None,
            None,
            "mean_shift",
            0.6,
            0.001,
            35,
            7,
            28,
            strength="strong",
            details={"recent_mean": 9000, "base_mean": 7000, "pct": 28.6, "recent_days": 7, "base_days": 28},
        ),
        Finding(
            "association",
            "days",
            "hl.step_count",
            "sleep.total_h",
            3,
            "distributed_lag",
            0.4,
            0.001,
            80,
            strength="moderate",
            details={"curve": [0, 0.1, 0.3, 0.4, 0.3, 0.1, 0, 0], "peak": 3},
        ),
        Finding(
            "weekday",
            "week",
            "sleep.total_h",
            None,
            None,
            "kruskal",
            0.12,
            0.001,
            95,
            strength="moderate",
            details={"means": {str(k): 7.0 + k / 10 for k in range(7)}, "high": 6, "low": 0},
        ),
    ]


def test_sentences_read_naturally():
    lines = [sentence(f, META) for f in _findings()]
    assert lines[0] == "Days with higher steps tend to have higher sleep (total) (64 days, moderate)."
    assert lines[1] == "Higher steps tends to be followed by lower sleep (total) the next day (63 days, moderate)."
    assert lines[2] == (
        "On days you logged feeling anxious, sleep (total) tended to be lower: median 6 h 12 min vs 6 h 54 min "
        "(14 vs 61 days, moderate)."
    )
    assert lines[3].startswith("The day after you logged feeling anxious, sleep (total)")
    assert lines[5].startswith("The day before you logged feeling anxious, sleep (total)")
    assert lines[6].startswith("When you logged feeling anxious, you logged a mood about work the next day on 31%")
    assert (
        lines[7] == "Steps over the last 7 days averaged 9,000 count, 29% above the 28 days before "
        "(7,000 count; 7 vs 28 days, strong)."
    )
    assert lines[8] == (
        "Higher steps tends to be followed by higher sleep (total) over the next days, most around 3 days later "
        "(80 days, moderate)."
    )
    assert lines[9].startswith("Sleep (total) is highest on Sundays (7 h 36 min) and lowest on Mondays (7 h 00 min)")


def test_every_sentence_has_evidence_and_association_wording_only():
    for f in _findings():
        line = sentence(f, META)
        assert not FORBIDDEN.search(line), line
        assert re.search(r"\(\d+ (vs \d+ )?days, (weak|moderate|strong)\)\.$|; \d+ vs \d+ days, \w+\)\.$", line), line


def test_calendar_events_read_as_events():
    meta = FeatureMeta("Public holiday", kind="count", family="almanac")
    for feature in ("almanac.holiday", "almanac.holiday_runup"):
        event = happening(feature, meta)
        assert event.startswith("it was") and "logged" not in event
