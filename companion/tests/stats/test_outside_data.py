"""Weather in the engine (R8, R17): tested like any other series, in both time orders. A planted weather effect on
the next day is found with the weather first; a series the weather follows is found with that series first;
unrelated weather with a season stays quiet. Seeded and synthetic (R4)."""

from __future__ import annotations

import datetime as dt
import math
import os

import numpy as np

from app.analysis.engine import FeatureMeta, analyse

SEEDS = range(int(os.environ.get("STATS_SEEDS", "20")))
START = dt.date(2026, 6, 1)
DAYS = 120
TODAY = START + dt.timedelta(days=DAYS)
META = {
    "weather.temp_mean": FeatureMeta("Temperature", "°C", family="weather"),
    "weather.pressure_change": FeatureMeta("Pressure change", "hPa", family="weather"),
    "sleep.total_h": FeatureMeta("Sleep", "h", family="sleep"),
    "hl.headache": FeatureMeta("Headache", family="symptom"),
}


def _series(arr: np.ndarray) -> dict[dt.date, float]:
    return {START + dt.timedelta(days=i): float(v) for i, v in enumerate(arr)}


def _ar1(rng: np.random.Generator, n: int, phi: float) -> np.ndarray:
    out = np.empty(n)
    out[0] = rng.normal()
    for i in range(1, n):
        out[i] = phi * out[i - 1] + rng.normal() * math.sqrt(1 - phi * phi)
    return out


def _weather(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    season = np.linspace(22, 8, DAYS)  # summer into autumn
    weekday = np.array([(START + dt.timedelta(days=i)).weekday() >= 5 for i in range(DAYS)]) * 3.0
    temp = season + weekday + 3 * _ar1(rng, DAYS, 0.7)
    pressure = 4 * _ar1(rng, DAYS, 0.2)
    return temp, pressure


def test_a_weather_effect_on_the_next_day_is_found():
    found = 0
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        temp, pressure = _weather(rng)
        sleep = 7 + 0.3 * rng.normal(size=DAYS)
        sleep[1:] -= 0.12 * pressure[:-1]  # a pressure change goes with shorter sleep the next night
        values = {
            "weather.temp_mean": _series(temp),
            "weather.pressure_change": _series(pressure),
            "sleep.total_h": _series(sleep),
        }
        hits = [
            f
            for f in analyse(values, META, TODAY)
            if f.kind == "association" and {f.a, f.b} == {"weather.pressure_change", "sleep.total_h"}
        ]
        found += bool(hits and hits[0].a == "weather.pressure_change" and hits[0].lag == 1)
    assert found >= 0.8 * len(SEEDS)


def test_a_series_the_weather_follows_is_reported_in_time_order():
    found = 0
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        temp, pressure = _weather(rng)
        headache = (rng.random(DAYS) < 0.3).astype(float)
        pressure[1:] += 4 * headache[:-1]  # headaches come the day before a pressure rise: measured, not presumed
        values = {
            "weather.temp_mean": _series(temp),
            "weather.pressure_change": _series(pressure),
            "hl.headache": _series(headache),
            "sleep.total_h": _series(7 + 0.3 * rng.normal(size=DAYS)),
        }
        hits = [
            f
            for f in analyse(values, META, TODAY)
            if f.kind == "association" and {f.a, f.b} == {"hl.headache", "weather.pressure_change"}
        ]
        found += bool(hits and hits[0].a == "hl.headache" and hits[0].lag == 1)
    assert found >= 0.8 * len(SEEDS)


def test_unrelated_weather_stays_quiet():
    false = 0
    for seed in SEEDS:
        rng = np.random.default_rng(1000 + seed)
        temp, pressure = _weather(rng)
        values = {
            "weather.temp_mean": _series(temp),
            "weather.pressure_change": _series(pressure),
            "sleep.total_h": _series(7 + 0.5 * _ar1(rng, DAYS, 0.5)),
            "hl.headache": _series((rng.random(DAYS) < 0.3).astype(float)),
        }
        false += any(f.kind == "association" for f in analyse(values, META, TODAY))
    assert false <= max(2, 0.15 * len(SEEDS))
