"""The ``companion-jobs`` process: scheduled work, separate from the web process.

- 04:10 local: the read-contract check.
- 04:15 local, after HealthLog's 03:30 analysis and before its 04:30 backup:
  ``refresh`` (seed metric settings, copy new State of Mind entries, load
  the collector's weather file, rebuild the daily feature table, run the
  insight engine).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import sqlalchemy as sa
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from . import features, metric_settings, mood, outside, upstream
from .analysis import run as analysis
from .config import get_settings
from .db import session_scope
from .timeutil import current_day

log = logging.getLogger("companion.jobs")

# One refresh at a time: the jobs process refreshes on start, a deploy refreshes to verify, and "Rebuild now"
# can be pressed at any moment. Each rebuilds the feature table, so two at once collide on its key.
REFRESH_LOCK = 0x636F6D70  # "comp"


def contract_check() -> int:
    """Returns the number of contract problems (logged)."""
    with session_scope() as db:
        problems = upstream.check_upstream(db)
    for problem in problems:
        log.warning("upstream contract: %s", problem)
    log.info("nightly contract check: %d problem(s)", len(problems))
    return len(problems)


@dataclass(frozen=True)
class RefreshResult:
    seeded: metric_settings.SeedResult
    mood: mood.SyncResult
    weather: outside.LoadResult
    features: features.RebuildResult
    insights: analysis.RunResult


def refresh(db: Session) -> RefreshResult:
    """Everything that turns HealthLog's data into our daily features (caller commits).

    Waits for any refresh already running (a transaction-level advisory lock, released at commit or rollback).
    """
    db.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": REFRESH_LOCK})
    settings = get_settings()
    seeded = metric_settings.seed(db)
    synced = mood.sync_from_raw(db)
    weather = outside.load_weather(db, settings.outside_dir)
    rebuilt = features.rebuild(db, settings.zone, settings.day_boundary)
    found = analysis.run(db, current_day(dt.datetime.now(dt.UTC), settings.zone, settings.day_boundary))
    log.info(
        "refresh: %d new metric settings, %d mood entries from %d payloads, weather %s (%d hours), "
        "%d features / %d rows, %d insights",
        seeded.added,
        synced.entries,
        synced.payloads,
        weather.status,
        weather.hours,
        rebuilt.features,
        rebuilt.rows,
        found.insights,
    )
    return RefreshResult(seeded, synced, weather, rebuilt, found)


def nightly_refresh() -> None:
    with session_scope() as db:
        refresh(db)


def run() -> int:
    settings = get_settings()
    scheduler = BlockingScheduler(timezone=settings.zone)
    scheduler.add_job(contract_check, CronTrigger(hour=4, minute=10, timezone=settings.zone), id="contract_check")
    scheduler.add_job(nightly_refresh, CronTrigger(hour=4, minute=15, timezone=settings.zone), id="refresh")
    log.info("jobs scheduler started (TZ=%s)", settings.tz)
    if contract_check() == 0:
        nightly_refresh()  # so a fresh install has features without waiting for the night
    scheduler.start()
    return 0
