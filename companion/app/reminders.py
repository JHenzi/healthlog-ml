"""Reminders: a nudge at 10:00 to look back on yesterday, at 11:00 with what's worth noticing (only when something
new clears the bar, app/signals.py), at 13:00 to log your mood in Apple Health, and at 19:00 to rate today (all
times are settings).

Every minute the jobs process checks whether a reminder is due: its time has passed today, it hasn't gone out
today, and it's at most ``LATE_LIMIT`` late (after downtime a 10:00 reminder isn't sent at 15:00). A reminder
whose question is already answered is skipped. Each one is sealed per subscribed device and left in the outbox
for the courier (``app/push.py``). ``schedule`` and ``due`` are pure.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from . import capture, dayrating, push, signals
from .auth import now_utc
from .config import Settings
from .models import PushSubscription, Setting, StateOfMindEntry, Tracker
from .timeutil import current_day, day_bounds

log = logging.getLogger("companion.reminders")

SETTINGS_KEY = "reminders"
SENT_KEY = "reminders_sent"
LATE_LIMIT = dt.timedelta(hours=2)


@dataclass(frozen=True)
class Kind:
    key: str
    label: str
    default: dt.time
    title: str
    body: str
    url: str = "/"


KINDS = (
    Kind("morning", "Morning", dt.time(10, 0), "Looking back", "How was yesterday, now that you've slept on it?"),
    Kind(
        "signals",
        "Worth noticing",
        dt.time(11, 0),
        "Worth noticing",
        "Sent only when something has clearly changed, at most twice a week.",
        "/#noticing",
    ),
    Kind(
        "mood",
        "Mood",
        dt.time(13, 0),
        "How are you feeling?",
        "Log it as a State of Mind in Apple Health, or in Mindfulness on your Watch.",
        "/mood",
    ),
    Kind("evening", "Evening", dt.time(19, 0), "How was today?", "Rate your day, and log anything else from today."),
)
BY_KEY = {k.key: k for k in KINDS}


def schedule(stored: dict | None) -> dict[str, dt.time | None]:
    """Each reminder's time, or None when it's off. Unset means the default."""
    stored = stored or {}
    out: dict[str, dt.time | None] = {}
    for kind in KINDS:
        value = stored.get(kind.key, kind.default.isoformat(timespec="minutes"))
        out[kind.key] = dt.time.fromisoformat(value) if value else None
    return out


def due(now_local: dt.datetime, times: dict[str, dt.time | None], sent: dict[str, str]) -> list[str]:
    """The reminders to send now: past their time today, not sent today, and not more than LATE_LIMIT late."""
    today = now_local.date()
    out = []
    for key, at in times.items():
        if at is None or sent.get(key) == today.isoformat():
            continue
        when = dt.datetime.combine(today, at, tzinfo=now_local.tzinfo)
        if when <= now_local < when + LATE_LIMIT:
            out.append(key)
    return out


# --- DB side --------------------------------------------------------------------


def load_schedule(db: Session) -> dict[str, dt.time | None]:
    row = db.get(Setting, SETTINGS_KEY)
    return schedule(row.value if row else None)


def save_schedule(db: Session, times: dict[str, dt.time | None]) -> None:
    value = {k: (t.isoformat(timespec="minutes") if t else "") for k, t in times.items()}
    row = db.get(Setting, SETTINGS_KEY)
    if row is None:
        db.add(Setting(key=SETTINGS_KEY, value=value))
    else:
        row.value = value
        row.updated_at = now_utc()


def _answered(db: Session, key: str, day: dt.date) -> bool:
    tracker = db.execute(sa.select(Tracker).where(Tracker.key == key)).scalar_one_or_none()
    return tracker is not None and bool(capture.day_values(db, tracker, day))


def mood_logged(db: Session, settings: Settings, today: dt.date) -> bool:
    """A State of Mind for today has reached the Companion (it comes through Health Auto Export, so maybe late)."""
    start, end = day_bounds(today, settings.zone, settings.day_boundary)
    found = db.execute(
        sa.select(StateOfMindEntry.hae_id)
        .where(StateOfMindEntry.start_time >= start, StateOfMindEntry.start_time < end)
        .limit(1)
    ).first()
    return found is not None


def already_answered(db: Session, kind: str, today: dt.date, settings: Settings | None = None) -> bool:
    """Morning: yesterday's look back. Mood: a State of Mind today. Evening: today's rating."""
    if kind == "morning":
        return _answered(db, dayrating.LOOKBACK_KEY, today - dt.timedelta(days=1))
    if kind == "mood":
        return settings is not None and mood_logged(db, settings, today)
    return _answered(db, dayrating.EVENING_KEY, today)


def subscriptions(db: Session) -> list[PushSubscription]:
    return list(db.execute(sa.select(PushSubscription).order_by(PushSubscription.id)).scalars())


def send(db: Session, settings: Settings, title: str, body: str, url: str = "/") -> int:
    """Seal one message for every subscribed device and leave it in the outbox. Returns how many."""
    if not settings.push_on:
        return 0
    now = now_utc()
    count = 0
    for row in subscriptions(db):
        sub = push.Subscription(row.endpoint, row.p256dh, row.auth)
        if not push.valid_subscription(sub):
            continue
        entry = push.seal(
            {"title": title, "body": body, "url": url},
            sub,
            settings.vapid_public_key,
            settings.vapid_private_key,
            settings.vapid_subject,
            now,
        )
        push.write_outbox(settings.push_dir, entry)
        row.last_sent_at = now
        count += 1
    return count


def run_due(db: Session, settings: Settings, now: dt.datetime) -> list[str]:
    """Send whatever is due now (caller commits). Returns the reminders handled."""
    if not settings.push_on:
        return []
    local = now.astimezone(settings.zone)
    row = db.get(Setting, SENT_KEY)
    sent = dict(row.value) if row else {}
    handled = due(local, load_schedule(db), sent)
    today = current_day(now, settings.zone, settings.day_boundary)
    for key in handled:
        kind = BY_KEY[key]
        if key == "signals":
            body = signals.push_body(db, today)
            if body is None:
                log.info("reminder signals: nothing new worth noticing, skipped")
            else:
                sealed = send(db, settings, kind.title, body, kind.url)
                log.info("reminder signals: sealed for %d device(s)", sealed)
        elif already_answered(db, key, today, settings):
            log.info("reminder %s: already answered, skipped", key)
        else:
            sealed = send(db, settings, kind.title, kind.body, kind.url)
            log.info("reminder %s: sealed for %d device(s)", key, sealed)
        sent[key] = local.date().isoformat()
    if handled:
        if row is None:
            db.add(Setting(key=SENT_KEY, value=sent))
        else:
            row.value = sent
            row.updated_at = now_utc()
    return handled


def apply_results(db: Session, settings: Settings) -> int:
    """Read the courier's reports: forget devices the push service says are gone. Returns how many reports."""
    results = push.take_results(settings.push_dir)
    for r in results:
        row = db.execute(
            sa.select(PushSubscription).where(PushSubscription.endpoint == r.endpoint)
        ).scalar_one_or_none()
        if row is None:
            continue
        if push.gone(r.status):
            log.info("push: a device unsubscribed (status %d), removed", r.status)
            db.delete(row)
        else:
            row.last_status = r.status
    return len(results)
