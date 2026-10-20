"""Settings: no inherited time zone (R14, risks.md B1)."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from app.config import Settings

BASE = {"DATABASE_URL": "postgresql+psycopg://companion:x@localhost/healthlog"}


def _settings(monkeypatch, **env) -> Settings:
    for key in ("TZ", "DAY_BOUNDARY", "DATABASE_URL", "WEATHER_LATITUDE", "HOLIDAYS_COUNTRY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {**BASE, **env}.items():
        monkeypatch.setenv(key, value)
    return Settings()


def test_missing_tz_refuses_to_start(monkeypatch):
    with pytest.raises(ValidationError):
        _settings(monkeypatch)


def test_unknown_tz_refuses_to_start(monkeypatch):
    with pytest.raises(ValidationError):
        _settings(monkeypatch, TZ="Mars/Olympus")


def test_day_boundary_default_and_override(monkeypatch):
    assert _settings(monkeypatch, TZ="America/New_York").day_boundary == dt.time(4, 0)
    assert _settings(monkeypatch, TZ="America/New_York", DAY_BOUNDARY="05:30").day_boundary == dt.time(5, 30)


def test_latitude_is_coarse_and_optional(monkeypatch):
    assert _settings(monkeypatch, TZ="America/New_York").latitude is None
    assert _settings(monkeypatch, TZ="America/New_York", WEATHER_LATITUDE="").latitude is None
    assert _settings(monkeypatch, TZ="America/New_York", WEATHER_LATITUDE="40.7128").latitude == 40.7
    with pytest.raises(ValidationError):
        _settings(monkeypatch, TZ="America/New_York", WEATHER_LATITUDE="91")


def test_holiday_country_follows_tz_unless_set(monkeypatch):
    assert _settings(monkeypatch, TZ="America/New_York").holiday_country == "US"
    assert _settings(monkeypatch, TZ="Asia/Tokyo").holiday_country is None
    assert _settings(monkeypatch, TZ="America/New_York", HOLIDAYS_COUNTRY="de").holiday_country == "DE"
    assert _settings(monkeypatch, TZ="America/New_York", HOLIDAYS_COUNTRY="none").holiday_country is None
    with pytest.raises(ValidationError):
        _settings(monkeypatch, TZ="America/New_York", HOLIDAYS_COUNTRY="FR")
