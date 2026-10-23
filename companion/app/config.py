"""Environment settings (secrets + infrastructure), same split as upstream.

``TZ`` has no default on purpose: HealthLog silently defaulted to Vienna and
shifted every day for a US user (risks.md L1). The Companion refuses to start
without it (R14).
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .almanac import SUPPORTED, country_for_zone


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
    # The collector's files (weather), mounted read-only. No file there means weather is off.
    outside_dir: Path = Field(default=Path("/outside"), alias="OUTSIDE_DIR")
    # The almanac (day length): the weather location's latitude only, rounded to 0.1°. Unset: no day length.
    latitude: float | None = Field(default=None, alias="WEATHER_LATITUDE")
    # Public holidays: a country code (US, CA, GB, DE), "none" to turn them off, or empty to go by TZ.
    holidays_country: str = Field(default="", alias="HOLIDAYS_COUNTRY")
    # Reminders (web push, opt-in): VAPID keys from `companion push keys`. Unset: no reminders are prepared.
    vapid_public_key: str = Field(default="", alias="VAPID_PUBLIC_KEY")
    vapid_private_key: str = Field(default="", alias="VAPID_PRIVATE_KEY")
    # Apple refuses a subject at localhost (403 BadJwtToken), so the default is the project's page.
    vapid_subject: str = Field(default="https://github.com/JHenzi/healthlog-ml", alias="VAPID_SUBJECT")
    # Sealed reminders go here for the courier to deliver (shared volume). The Companion never sends (R5).
    push_dir: Path = Field(default=Path("/push"), alias="PUSH_DIR")

    @field_validator("tz")
    @classmethod
    def _valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"TZ={value!r} is not a known IANA time zone") from exc
        return value

    @field_validator("latitude", mode="before")
    @classmethod
    def _coarse_latitude(cls, value: object) -> float | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        latitude = float(value)
        if not -90 <= latitude <= 90:
            raise ValueError("WEATHER_LATITUDE must be between -90 and 90")
        return round(latitude, 1)

    @field_validator("holidays_country")
    @classmethod
    def _known_country(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in ("", "NONE", *SUPPORTED):
            raise ValueError(f"HOLIDAYS_COUNTRY={value!r}: use one of {', '.join(SUPPORTED)} or none")
        return value

    @property
    def holiday_country(self) -> str | None:
        if self.holidays_country == "NONE":
            return None
        return self.holidays_country or country_for_zone(self.tz)

    @property
    def push_on(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)


@lru_cache
def get_settings() -> Settings:
    return Settings()
