"""Distributed lags (R8): a link spread over days 2–4 is found, with its peak; autocorrelated noise stays quiet,
both for the single curve test and for the whole engine; a same-day link is left to the day-level tests."""

from __future__ import annotations

import datetime as dt
import math
import os

import numpy as np

from app.analysis import constants as C
from app.analysis.engine import FeatureMeta, analyse
from app.analysis.pure import as_daily, distributed_lag

SEEDS = range(int(os.environ.get("STATS_SEEDS", "20")))
START = dt.date(2026, 6, 1)
DAYS = 100
TODAY = START + dt.timedelta(days=DAYS)
META = {"sleep.total_h": FeatureMeta("Sleep", family="sleep"), "y": FeatureMeta("y", family="fam_y")}
for k in range(6):
    META[f"o{k}"] = FeatureMeta(f"o{k}", family=f"fam_o{k}")


def _ar1(rng: np.random.Generator, n: int, phi: float) -> np.ndarray:
    out = np.empty(n)
    out[0] = rng.normal()
    for i in range(1, n):
        out[i] = phi * out[i - 1] + rng.normal() * math.sqrt(1 - phi * phi)
    return out


def _series(arr: np.ndarray) -> dict[dt.date, float]:
    return {START + dt.timedelta(days=i): float(v) for i, v in enumerate(arr)}


def _spread(rng, x: np.ndarray, weights=(0, 0, 0.35, 0.5, 0.35, 0, 0, 0)) -> np.ndarray:
    y = 0.8 * _ar1(rng, DAYS, 0.3)
    for k, w in enumerate(weights):
        y[k:] += w * x[: DAYS - k]
    return y


def test_a_link_spread_over_days_is_found_with_its_peak():
    def check(seed: int) -> bool:
        rng = np.random.default_rng(50_000 + seed)
        x = _ar1(rng, DAYS, 0.3)
        values = {"sleep.total_h": _series(x), "y": _series(_spread(rng, x))}
        found = analyse(values, META, TODAY)
        hits = [f for f in found if f.method == "distributed_lag" and (f.a, f.b) == ("sleep.total_h", "y")]
        return bool(hits) and 2 <= hits[0].details["peak"] <= 4 and hits[0].effect > 0

    assert np.mean([check(s) for s in SEEDS]) >= 0.8


def _size(make) -> float:
    """Share of 400 null datasets where the curve test alone says p < .05 (target 5%; Monte Carlo SE ~1.1%)."""
    hits = []
    for seed in range(400):
        x, y = make(np.random.default_rng(60_000 + seed))
        res = distributed_lag(as_daily(_series(x)), as_daily(_series(y)), C.DLM_MAX_LAG, C.DLM_DEGREE, C.DLM_MIN_DAYS)
        hits.append(res.p < 0.05)
    return float(np.mean(hits))


def test_the_curve_test_is_calibrated_on_independent_and_autocorrelated_noise():
    # Measured 4.5% and 4.8%. The residual-based version measured 8.5% and 11%; at phi 0.9 this one is 8%.
    assert _size(lambda rng: (_ar1(rng, DAYS, 0.0), _ar1(rng, DAYS, 0.0))) <= 0.07
    assert _size(lambda rng: (_ar1(rng, DAYS, 0.6), _ar1(rng, DAYS, 0.6))) <= 0.07


def test_the_curve_test_ignores_a_shared_trend_or_weekday_pattern():
    trend = np.linspace(0, 3, DAYS)
    pattern = np.array([0.0, 0.2, 0.1, 0.3, 1.0, 2.5, 2.0])
    week = np.array([pattern[(START + dt.timedelta(days=i)).weekday()] for i in range(DAYS)])
    assert _size(lambda rng: (trend + _ar1(rng, DAYS, 0.3), trend + _ar1(rng, DAYS, 0.3))) <= 0.08
    assert _size(lambda rng: (week + 0.5 * _ar1(rng, DAYS, 0.3), week + 0.5 * _ar1(rng, DAYS, 0.3))) <= 0.08


def test_noise_reports_no_spread_links():
    def check(seed: int) -> bool:
        rng = np.random.default_rng(70_000 + seed)
        values = {"sleep.total_h": _series(_ar1(rng, DAYS, 0.5))}
        values |= {f"o{k}": _series(_ar1(rng, DAYS, 0.5)) for k in range(6)}
        return any(f.method == "distributed_lag" for f in analyse(values, META, TODAY))

    assert np.mean([check(s) for s in SEEDS]) <= 0.15


def test_a_same_day_link_is_not_reported_as_spread():
    def check(seed: int) -> bool:
        rng = np.random.default_rng(80_000 + seed)
        x = _ar1(rng, DAYS, 0.3)
        values = {"sleep.total_h": _series(x), "y": _series(_spread(rng, x, weights=(0.7,)))}
        return any(f.method == "distributed_lag" for f in analyse(values, META, TODAY))

    assert np.mean([check(s) for s in SEEDS]) <= 0.1
