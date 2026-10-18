"""Settings: no inherited time zone (R14, risks.md B1)."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from app.config import Settings

BASE = {"DATABASE_URL": "postgresql+psycopg://companion:x@localhost/healthlog"}


def _settings(monkeypatch, **env) -> Settings:
    for key in ("TZ", "DAY_BOUNDARY", "DATABASE_URL"):
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
