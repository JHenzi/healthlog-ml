"""Adjusted re-check (R8): a link that only exists through sleep must read as explained by it; a direct link
must still hold once sleep is allowed for. Seeded and synthetic (R4)."""

from __future__ import annotations

import datetime as dt
import math
import os

import numpy as np

from app.analysis.engine import FeatureMeta, analyse

SEEDS = range(max(int(os.environ.get("STATS_SEEDS", "20")), 40))
START = dt.date(2026, 6, 1)
DAYS = 100
TODAY = START + dt.timedelta(days=DAYS)
SLEEP = "sleep.total_h"
META = {
    "x": FeatureMeta("x", family="fam_x"),
    "y": FeatureMeta("y", family="fam_y"),
    "flag": FeatureMeta("flag", kind="count", family="fam_flag"),
    SLEEP: FeatureMeta("Sleep", family="sleep"),
}


def _ar1(rng: np.random.Generator, n: int, phi: float) -> np.ndarray:
    out = np.empty(n)
    out[0] = rng.normal()
    for i in range(1, n):
        out[i] = phi * out[i - 1] + rng.normal() * math.sqrt(1 - phi * phi)
    return out


def _series(arr: np.ndarray) -> dict[dt.date, float]:
    return {START + dt.timedelta(days=i): float(v) for i, v in enumerate(arr)}


def _verdicts(make, pair: frozenset = frozenset({"x", "y"})) -> list[str]:
    """The adjusted verdict of the pair's finding in each dataset where it was reported."""
    out = []
    for seed in SEEDS:
        values = make(np.random.default_rng(seed))
        found = analyse(values, {k: META[k] for k in values}, TODAY)
        hits = [f for f in found if f.kind == "association" and {f.a, f.b} == pair]
        if hits and "adjusted" in hits[0].details:
            out.append(hits[0].details["adjusted"]["verdict"])
    return out


def test_a_link_through_sleep_reads_as_explained():
    def make(rng):
        sleep = _ar1(rng, DAYS, 0.3)
        return {
            SLEEP: _series(sleep),
            "x": _series(0.8 * sleep + 0.6 * rng.normal(size=DAYS)),
            "y": _series(0.8 * sleep + 0.6 * rng.normal(size=DAYS)),
        }

    verdicts = _verdicts(make)
    assert len(verdicts) >= 0.8 * len(SEEDS)  # the raw link is found...
    assert verdicts.count("explained") >= 0.85 * len(verdicts)  # ...and sleep accounts for it


def test_a_direct_link_still_holds():
    def make(rng):
        x = _ar1(rng, DAYS, 0.3)
        return {
            SLEEP: _series(_ar1(rng, DAYS, 0.3)),
            "x": _series(x),
            "y": _series(0.6 * x + 0.8 * rng.normal(size=DAYS)),
        }

    verdicts = _verdicts(make)
    assert len(verdicts) >= 0.8 * len(SEEDS)
    assert verdicts.count("holds") >= 0.85 * len(verdicts)


def test_a_yes_no_link_through_sleep_reads_as_explained():
    def make(rng):
        sleep = _ar1(rng, DAYS, 0.3)
        flag = (sleep + 0.5 * rng.normal(size=DAYS) < -0.5).astype(float)  # short nights make the event likelier
        return {SLEEP: _series(sleep), "flag": _series(flag), "y": _series(0.8 * sleep + 0.6 * rng.normal(size=DAYS))}

    verdicts = _verdicts(make, frozenset({"flag", "y"}))
    assert len(verdicts) >= 0.6 * len(SEEDS)
    assert verdicts.count("holds") <= 0.15 * len(verdicts)
