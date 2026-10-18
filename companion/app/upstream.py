"""The read contract with HealthLog (R3).

Every HealthLog table and column the Companion reads is listed in
``CONTRACT``, and every query against schema ``public`` lives in this module.
Reads go to base tables only, never HealthLog's views, which its migrations
drop and rebuild. ``check_upstream`` verifies the contract against the live
database at startup, in the nightly job and via ``companion check-upstream``;
a mismatch degrades the affected feature with a clear message instead of
breaking anything.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .timeutil import boundary_interval, day_bounds, sql_day_expr

UPSTREAM_SCHEMA = "public"

CONTRACT: dict[str, tuple[str, ...]] = {
    "metric_samples": ("time", "metric", "source", "qty", "vmin", "vavg", "vmax"),
    "metric_registry": ("metric", "display_name", "unit_canonical", "agg_default", "category", "tier"),
    "sleep_sessions": ("sleep_start", "sleep_end", "source", "total_sleep_h", "deep_h", "core_h", "rem_h", "awake_h"),
    "stress_intraday": ("ts", "stress", "state"),
    "body_battery_intraday": ("ts", "level"),
    "workouts": ("start_time", "duration_s", "active_energy_kcal", "source"),
    # State of Mind straight from the raw archive until HealthLog parses it (upstream PR #111).
    "raw_ingest": ("id", "payload"),
}

# HealthLog's stress states that carry a score (upstream analysis/constants.py).
MEASURED_STRESS_STATES = ("rest", "low", "medium", "high")


@dataclass(frozen=True)
class ContractProblem:
    table: str
    column: str | None
    message: str

    def __str__(self) -> str:
        where = f"{self.table}.{self.column}" if self.column else self.table
        return f"{where}: {self.message}"


def check_upstream(db: Session) -> list[ContractProblem]:
    """Every contracted table must exist and be readable, with every contracted column."""
    rows = db.execute(
        sa.text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = ANY(:tables)"
        ),
        {"schema": UPSTREAM_SCHEMA, "tables": list(CONTRACT)},
    ).all()
    present: dict[str, set[str]] = {}
    for table, column in rows:
        present.setdefault(table, set()).add(column)

    problems: list[ContractProblem] = []
    for table, columns in CONTRACT.items():
        if table not in present:
            problems.append(ContractProblem(table, None, "table missing or not visible to this role"))
            continue
        readable = db.execute(
            sa.text("SELECT has_table_privilege(current_user, :qualified, 'SELECT')"),
            {"qualified": f"{UPSTREAM_SCHEMA}.{table}"},
        ).scalar_one()
        if not readable:
            problems.append(ContractProblem(table, None, "no SELECT privilege (re-run bootstrap.sql)"))
        for column in columns:
            if column not in present[table]:
                problems.append(ContractProblem(table, column, "column missing"))
    return problems


# --- daily reads -----------------------------------------------------------


@dataclass(frozen=True)
class SourceDay:
    """One metric's aggregate for one Companion day from one source."""

    day: dt.date
    source: str
    value: float
    n: int


def _params(zone: ZoneInfo, boundary: dt.time, first: dt.date, last: dt.date) -> dict:
    start, _ = day_bounds(first, zone, boundary)
    _, end = day_bounds(last, zone, boundary)
    return {"tz": zone.key, "boundary": boundary_interval(boundary), "start": start, "end": end}


def metric_by_source(
    db: Session, metric: str, agg: str, zone: ZoneInfo, boundary: dt.time, first: dt.date, last: dt.date
) -> list[SourceDay]:
    """Per-day, per-source aggregate of one metric (``agg`` is ``sum`` or ``avg``).

    Sources are kept apart so the caller can apply a source policy (R16)
    instead of summing overlapping streams.
    """
    if agg not in ("sum", "avg"):
        raise ValueError(f"unsupported aggregation {agg!r}")
    day = sql_day_expr("time")
    rows = db.execute(
        sa.text(
            f"SELECT {day} AS day, source, {agg}(coalesce(vavg, qty)) AS value, count(*) AS n "
            "FROM public.metric_samples "
            "WHERE metric = :metric AND time >= :start AND time < :end "
            "GROUP BY 1, 2"
        ),
        {"metric": metric, **_params(zone, boundary, first, last)},
    ).all()
    return [SourceDay(r.day, r.source or "", float(r.value), int(r.n)) for r in rows if r.value is not None]


def sleep_by_source(db: Session, zone: ZoneInfo, first: dt.date, last: dt.date) -> list[SourceDay]:
    """Hours asleep per wake date (local calendar date of ``sleep_end``) and source.

    Sleep is keyed by the morning you woke up, not by the day boundary: the
    night ending on the 17th is "last night" on the 17th.
    """
    rows = db.execute(
        sa.text(
            "SELECT (sleep_end AT TIME ZONE :tz)::date AS day, source, sum(total_sleep_h) AS value, count(*) AS n "
            "FROM public.sleep_sessions "
            "WHERE sleep_end IS NOT NULL AND total_sleep_h IS NOT NULL "
            "AND (sleep_end AT TIME ZONE :tz)::date BETWEEN :first AND :last "
            "GROUP BY 1, 2"
        ),
        {"tz": zone.key, "first": first, "last": last},
    ).all()
    return [SourceDay(r.day, r.source or "", float(r.value), int(r.n)) for r in rows]


def stress_daily(db: Session, zone: ZoneInfo, boundary: dt.time, first: dt.date, last: dt.date) -> list[SourceDay]:
    """Mean stress over measured minutes per Companion day (HealthLog's own days use midnight)."""
    day = sql_day_expr("ts")
    rows = db.execute(
        sa.text(
            f"SELECT {day} AS day, avg(stress) AS value, count(*) AS n "
            "FROM public.stress_intraday "
            "WHERE ts >= :start AND ts < :end AND state = ANY(:states) AND stress IS NOT NULL "
            "GROUP BY 1"
        ),
        {"states": list(MEASURED_STRESS_STATES), **_params(zone, boundary, first, last)},
    ).all()
    return [SourceDay(r.day, "", float(r.value), int(r.n)) for r in rows]


def energy_reserve_daily(
    db: Session, zone: ZoneInfo, boundary: dt.time, first: dt.date, last: dt.date
) -> dict[dt.date, tuple[int, int]]:
    """``(low, high)`` Body-Battery level per Companion day."""
    day = sql_day_expr("ts")
    rows = db.execute(
        sa.text(
            f"SELECT {day} AS day, min(level) AS low, max(level) AS high "
            "FROM public.body_battery_intraday WHERE ts >= :start AND ts < :end GROUP BY 1"
        ),
        _params(zone, boundary, first, last),
    ).all()
    return {r.day: (int(r.low), int(r.high)) for r in rows}


# --- bulk reads for the daily feature table (M2) ----------------------------


@dataclass(frozen=True)
class MetricDayRow:
    """Every aggregate of one metric for one Companion day from one source; the caller picks one."""

    day: dt.date
    metric: str
    source: str
    sum: float | None
    avg: float | None
    min: float | None
    max: float | None
    n: int


def registry(db: Session) -> list[dict]:
    rows = db.execute(
        sa.text("SELECT metric, display_name, unit_canonical, agg_default, category, tier FROM public.metric_registry")
    ).mappings()
    return [dict(r) for r in rows]


def metric_day_rows(db: Session, zone: ZoneInfo, boundary: dt.time, since: dt.date | None = None) -> list[MetricDayRow]:
    """All metrics, per Companion day and source, over the whole history (or from ``since``)."""
    day = sql_day_expr("time")
    params: dict = {"tz": zone.key, "boundary": boundary_interval(boundary)}
    where = ""
    if since is not None:
        params["start"] = day_bounds(since, zone, boundary)[0]
        where = "WHERE time >= :start"
    rows = db.execute(
        sa.text(
            f"SELECT {day} AS day, metric, source, sum(qty) AS s, avg(coalesce(vavg, qty)) AS a, "
            "min(coalesce(vmin, vavg, qty)) AS lo, max(coalesce(vmax, vavg, qty)) AS hi, count(*) AS n "
            f"FROM public.metric_samples {where} GROUP BY 1, 2, 3"
        ),
        params,
    ).all()
    return [MetricDayRow(r.day, r.metric, r.source or "", r.s, r.a, r.lo, r.hi, int(r.n)) for r in rows]


@dataclass(frozen=True)
class SleepDayRow:
    day: dt.date  # wake date
    source: str
    total_h: float
    deep_h: float | None
    core_h: float | None
    rem_h: float | None
    awake_h: float | None
    sessions: int


def sleep_day_rows(db: Session, zone: ZoneInfo) -> list[SleepDayRow]:
    rows = db.execute(
        sa.text(
            "SELECT (sleep_end AT TIME ZONE :tz)::date AS day, source, sum(total_sleep_h) AS total, "
            "sum(deep_h) AS deep, sum(core_h) AS core, sum(rem_h) AS rem, sum(awake_h) AS awake, count(*) AS n "
            "FROM public.sleep_sessions WHERE sleep_end IS NOT NULL AND total_sleep_h IS NOT NULL GROUP BY 1, 2"
        ),
        {"tz": zone.key},
    ).all()
    return [SleepDayRow(r.day, r.source or "", r.total, r.deep, r.core, r.rem, r.awake, int(r.n)) for r in rows]


def workout_day_rows(db: Session, zone: ZoneInfo, boundary: dt.time) -> list[SourceDay]:
    """Workout minutes per Companion day and source (``n`` = number of workouts)."""
    day = sql_day_expr("start_time")
    rows = db.execute(
        sa.text(
            f"SELECT {day} AS day, coalesce(source, '') AS source, sum(duration_s) / 60.0 AS value, count(*) AS n "
            "FROM public.workouts WHERE start_time IS NOT NULL AND duration_s IS NOT NULL GROUP BY 1, 2"
        ),
        {"tz": zone.key, "boundary": boundary_interval(boundary)},
    ).all()
    return [SourceDay(r.day, r.source, float(r.value), int(r.n)) for r in rows]


def stress_day_rows(db: Session, zone: ZoneInfo, boundary: dt.time) -> list[SourceDay]:
    day = sql_day_expr("ts")
    rows = db.execute(
        sa.text(
            f"SELECT {day} AS day, avg(stress) AS value, count(*) AS n FROM public.stress_intraday "
            "WHERE state = ANY(:states) AND stress IS NOT NULL GROUP BY 1"
        ),
        {"tz": zone.key, "boundary": boundary_interval(boundary), "states": list(MEASURED_STRESS_STATES)},
    ).all()
    return [SourceDay(r.day, "", float(r.value), int(r.n)) for r in rows]


def energy_day_rows(db: Session, zone: ZoneInfo, boundary: dt.time) -> dict[dt.date, tuple[int, int]]:
    day = sql_day_expr("ts")
    rows = db.execute(
        sa.text(
            f"SELECT {day} AS day, min(level) AS low, max(level) AS high FROM public.body_battery_intraday GROUP BY 1"
        ),
        {"tz": zone.key, "boundary": boundary_interval(boundary)},
    ).all()
    return {r.day: (int(r.low), int(r.high)) for r in rows}


def raw_state_of_mind_since(db: Session, cursor: int, limit: int = 200) -> list[tuple[int, list]]:
    """``(raw_ingest id, stateOfMind entries)`` for archived payloads after ``cursor``, oldest first."""
    rows = db.execute(
        sa.text(
            "SELECT id, payload->'data'->'stateOfMind' AS entries FROM public.raw_ingest "
            "WHERE id > :cursor AND jsonb_typeof(payload->'data'->'stateOfMind') = 'array' "
            "ORDER BY id LIMIT :limit"
        ),
        {"cursor": cursor, "limit": limit},
    ).all()
    return [(int(r.id), r.entries) for r in rows]


def max_raw_ingest_id(db: Session) -> int:
    return int(db.execute(sa.text("SELECT coalesce(max(id), 0) FROM public.raw_ingest")).scalar_one())


def metric_sources(db: Session, metric: str) -> list[tuple[str, int]]:
    """``(source, samples)`` for one metric, most samples first (for the source-priority setting)."""
    rows = db.execute(
        sa.text(
            "SELECT source, count(*) AS n FROM public.metric_samples WHERE metric = :metric "
            "GROUP BY source ORDER BY n DESC"
        ),
        {"metric": metric},
    ).all()
    return [(r.source or "", int(r.n)) for r in rows]
