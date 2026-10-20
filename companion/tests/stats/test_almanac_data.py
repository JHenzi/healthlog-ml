"""The almanac in the engine (R8): calendar facts are outside data. A planted run-up effect (stress higher in the
two weeks before Thanksgiving and Christmas) is found; the moon and holidays stay quiet against unrelated
series; calendar features are never an outcome, a change or a rhythm. Seeded and synthetic (R4)."""

from __future__ import annotations

import datetime as dt
import math
import os

import numpy as np

from app.almanac import almanac_features
from app.analysis.engine import FeatureMeta, analyse

SEEDS = range(int(os.environ.get("STATS_SEEDS", "20")))
START = dt.date(2026, 7, 1)
DAYS = 180
TODAY = START + dt.timedelta(days=DAYS)
CALENDAR = almanac_features(START, TODAY - dt.timedelta(days=1), 40.7, "US")
META = {
    "almanac.moon": FeatureMeta("Moon (share lit)", "%", family="almanac"),
    "almanac.holiday": FeatureMeta("Public holiday", kind="count", family="almanac"),
    "almanac.holiday_runup": FeatureMeta("Two weeks before a big holiday", kind="count", family="almanac"),
    "stress.mean": FeatureMeta("Stress", family="vital"),
    "sleep.total_h": FeatureMeta("Sleep", "h", family="sleep"),
    "hl.headache": FeatureMeta("Headache", kind="count", family="symptom"),
}


def _series(arr: np.ndarray) -> dict[dt.date, float]:
    return {START + dt.timedelta(days=i): float(v) for i, v in enumerate(arr)}


def _ar1(rng: np.random.Generator, n: int, phi: float) -> np.ndarray:
    out = np.empty(n)
    out[0] = rng.normal()
    for i in range(1, n):
        out[i] = phi * out[i - 1] + rng.normal() * math.sqrt(1 - phi * phi)
    return out


def _calendar() -> dict[str, dict[dt.date, float]]:
    return {f: v for f, v in CALENDAR.items() if f in META}


def test_a_run_up_effect_is_found():
    runup = np.array([CALENDAR["almanac.holiday_runup"][START + dt.timedelta(days=i)] for i in range(DAYS)])
    found = 0
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        stress = 30 + 3 * _ar1(rng, DAYS, 0.4) + 5 * runup  # 1.7 SD; measured 92.5% at 200 seeds (1.3 SD: 77%)
        values = {**_calendar(), "stress.mean": _series(stress)}
        found += any(
            f.kind == "association" and f.a == "almanac.holiday_runup" and f.b == "stress.mean" and f.effect > 0
            for f in analyse(values, META, TODAY)
        )
    assert found >= 0.8 * len(SEEDS)


def test_the_calendar_is_never_an_outcome_or_a_change_or_a_rhythm():
    for seed in SEEDS:
        rng = np.random.default_rng(500 + seed)
        values = {
            **_calendar(),
            "stress.mean": _series(30 + 3 * _ar1(rng, DAYS, 0.4)),
            "hl.headache": _series((rng.random(DAYS) < 0.3).astype(float)),
        }
        for f in analyse(values, META, TODAY):
            if f.kind != "association":
                assert not f.a.startswith("almanac."), f
            if f.b and f.b.startswith("almanac."):
                assert f.lag == 0 and not f.a.startswith("almanac."), f


def test_the_moon_and_holidays_stay_quiet_against_unrelated_series():
    false = 0
    for seed in SEEDS:
        rng = np.random.default_rng(2000 + seed)
        values = {
            **_calendar(),
            "sleep.total_h": _series(7 + 0.5 * _ar1(rng, DAYS, 0.5)),
            "stress.mean": _series(30 + 3 * _ar1(rng, DAYS, 0.4)),
            "hl.headache": _series((rng.random(DAYS) < 0.3).astype(float)),
        }
        false += any(f.kind == "association" and f.a.startswith("almanac.") for f in analyse(values, META, TODAY))
    assert false <= max(2, 0.15 * len(SEEDS))
