"""The ``companion-jobs`` process: scheduled work, separate from the web process.

- 04:10 local: the read-contract check.
- 04:15 local, after HealthLog's 03:30 analysis and before its 04:30 backup:
  ``refresh`` (seed metric settings, copy new State of Mind entries, load
  the collector's weather file, rebuild the daily feature table, run the
  insight engine).
- every 15 minutes: the same refresh, but only when HealthLog has received a payload since the last one
  (``refresh_if_new``). Health Auto Export can deliver a whole day late, after the 04:15 run; without this
  the day stays empty until the next night.
- every minute, when reminders are on: seal the reminders that are due for the courier, and read its reports
  (``app/reminders.py``).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import sqlalchemy as sa
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from . import features, metric_settings, mood, outside, reminders, upstream
from .analysis import run as analysis
from .config import get_settings
from .db import session_scope
from .models import Setting
from .timeutil import current_day

log = logging.getLogger("companion.jobs")

# One refresh at a time: the jobs process refreshes on start, a deploy refreshes to verify, and "Rebuild now"
# can be pressed at any moment. Each rebuilds the feature table, so two at once collide on its key.
REFRESH_LOCK = 0x636F6D70  # "comp"

# The newest HealthLog payload id a refresh has started from; ``refresh_if_new`` compares against it.
SEEN_KEY = "refresh_seen_payload"
NEW_DATA_MINUTES = 15


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
    # Taken before the work: a payload that lands while we run is newer and triggers the next check.
    _mark_seen(db, upstream.max_raw_ingest_id(db))
    seeded = metric_settings.seed(db)
    synced = mood.sync_from_raw(db)
    weather = outside.load_weather(db, settings.outside_dir)
    rebuilt = features.rebuild(db, settings.zone, settings.day_boundary, settings.latitude, settings.holiday_country)
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


def _mark_seen(db: Session, payload_id: int) -> None:
    setting = db.get(Setting, SEEN_KEY)
    if setting is None:
        db.add(Setting(key=SEEN_KEY, value={"payload_id": payload_id}))
    else:
        setting.value = {"payload_id": payload_id}


def refresh_if_new(db: Session) -> RefreshResult | None:
    """Refresh when HealthLog has received a payload since the last refresh started; else ``None`` (caller commits)."""
    db.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": REFRESH_LOCK})
    setting = db.get(Setting, SEEN_KEY)
    seen = int(setting.value.get("payload_id", 0)) if setting else 0
    newest = upstream.max_raw_ingest_id(db)
    if newest <= seen:
        return None
    log.info("new HealthLog data (payload %d > %d): refreshing", newest, seen)
    return refresh(db)


def new_data_refresh() -> None:
    try:
        with session_scope() as db:
            refresh_if_new(db)
    except Exception:
        log.exception("refresh on new data failed")


def nightly_refresh() -> None:
    with session_scope() as db:
        refresh(db)


def reminder_tick() -> None:
    settings = get_settings()
    try:
        with session_scope() as db:
            reminders.apply_results(db, settings)
            reminders.run_due(db, settings, dt.datetime.now(dt.UTC))
    except Exception:
        log.exception("reminders: tick failed")


def run() -> int:
    settings = get_settings()
    scheduler = BlockingScheduler(timezone=settings.zone)
    scheduler.add_job(contract_check, CronTrigger(hour=4, minute=10, timezone=settings.zone), id="contract_check")
    scheduler.add_job(nightly_refresh, CronTrigger(hour=4, minute=15, timezone=settings.zone), id="refresh")
    scheduler.add_job(
        new_data_refresh, IntervalTrigger(minutes=NEW_DATA_MINUTES), id="refresh_on_new_data", max_instances=1
    )
    if settings.push_on:
        scheduler.add_job(reminder_tick, IntervalTrigger(minutes=1), id="reminders")
        log.info("reminders on (outbox %s)", settings.push_dir)
    log.info("jobs scheduler started (TZ=%s)", settings.tz)
    if contract_check() == 0:
        nightly_refresh()  # so a fresh install has features without waiting for the night
    scheduler.start()
    return 0
