"""Validation suite for the insight engine (R8, risks.md C1-C4).

The engine must find planted effects (same day, next day, yes/no, weekly
change), stay within its false-discovery target on pure autocorrelated noise,
and stay quiet on pairs that only share a weekday pattern or a trend.
Seeded and synthetic (R4). ``STATS_SEEDS`` (default 20) sets how many datasets
each check uses; the nightly job raises it.
"""

from __future__ import annotations

import datetime as dt
import os

import numpy as np
import pytest

from app.analysis.engine import FeatureMeta, analyse

SEEDS = range(int(os.environ.get("STATS_SEEDS", "20")))
START = dt.date(2026, 6, 1)
DAYS = 100
TODAY = START + dt.timedelta(days=DAYS)


def _ar1(rng: np.random.Generator, n: int, phi: float) -> np.ndarray:
    out = np.empty(n)
    out[0] = rng.normal()
    for i in range(1, n):
        out[i] = phi * out[i - 1] + rng.normal() * np.sqrt(1 - phi * phi)
    return out


def _series(arr: np.ndarray) -> dict[dt.date, float]:
    return {START + dt.timedelta(days=i): float(v) for i, v in enumerate(arr) if not np.isnan(v)}


def _meta(names: list[str], kinds: dict[str, str] | None = None) -> dict[str, FeatureMeta]:
    kinds = kinds or {}
    return {n: FeatureMeta(n, None, kinds.get(n, "continuous"), family=f"fam_{n}") for n in names}


def _related(findings, a: str, b: str, lag: int | None = None, direction: bool = False) -> bool:
    for f in findings:
        if f.kind != "association":
            continue
        if direction and (f.a, f.b) != (a, b):
            continue
        if not direction and {f.a, f.b} != {a, b}:
            continue
        if lag is not None and f.lag != lag:
            continue
        return True
    return False


def _rate(check) -> float:
    return float(np.mean([check(seed) for seed in SEEDS]))


def test_planted_same_day_effect_is_found():
    def check(seed: int) -> bool:
        rng = np.random.default_rng(seed)
        x = _ar1(rng, DAYS, 0.3)
        y = 0.6 * x + 0.8 * _ar1(rng, DAYS, 0.3)
        found = analyse({"x": _series(x), "y": _series(y)}, _meta(["x", "y"]), TODAY)
        return _related(found, "x", "y", lag=0)

    assert _rate(check) >= 0.9


def test_planted_next_day_effect_is_found_with_its_direction():
    def check(seed: int) -> bool:
        rng = np.random.default_rng(1000 + seed)
        x = rng.normal(size=DAYS)
        y = np.empty(DAYS)
        y[0] = rng.normal()
        y[1:] = 0.7 * x[:-1] + 0.7 * rng.normal(size=DAYS - 1)
        found = analyse({"x": _series(x), "y": _series(y)}, _meta(["x", "y"]), TODAY)
        return _related(found, "x", "y", lag=1, direction=True)

    assert _rate(check) >= 0.9


def test_planted_yes_no_effect_is_found():
    def check(seed: int) -> bool:
        rng = np.random.default_rng(2000 + seed)
        flag = (rng.random(DAYS) < 0.3).astype(float)
        y = rng.normal(size=DAYS) + 1.0 * flag
        found = analyse({"flag": _series(flag), "y": _series(y)}, _meta(["flag", "y"], {"flag": "count"}), TODAY)
        return any(f.method == "mann_whitney" and {f.a, f.b} == {"flag", "y"} and f.lag == 0 for f in found)

    assert _rate(check) >= 0.8


def test_shared_weekday_pattern_is_not_a_relationship():
    pattern = np.array([0.0, 0.2, 0.1, 0.3, 1.0, 2.5, 2.0])

    def check(seed: int) -> bool:
        rng = np.random.default_rng(3000 + seed)
        weekday = np.array([pattern[(START + dt.timedelta(days=i)).weekday()] for i in range(DAYS)])
        x = weekday + 0.5 * rng.normal(size=DAYS)
        y = weekday + 0.5 * rng.normal(size=DAYS)
        found = analyse({"x": _series(x), "y": _series(y)}, _meta(["x", "y"]), TODAY)
        return _related(found, "x", "y")

    assert _rate(check) <= 0.1


def test_shared_trend_is_not_a_relationship():
    def check(seed: int) -> bool:
        rng = np.random.default_rng(4000 + seed)
        trend = np.linspace(0, 3, DAYS)
        x = trend + 0.5 * rng.normal(size=DAYS)
        y = trend + 0.5 * rng.normal(size=DAYS)
        found = analyse({"x": _series(x), "y": _series(y)}, _meta(["x", "y"]), TODAY)
        return _related(found, "x", "y")

    assert _rate(check) <= 0.1


def test_null_autocorrelated_noise_stays_within_the_fdr_target():
    """Twelve independent AR(1) series (phi 0.5): any reported relationship is a false discovery."""
    names = [f"f{i}" for i in range(12)]

    def check(seed: int) -> bool:
        rng = np.random.default_rng(5000 + seed)
        values = {n: _series(_ar1(rng, DAYS, 0.5)) for n in names}
        found = analyse(values, _meta(names), TODAY)
        return any(f.kind == "association" for f in found)

    # Under the global null, FDR equals the chance of any false hit; target 10% plus seed noise.
    assert _rate(check) <= 0.15


def test_planted_effects_among_noise_keep_false_discoveries_low():
    names = [f"f{i}" for i in range(10)]

    def check(seed: int) -> float:
        rng = np.random.default_rng(6000 + seed)
        values = {n: _ar1(rng, DAYS, 0.4) for n in names}
        values["f1"] = 0.6 * values["f0"] + 0.8 * values["f1"]
        values["f3"] = 0.6 * values["f2"] + 0.8 * values["f3"]
        found = analyse({n: _series(v) for n, v in values.items()}, _meta(names), TODAY)
        assoc = [f for f in found if f.kind == "association"]
        false = [f for f in assoc if {f.a, f.b} not in ({"f0", "f1"}, {"f2", "f3"})]
        return len(false) / len(assoc) if assoc else 0.0

    assert float(np.mean([check(s) for s in SEEDS])) <= 0.15


def test_same_family_features_are_never_related():
    rng = np.random.default_rng(7)
    x = rng.normal(size=DAYS)
    meta = {"x": FeatureMeta("x", family="activity"), "y": FeatureMeta("y", family="activity")}
    found = analyse({"x": _series(x), "y": _series(x * 2 + 0.01 * rng.normal(size=DAYS))}, meta, TODAY)
    assert not any(f.kind == "association" for f in found)


def test_weekly_step_change_is_found_and_flat_data_is_not():
    def check(seed: int, jump: float) -> bool:
        rng = np.random.default_rng(8000 + seed)
        y = 10 + rng.normal(size=DAYS)
        y[-7:] += jump
        found = analyse({"y": _series(y)}, _meta(["y"]), TODAY)
        return any(f.kind == "change" and f.horizon == "week" for f in found)

    assert float(np.mean([check(s, 4.0) for s in SEEDS])) >= 0.9
    assert float(np.mean([check(s, 0.0) for s in SEEDS])) <= 0.1


@pytest.mark.parametrize("phase", [0, 3])
def test_weekday_rhythm_is_found(phase):
    rng = np.random.default_rng(9 + phase)
    y = np.array([3.0 if (START + dt.timedelta(days=i)).weekday() in (5, 6) else 0.0 for i in range(DAYS)])
    y = y + rng.normal(size=DAYS)
    found = analyse({"y": _series(y)}, _meta(["y"]), TODAY)
    weekday = [f for f in found if f.kind == "weekday"]
    assert weekday and weekday[0].details["high"] in (5, 6)
