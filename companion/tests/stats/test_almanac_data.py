"""The almanac in the engine (R8, R17): calendar facts are tested like any other series. A planted moon effect on
sleep is found; the moon and holidays stay quiet against unrelated series. Seeded and synthetic (R4)."""

from __future__ import annotations

import datetime as dt
import math
import os

import numpy as np
from scipy.stats import binom

from app.almanac import almanac_features
from app.analysis.engine import FeatureMeta, analyse

SEEDS = range(int(os.environ.get("STATS_SEEDS", "20")))


def null_bound(n: int, target: float) -> float:
    """At full strength (100+ seeds) the target itself; on a quick run, its 95% binomial upper bound (seed noise)."""
    return target * n if n >= 100 else float(binom.ppf(0.95, n, target))


START = dt.date(2026, 7, 1)
DAYS = 180
TODAY = START + dt.timedelta(days=DAYS)
CALENDAR = almanac_features(START, TODAY - dt.timedelta(days=1), 40.7, "US")
META = {
    "almanac.moon": FeatureMeta("Moon (share lit)", "%", family="almanac"),
    "almanac.holiday": FeatureMeta("Public holiday", kind="count", family="almanac"),
    "almanac.days_to_holiday": FeatureMeta("Days until the next public holiday", "days", family="almanac"),
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


def test_a_moon_effect_on_sleep_is_found():
    moon = np.array([CALENDAR["almanac.moon"][START + dt.timedelta(days=i)] for i in range(DAYS)])
    found = 0
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        sleep = 7 + 0.5 * _ar1(rng, DAYS, 0.3) - 0.006 * (moon - 50)  # +-0.3 h from new to full moon
        values = {**_calendar(), "sleep.total_h": _series(sleep)}
        found += any(
            f.kind == "association" and {f.a, f.b} == {"almanac.moon", "sleep.total_h"}
            for f in analyse(values, META, TODAY)
        )
    assert found >= 0.8 * len(SEEDS)


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
        false += any(f.kind == "association" and "almanac." in f"{f.a} {f.b}" for f in analyse(values, META, TODAY))
    assert false <= null_bound(len(SEEDS), 0.15)
