"""Environment settings (secrets + infrastructure), same split as upstream.

``TZ`` has no default on purpose: HealthLog silently defaulted to Vienna and
shifted every day for a US user (risks.md L1). The Companion refuses to start
without it (R14).
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

    # Connects as the `companion` role: owner of schema `companion`, SELECT-only on `public` (R2).
    database_url: str = Field(alias="DATABASE_URL")
    tz: str = Field(alias="TZ")
    # Local clock time at which one "day" ends and the next begins (late nights count as the same day).
    day_boundary: dt.time = Field(default=dt.time(4, 0), alias="DAY_BOUNDARY")
    cookie_secure: bool = Field(default=True, alias="COOKIE_SECURE")
    session_days: int = Field(default=30, alias="SESSION_DAYS")
    login_max_failures: int = Field(default=5, alias="LOGIN_MAX_FAILURES")
    login_lockout_minutes: int = Field(default=15, alias="LOGIN_LOCKOUT_MINUTES")
    # Same semantics as HealthLog's TRUSTED_PROXIES (empty = private ranges, '*' = all).
    trusted_proxies: str = Field(default="", alias="TRUSTED_PROXIES")

    @field_validator("tz")
    @classmethod
    def _valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"TZ={value!r} is not a known IANA time zone") from exc
        return value

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)


@lru_cache
def get_settings() -> Settings:
    return Settings()
