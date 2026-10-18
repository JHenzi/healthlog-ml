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
from collections.abc import Iterable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .timeutil import boundary_interval, day_bounds, sql_day_expr

UPSTREAM_SCHEMA = "public"

CONTRACT: dict[str, tuple[str, ...]] = {
    "metric_samples": ("time", "metric", "source", "qty", "vavg"),
    "metric_registry": ("metric", "display_name", "unit_canonical", "agg_default", "tier"),
    "sleep_sessions": ("sleep_start", "sleep_end", "source", "total_sleep_h"),
    "stress_intraday": ("ts", "stress", "state"),
    "body_battery_intraday": ("ts", "level"),
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


def contract_tables() -> Iterable[str]:
    return CONTRACT.keys()
