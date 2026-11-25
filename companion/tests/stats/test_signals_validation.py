"""Validation for the Overview's signals (R8; app/signals.py).

On pure noise, including carried-over (autocorrelated), skewed and gappy noise, a series must clear the bar on
only a small share of days: the Overview checks every series at once, so its bar must stay rare on noise. A
planted shift over the last two weeks (or a planted sharp drop over the last three days) must be found. Seeded
and synthetic (R4). ``STATS_SEEDS`` (default 20) sets the datasets per check.
"""

from __future__ import annotations

import datetime as dt
import os

import numpy as np
import pytest

from app.signals import NOW_DAYS, TREND_DAYS, TREND_MIN, Z_PIN, Def, compare, evaluate

SEEDS = range(int(os.environ.get("STATS_SEEDS", "20")))
DAYS = 90
START = dt.date(2026, 6, 1)
TODAY = START + dt.timedelta(days=DAYS)  # the last complete day is the day before
SERIES_PER_SEED = 50
D = Def("Thing", "x", "healthlog")


def _ar1(rng: np.random.Generator, n: int, phi: float) -> np.ndarray:
    out = np.empty(n)
    out[0] = rng.normal()
    for i in range(1, n):
        out[i] = phi * out[i - 1] + rng.normal() * np.sqrt(1 - phi * phi)
    return out


def _series(arr: np.ndarray, rng: np.random.Generator, missing: float = 0.0) -> dict[dt.date, float]:
    keep = rng.random(len(arr)) >= missing
    keep[-TREND_DAYS:] = True  # gaps in the history, not a gap signal at the end
    return {START + dt.timedelta(days=i): float(v) for i, v in enumerate(arr) if keep[i]}


NOISE = [
    ("white", 0.0, False, 0.0),
    ("carried over", 0.5, False, 0.0),
    ("strongly carried over", 0.8, False, 0.0),
    ("skewed", 0.4, True, 0.0),
    ("gappy", 0.4, False, 0.25),
]


@pytest.mark.parametrize(("name", "phi", "skewed", "missing"), NOISE, ids=[n[0] for n in NOISE])
def test_noise_rarely_clears_the_bar(name, phi, skewed, missing):
    fired = total = 0
    for seed in SEEDS:
        rng = np.random.default_rng(1000 + seed)
        for _ in range(SERIES_PER_SEED):
            arr = _ar1(rng, DAYS, phi)
            if skewed:
                arr = np.exp(0.6 * arr) * 4000  # step-count-like: long right tail
            fired += evaluate("x", D, _series(arr, rng, missing), TODAY) is not None
            total += 1
    # Across ~150 series a day, this keeps noise to about one signal a day at worst, before the per-family cap.
    assert fired / total <= 0.015, f"{name}: {fired} of {total}"


def test_the_pin_bar_stays_near_its_nominal_rate_on_noise():
    fired = total = 0
    for seed in SEEDS:
        rng = np.random.default_rng(2000 + seed)
        for _ in range(SERIES_PER_SEED):
            values = _series(_ar1(rng, DAYS, 0.5), rng)
            c = compare(values, TODAY - dt.timedelta(days=1), TREND_DAYS, TREND_MIN, Z_PIN)
            fired += c is not None and c.direction is not None
            total += 1
    assert fired / total <= 0.10, f"{fired} of {total}"


def test_a_planted_two_week_shift_is_found_with_its_direction():
    found = total = 0
    for seed in SEEDS:
        rng = np.random.default_rng(3000 + seed)
        for _ in range(SERIES_PER_SEED // 5):
            arr = _ar1(rng, DAYS, 0.4)
            arr[-TREND_DAYS:] -= 2.5  # the list searches everything, so it waits for a large shift
            s = evaluate("x", D, _series(arr, rng), TODAY)
            found += s is not None and s.kind == "trend" and s.direction == "down"
            total += 1
    assert found / total >= 0.8, f"{found} of {total}"


def test_a_planted_sharp_change_in_the_last_days_is_found():
    found = total = 0
    for seed in SEEDS:
        rng = np.random.default_rng(4000 + seed)
        for _ in range(SERIES_PER_SEED // 5):
            arr = _ar1(rng, DAYS, 0.3)
            arr[-NOW_DAYS:] += 4.0
            s = evaluate("x", D, _series(arr, rng), TODAY)
            found += s is not None and s.direction == "up"
            total += 1
    assert found / total >= 0.8, f"{found} of {total}"


def test_a_pinned_series_shows_a_moderate_two_week_shift():
    """Pins are a handful you chose to watch, so their bar is gentler: a 1.2-spread drop shows most of the time."""
    found = total = 0
    for seed in SEEDS:
        rng = np.random.default_rng(5000 + seed)
        for _ in range(SERIES_PER_SEED // 5):
            arr = _ar1(rng, DAYS, 0.4)
            arr[-TREND_DAYS:] -= 1.2
            c = compare(_series(arr, rng), TODAY - dt.timedelta(days=1), TREND_DAYS, TREND_MIN, Z_PIN)
            found += c is not None and c.direction == "down"
            total += 1
    assert found / total >= 0.7, f"{found} of {total}"
