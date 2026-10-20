"""Outside data: weather and air quality for the home area (M3).

The Companion makes no outbound request (R5). The ``companion-collector``
sidecar fetches Open-Meteo and writes ``weather-hourly.csv`` to a volume the
Companion mounts read-only. ``load_weather`` validates the whole file against
a strict schema (exact columns, UTC hours, numeric ranges) and loads nothing if
any line fails (risks.md E2/E3); otherwise it upserts the hours into
``weather_hours``. Daily features (``weather_features``) are pure.

The engine treats weather like any other series (R17).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import math
import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .models import WeatherHourRow
from .timeutil import day_bounds, local_day

log = logging.getLogger("companion.outside")

FILE_NAME = "weather-hourly.csv"
MAX_FILE_BYTES = 50_000_000
# Column -> plausible range. Anything outside it rejects the file: a bad fetch is never partly believed.
RANGES = {
    "temperature_c": (-90.0, 60.0),
    "humidity_pct": (0.0, 100.0),
    "dew_point_c": (-90.0, 40.0),
    "pressure_hpa": (850.0, 1090.0),
    "precipitation_mm": (0.0, 500.0),
    "cloud_pct": (0.0, 100.0),
    "wind_kmh": (0.0, 500.0),
    "uv_index": (0.0, 20.0),
    "radiation_wm2": (0.0, 1500.0),
    "pm25": (0.0, 2000.0),
    "pm10": (0.0, 3000.0),
    "us_aqi": (0.0, 800.0),
}
COLUMNS = tuple(RANGES)
HEADER = ("time_utc", *COLUMNS)
_HOUR = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:00Z$")

# A day needs this many hours of a variable for its daily value (DST days have 23 or 25).
MIN_HOURS = 20


class OutsideDataError(ValueError):
    """The collector's file failed validation; nothing from it was loaded."""


@dataclass(frozen=True)
class WeatherHour:
    time: dt.datetime  # UTC, on the hour
    values: dict[str, float | None]


def parse_weather_csv(text: str) -> list[WeatherHour]:
    """All hours of the file, or OutsideDataError naming the first problem."""
    reader = csv.reader(io.StringIO(text))
    if tuple(next(reader, ())) != HEADER:
        raise OutsideDataError("unexpected columns")
    out: list[WeatherHour] = []
    seen: set[str] = set()
    for line, row in enumerate(reader, start=2):
        if len(row) != len(HEADER):
            raise OutsideDataError(f"line {line}: {len(row)} fields, expected {len(HEADER)}")
        stamp = row[0]
        if not _HOUR.match(stamp) or stamp in seen:
            raise OutsideDataError(f"line {line}: bad or repeated hour")
        seen.add(stamp)
        try:
            time = dt.datetime.strptime(stamp, "%Y-%m-%dT%H:00Z").replace(tzinfo=dt.UTC)
        except ValueError as exc:
            raise OutsideDataError(f"line {line}: bad hour") from exc
        values: dict[str, float | None] = {}
        for column, raw in zip(COLUMNS, row[1:], strict=True):
            if raw == "":
                values[column] = None
                continue
            try:
                value = float(raw)
            except ValueError as exc:
                raise OutsideDataError(f"line {line}: {column} is not a number") from exc
            lo, hi = RANGES[column]
            if not math.isfinite(value) or not lo <= value <= hi:
                raise OutsideDataError(f"line {line}: {column} outside {lo:g}..{hi:g}")
            values[column] = value
        out.append(WeatherHour(time, values))
    return out


@dataclass(frozen=True)
class LoadResult:
    status: str  # off | loaded | rejected
    hours: int = 0


def load_weather(db: Session, directory: Path) -> LoadResult:
    """Validate the collector's file and upsert its hours. A missing file means weather is off."""
    path = directory / FILE_NAME
    if not path.is_file():
        return LoadResult("off")
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise OutsideDataError("file too large")
        hours = parse_weather_csv(path.read_text(encoding="utf-8"))
    except (OutsideDataError, UnicodeDecodeError) as exc:
        log.warning("weather file rejected, nothing loaded: %s", exc)
        return LoadResult("rejected")
    rows = [{"time": h.time, **h.values} for h in hours]
    for start in range(0, len(rows), 5000):
        chunk = rows[start : start + 5000]
        stmt = insert(WeatherHourRow).values(chunk)
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["time"],
                set_={**{c: getattr(stmt.excluded, c) for c in COLUMNS}, "loaded_at": sa.func.now()},
            )
        )
    log.info("weather: %d hours loaded", len(rows))
    return LoadResult("loaded", len(rows))


def stored_hours(db: Session, since: dt.datetime | None = None) -> list[WeatherHour]:
    query = sa.select(WeatherHourRow).order_by(WeatherHourRow.time)
    if since is not None:
        query = query.where(WeatherHourRow.time >= since)
    return [WeatherHour(r.time, {c: getattr(r, c) for c in COLUMNS}) for r in db.execute(query).scalars()]


# --- daily features ----------------------------------------------------------


@dataclass(frozen=True)
class WeatherDef:
    feature: str
    label: str
    unit: str | None
    analyse: bool


# Every one is analysed (R17); near-duplicates (high, low and mean temperature) share the family, so they are
# never tested against each other.
DEFS = (
    WeatherDef("weather.temp_mean", "Temperature (mean)", "°C", True),
    WeatherDef("weather.temp_max", "Temperature (high)", "°C", True),
    WeatherDef("weather.temp_min", "Temperature (low)", "°C", True),
    WeatherDef("weather.temp_range", "Temperature swing (high − low)", "°C", True),
    WeatherDef("weather.humidity_mean", "Humidity (mean)", "%", True),
    WeatherDef("weather.dew_point_mean", "Dew point (mean)", "°C", True),
    WeatherDef("weather.pressure_mean", "Air pressure (mean)", "hPa", True),
    WeatherDef("weather.pressure_change", "Air pressure change from the day before", "hPa", True),
    WeatherDef("weather.precipitation", "Precipitation", "mm", True),
    WeatherDef("weather.cloud_mean", "Cloud cover (mean)", "%", True),
    WeatherDef("weather.wind_max", "Wind (strongest hour)", "km/h", True),
    WeatherDef("weather.uv_max", "UV index (highest)", None, True),
    WeatherDef("weather.radiation", "Sunlight energy", "kWh/m²", True),
    WeatherDef("weather.pm25_mean", "Fine particles PM2.5 (mean)", "µg/m³", True),
    WeatherDef("weather.aqi_max", "Air quality index (worst hour, US AQI)", None, True),
)


def _by_day(
    hours: Iterable[WeatherHour], zone: ZoneInfo, boundary: dt.time, now: dt.datetime
) -> dict[dt.date, list[WeatherHour]]:
    """Hours grouped by Companion day, complete days only (a day still running would look calm)."""
    out: dict[dt.date, list[WeatherHour]] = {}
    for h in hours:
        out.setdefault(local_day(h.time, zone, boundary), []).append(h)
    return {d: hs for d, hs in out.items() if day_bounds(d, zone, boundary)[1] <= now}


def _values(hours: list[WeatherHour], column: str) -> list[float] | None:
    vals = [h.values[column] for h in hours if h.values.get(column) is not None]
    return vals if len(vals) >= MIN_HOURS else None


def weather_features(
    hours: Iterable[WeatherHour], zone: ZoneInfo, boundary: dt.time, now: dt.datetime
) -> dict[str, dict[dt.date, float]]:
    """One value per complete Companion day and feature; a day with too few hours of a variable has none."""
    out: dict[str, dict[dt.date, float]] = {d.feature: {} for d in DEFS}

    def put(feature: str, day: dt.date, value: float) -> None:
        out[feature][day] = round(value, 3)

    pressure: dict[dt.date, float] = {}
    for day, hs in _by_day(hours, zone, boundary, now).items():
        if t := _values(hs, "temperature_c"):
            put("weather.temp_mean", day, statistics.fmean(t))
            put("weather.temp_max", day, max(t))
            put("weather.temp_min", day, min(t))
            put("weather.temp_range", day, max(t) - min(t))
        for column, feature in (
            ("humidity_pct", "weather.humidity_mean"),
            ("dew_point_c", "weather.dew_point_mean"),
            ("cloud_pct", "weather.cloud_mean"),
            ("pm25", "weather.pm25_mean"),
        ):
            if v := _values(hs, column):
                put(feature, day, statistics.fmean(v))
        for column, feature in (("wind_kmh", "weather.wind_max"), ("uv_index", "weather.uv_max")):
            if v := _values(hs, column):
                put(feature, day, max(v))
        if (v := _values(hs, "us_aqi")) is not None:
            put("weather.aqi_max", day, max(v))
        if (v := _values(hs, "precipitation_mm")) is not None:
            put("weather.precipitation", day, sum(v))
        if (v := _values(hs, "radiation_wm2")) is not None:
            put("weather.radiation", day, sum(v) / 1000)  # hourly W/m² -> kWh/m² for the day
        if p := _values(hs, "pressure_hpa"):
            pressure[day] = statistics.fmean(p)
            put("weather.pressure_mean", day, pressure[day])
    for day, mean in pressure.items():
        before = pressure.get(day - dt.timedelta(days=1))
        if before is not None:
            put("weather.pressure_change", day, mean - before)
    return {f: v for f, v in out.items() if v}
