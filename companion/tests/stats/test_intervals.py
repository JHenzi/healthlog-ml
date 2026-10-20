"""Coverage of the likely ranges shown with findings (R8, design 1b/1c).

A 95% range must contain the planted effect in about 95% of datasets, also on
autocorrelated data, where a naive range would be far too narrow. Pure and
cheap, so every check runs 400 seeded datasets regardless of ``STATS_SEEDS``.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
from scipy import stats

from app.analysis.engine import FeatureMeta, _prepare
from app.analysis.pure import (
    acf,
    as_daily,
    delta_interval,
    mann_whitney_eff,
    mean_shift,
    residualize,
    rho_interval,
    spearman_eff,
)

SEEDS = range(400)
START = dt.date(2026, 6, 1)
DAYS = 100


def _ar1(rng: np.random.Generator, n: int, phi: float) -> np.ndarray:
    out = np.empty(n)
    out[0] = rng.normal()
    for i in range(1, n):
        out[i] = phi * out[i - 1] + rng.normal() * math.sqrt(1 - phi * phi)
    return out


def _series(arr: np.ndarray) -> dict[dt.date, float]:
    return {START + dt.timedelta(days=i): float(v) for i, v in enumerate(arr)}


def _coverage(check) -> float:
    return float(np.mean([check(seed) for seed in SEEDS]))


def _rho_coverage(phi: float, r: float) -> float:
    truth = 6 / math.pi * math.asin(r / 2)  # Spearman's rho of a bivariate normal with Pearson r
    meta = FeatureMeta("x")

    def check(seed: int) -> bool:
        rng = np.random.default_rng(10_000 + seed)
        x = _ar1(rng, DAYS, phi)
        y = r * x + math.sqrt(1 - r * r) * _ar1(rng, DAYS, phi)
        px, py = _prepare(_series(x), meta), _prepare(_series(y), meta)
        corr = spearman_eff(px.resid, py.resid, px.acf, py.acf)
        lo, hi = rho_interval(corr.rho, corr.n_eff)
        return lo <= truth <= hi

    return _coverage(check)


def test_rho_range_covers_the_planted_correlation():
    assert 0.9 <= _rho_coverage(0.0, 0.5) <= 0.99


def test_rho_range_stays_honest_on_autocorrelated_days():
    # Without the effective n this drops well below 90%.
    assert 0.88 <= _rho_coverage(0.6, 0.5) <= 0.99


def test_delta_range_covers_the_planted_yes_no_effect():
    shift = 0.8
    truth = 2 * stats.norm.cdf(shift / math.sqrt(2)) - 1  # Cliff's delta of N(shift, 1) vs N(0, 1)

    def check(seed: int) -> bool:
        rng = np.random.default_rng(20_000 + seed)
        flag = rng.random(DAYS) < 0.3
        y = _ar1(rng, DAYS, 0.4) + shift * flag
        resid = residualize(as_daily(_series(y)))
        yes = as_daily(_series(flag.astype(float))).reindex(resid.index).to_numpy() > 0
        with_, without = resid.to_numpy()[yes], resid.to_numpy()[~yes]
        g = mann_whitney_eff(with_, without, acf(resid), np.zeros(10))
        lo, hi = delta_interval(g.delta, g.n_with, g.n_without, g.n_eff)
        return lo <= truth <= hi

    assert _coverage(check) >= 0.88


def test_change_range_covers_the_planted_shift():
    def check(seed: int) -> bool:
        rng = np.random.default_rng(30_000 + seed)
        y = 10 + _ar1(rng, 35, 0.5)
        y[-7:] += 1.0
        lo, hi = mean_shift(y[-7:], y[:28], _lag1(y[:28])).interval()
        return lo <= 1.0 <= hi

    assert _coverage(check) >= 0.88


def _lag1(y: np.ndarray) -> float:
    return float(np.corrcoef(y[:-1], y[1:])[0, 1])
