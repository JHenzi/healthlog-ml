"""Weather collector: the Companion's one outbound path (R5; next-steps.md §4.2).

It runs in its own container, which has network access but no database credentials and no health data. It
sends Open-Meteo a home location rounded to 0.1° (about 10 km) and a date range, nothing else (risks.md E3).
The hours it gets back go into a CSV file on a shared volume. The Companion mounts that volume read-only,
validates the whole file and loads it (``app/outside.py``); it never makes a request itself.

  collector run                       # backfill if there's no file yet, then refresh the last days every night
  collector backfill [--since DATE]   # fetch every hour since DATE (default WEATHER_SINCE) and merge it in
  collector once                      # refresh the last REFRESH_DAYS days now

Standard library only, so the image needs no package downloads.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import math
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

log = logging.getLogger("collector")

# Open-Meteo: no key, no account. The historical-forecast API serves one model from 2022 up to the current
# hour, so the backfill and the nightly refresh agree.
ENDPOINTS = {
    "weather": "https://historical-forecast-api.open-meteo.com/v1/forecast",
    "air": "https://air-quality-api.open-meteo.com/v1/air-quality",
}
ALLOWED_HOSTS = frozenset(urlparse(u).hostname for u in ENDPOINTS.values())
# Open-Meteo variable -> our column (the Companion's schema in app/outside.py must match).
VARIABLES = {
    "weather": {
        "temperature_2m": "temperature_c",
        "relative_humidity_2m": "humidity_pct",
        "dew_point_2m": "dew_point_c",
        "pressure_msl": "pressure_hpa",
        "precipitation": "precipitation_mm",
        "cloud_cover": "cloud_pct",
        "wind_speed_10m": "wind_kmh",
        "uv_index": "uv_index",
        "shortwave_radiation": "radiation_wm2",
    },
    "air": {"pm2_5": "pm25", "pm10": "pm10", "us_aqi": "us_aqi"},
}
COLUMNS = tuple(c for names in VARIABLES.values() for c in names.values())
HEADER = ("time_utc", *COLUMNS)
FILE_NAME = "weather-hourly.csv"

CHUNK_DAYS = 92  # one request covers at most this many days
REFRESH_DAYS = 10  # recent values are revised for a few days, so the nightly run re-fetches these
RUN_AT = dt.time(3, 40)  # local; before the Companion's 04:15 refresh
RETRY_SECONDS = 3600
MAX_RESPONSE_BYTES = 20_000_000
TIMEOUT_SECONDS = 60

Rows = dict[str, dict[str, float | None]]  # "YYYY-MM-DDTHH:00Z" -> column -> value


def coarse(value: float) -> float:
    """Round a coordinate to 0.1° (~11 km north-south): enough for weather, too coarse to find a home."""
    return round(value, 1)


@dataclass(frozen=True)
class Config:
    latitude: float
    longitude: float
    since: dt.date
    directory: Path
    zone: ZoneInfo

    @property
    def path(self) -> Path:
        return self.directory / FILE_NAME


def config_from_env(env: dict[str, str]) -> Config | None:
    """None when no location is set: weather is opt-in."""
    lat, lon = env.get("WEATHER_LATITUDE", "").strip(), env.get("WEATHER_LONGITUDE", "").strip()
    if not lat or not lon:
        return None
    latitude, longitude = float(lat), float(lon)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("WEATHER_LATITUDE / WEATHER_LONGITUDE out of range")
    zone = ZoneInfo(env.get("TZ") or "UTC")
    since_raw = env.get("WEATHER_SINCE", "").strip()
    since = dt.date.fromisoformat(since_raw) if since_raw else dt.datetime.now(zone).date() - dt.timedelta(days=92)
    return Config(coarse(latitude), coarse(longitude), since, Path(env.get("WEATHER_DIR") or "/data"), zone)


def request_url(kind: str, latitude: float, longitude: float, start: dt.date, end: dt.date) -> str:
    """The whole request: rounded coordinates, a date range, the variables, UTC. Nothing else is sent."""
    params = {
        "latitude": f"{coarse(latitude):.1f}",
        "longitude": f"{coarse(longitude):.1f}",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(VARIABLES[kind]),
        "timezone": "GMT",
    }
    return f"{ENDPOINTS[kind]}?{urlencode(params)}"


def fetch_json(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"refusing a request to {parsed.hostname!r}: not an allowlisted host")
    request = Request(url, headers={"User-Agent": "healthlog-companion-collector"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("response too large")
    return json.loads(body)


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"not a number: {value!r}")
    return float(value)


def hours_from(payload: dict, names: dict[str, str]) -> Rows:
    """Open-Meteo's hourly arrays -> rows keyed by UTC hour."""
    hourly = payload["hourly"]
    times = hourly["time"]
    out: Rows = {}
    for name, column in names.items():
        values = hourly[name]
        if len(values) != len(times):
            raise ValueError(f"{name}: {len(values)} values for {len(times)} hours")
        for t, v in zip(times, values, strict=True):
            stamp = dt.datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=dt.UTC).strftime("%Y-%m-%dT%H:00Z")
            out.setdefault(stamp, {})[column] = _number(v)
    return out


def fetch_range(
    latitude: float, longitude: float, start: dt.date, end: dt.date, get: Callable[[str], dict] = fetch_json
) -> Rows:
    """Every hour from ``start`` to ``end`` (UTC dates, inclusive), in chunks. Air quality is best effort."""
    out: Rows = {}
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + dt.timedelta(days=CHUNK_DAYS - 1))
        for kind, names in VARIABLES.items():
            try:
                rows = hours_from(get(request_url(kind, latitude, longitude, chunk_start, chunk_end)), names)
            except Exception as exc:
                if kind == "weather":
                    raise
                log.warning("air quality %s..%s not fetched: %s", chunk_start, chunk_end, exc)
                continue
            for stamp, values in rows.items():
                out.setdefault(stamp, {}).update(values)
        chunk_start = chunk_end + dt.timedelta(days=1)
    return out


def merge(existing: Rows, fetched: Rows, now: dt.datetime) -> Rows:
    """Fetched values replace stored ones; a missing (None) value never erases a stored one. Future hours
    (forecasts) are dropped: the file holds what happened."""
    out = {k: dict(v) for k, v in existing.items()}
    cutoff = now.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:00Z")
    for stamp, values in fetched.items():
        if stamp > cutoff:
            continue
        row = out.setdefault(stamp, {})
        for column, value in values.items():
            if value is not None or column not in row:
                row[column] = value
    return out


def read_file(path: Path) -> Rows:
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        reader = csv.reader(f)
        if tuple(next(reader, ())) != HEADER:
            raise ValueError(f"{path} has an unexpected header; move it aside to start over")
        return {r[0]: {c: (float(v) if v else None) for c, v in zip(COLUMNS, r[1:], strict=True)} for r in reader}


def write_file(path: Path, rows: Rows) -> None:
    """Atomically: the Companion never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for stamp in sorted(rows):
            row = rows[stamp]
            w.writerow([stamp, *("" if row.get(c) is None else repr(row[c]) for c in COLUMNS)])
    os.replace(tmp, path)


def collect(cfg: Config, start: dt.date, now: dt.datetime, get: Callable[[str], dict] = fetch_json) -> int:
    """Fetch ``start``..today and merge into the file; returns the number of hours in the file."""
    end = now.astimezone(dt.UTC).date()
    rows = merge(read_file(cfg.path), fetch_range(cfg.latitude, cfg.longitude, start, end, get), now)
    write_file(cfg.path, rows)
    log.info("weather: %s..%s fetched, %d hours on file", start, end, len(rows))
    return len(rows)


def once(cfg: Config, now: dt.datetime, get: Callable[[str], dict] = fetch_json) -> int:
    """The nightly run: a full backfill if there's no file yet, else the last REFRESH_DAYS days."""
    if not cfg.path.exists():
        return collect(cfg, cfg.since, now, get)
    return collect(cfg, now.astimezone(dt.UTC).date() - dt.timedelta(days=REFRESH_DAYS), now, get)


def next_run(now: dt.datetime, zone: ZoneInfo) -> dt.datetime:
    local = now.astimezone(zone)
    at = dt.datetime.combine(local.date(), RUN_AT, tzinfo=zone)
    if at <= local:
        at = dt.datetime.combine(local.date() + dt.timedelta(days=1), RUN_AT, tzinfo=zone)
    return at


def run(cfg: Config | None) -> int:
    if cfg is None:
        log.warning("weather is off: set WEATHER_LATITUDE and WEATHER_LONGITUDE to turn it on")
        while True:  # stay up quietly instead of restart-looping
            time.sleep(86400)
    while True:
        try:
            once(cfg, dt.datetime.now(dt.UTC))
            wait = (next_run(dt.datetime.now(dt.UTC), cfg.zone) - dt.datetime.now(dt.UTC)).total_seconds()
        except Exception:
            log.exception("weather fetch failed; retrying in %d s", RETRY_SECONDS)
            wait = RETRY_SECONDS
        time.sleep(max(wait, 60))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="collector", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="backfill if needed, then refresh every night")
    back = sub.add_parser("backfill", help="fetch every hour since a date and merge it into the file")
    back.add_argument("--since", type=dt.date.fromisoformat, help="first date (default: WEATHER_SINCE)")
    sub.add_parser("once", help="refresh the last days now")
    args = parser.parse_args(argv)
    cfg = config_from_env(dict(os.environ))
    if args.command == "run":
        return run(cfg)
    if cfg is None:
        print("weather is off: set WEATHER_LATITUDE and WEATHER_LONGITUDE", file=sys.stderr)
        return 2
    now = dt.datetime.now(dt.UTC)
    if args.command == "backfill":
        hours = collect(cfg, args.since or cfg.since, now)
    else:
        hours = once(cfg, now)
    print(f"weather: {hours} hours on file ({cfg.path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
