"""The weather collector (R5, risks.md E2/E3): what it sends, where it may connect, and the file it writes.
No network: requests go to a fake. Synthetic values only (R4)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest

from app import outside

_PATH = Path(__file__).resolve().parents[2] / "collector" / "collector.py"
_spec = importlib.util.spec_from_file_location("collector", _PATH)
collector = importlib.util.module_from_spec(_spec)
sys.modules["collector"] = collector
_spec.loader.exec_module(collector)


def test_the_request_carries_only_rounded_coordinates_dates_and_variables():
    url = collector.request_url("weather", 40.7128, -74.0061, dt.date(2026, 7, 15), dt.date(2026, 10, 14))
    parsed = urlparse(url)
    assert parsed.scheme == "https" and parsed.hostname == "historical-forecast-api.open-meteo.com"
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert set(q) == {"latitude", "longitude", "start_date", "end_date", "hourly", "timezone"}
    assert (q["latitude"], q["longitude"]) == ("40.7", "-74.0")
    assert (q["start_date"], q["end_date"], q["timezone"]) == ("2026-07-15", "2026-10-14", "GMT")


def test_config_rounds_the_location_and_weather_is_off_without_one():
    cfg = collector.config_from_env({"WEATHER_LATITUDE": "40.71", "WEATHER_LONGITUDE": "-74.04", "TZ": "UTC"})
    assert (cfg.latitude, cfg.longitude) == (40.7, -74.0)
    assert collector.config_from_env({"TZ": "UTC"}) is None
    with pytest.raises(ValueError):
        collector.config_from_env({"WEATHER_LATITUDE": "140", "WEATHER_LONGITUDE": "0"})


def test_only_allowlisted_hosts_are_fetched():
    for url in ("https://example.com/v1/forecast", "http://historical-forecast-api.open-meteo.com/v1/forecast"):
        with pytest.raises(ValueError, match="allowlisted"):
            collector.fetch_json(url)


def _fake_api(calls: list[str]):
    def get(url: str) -> dict:
        calls.append(url)
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        start, end = dt.date.fromisoformat(q["start_date"]), dt.date.fromisoformat(q["end_date"])
        n = ((end - start).days + 1) * 24
        times = [
            (dt.datetime.combine(start, dt.time(0)) + dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M")
            for i in range(n)
        ]
        hourly = {"time": times}
        for name in q["hourly"].split(","):
            hourly[name] = [None if name == "uv_index" and i % 2 else 5.0 for i in range(n)]
        if "pressure_msl" in hourly:
            hourly["pressure_msl"] = [1012.0] * n
        return {"hourly": hourly}

    return get


def test_backfill_writes_a_file_the_companion_accepts(tmp_path):
    cfg = collector.Config(40.7, -74.0, dt.date(2026, 7, 15), tmp_path, ZoneInfo("UTC"))
    calls: list[str] = []
    now = dt.datetime(2026, 10, 20, 9, 30, tzinfo=dt.UTC)
    hours = collector.collect(cfg, cfg.since, now, _fake_api(calls))
    assert len(calls) == 4  # two 92-day chunks x (weather, air quality)
    # Every hour from Jul 15 00:00 to now; forecast hours later today are dropped.
    assert hours == (dt.date(2026, 10, 20) - dt.date(2026, 7, 15)).days * 24 + 10
    parsed = outside.parse_weather_csv(cfg.path.read_text())
    assert len(parsed) == hours and parsed[-1].time == dt.datetime(2026, 10, 20, 9, tzinfo=dt.UTC)
    assert collector.HEADER == outside.HEADER


def test_a_missing_value_never_erases_a_stored_one():
    now = dt.datetime(2026, 10, 20, tzinfo=dt.UTC)
    merged = collector.merge(
        {"2026-10-19T00:00Z": {"pm25": 4.0, "uv_index": 1.0}},
        {"2026-10-19T00:00Z": {"pm25": None, "uv_index": 2.0}, "2026-10-21T00:00Z": {"pm25": 1.0}},
        now,
    )
    assert merged == {"2026-10-19T00:00Z": {"pm25": 4.0, "uv_index": 2.0}}


def test_air_quality_is_best_effort_but_weather_is_not(tmp_path):
    def no_air(url: str) -> dict:
        if "air-quality" in url:
            raise OSError("unreachable")
        return _fake_api([])(url)

    rows = collector.fetch_range(40.7, -74.0, dt.date(2026, 10, 1), dt.date(2026, 10, 1), no_air)
    assert len(rows) == 24 and "pm25" not in rows["2026-10-01T00:00Z"]

    def no_weather(url: str) -> dict:
        raise OSError("unreachable")

    with pytest.raises(OSError):
        collector.fetch_range(40.7, -74.0, dt.date(2026, 10, 1), dt.date(2026, 10, 1), no_weather)


def test_the_nightly_run_is_before_the_companion_refresh():
    zone = ZoneInfo("America/New_York")
    after = dt.datetime(2026, 10, 20, 12, tzinfo=dt.UTC)  # 08:00 local
    assert collector.next_run(after, zone) == dt.datetime(2026, 10, 21, 3, 40, tzinfo=zone)
