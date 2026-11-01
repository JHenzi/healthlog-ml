"""Bring day-by-day history in from another tracking app (plan M10). Repeatable, so both apps can run side by side.

The input is one JSON document, produced outside this repository (R4)::

    {"source": "otherapp",
     "tags": {"Tag name": {"2026-01-02": 1, "2026-01-03": 0}},
     "trackers": [{"key": "...", "name": "...", "type": "scale", "scale_min": 1, "scale_max": 9, "unit": null,
                   "days": {"2026-01-02": 5}}],
     "diary": {"2026-01-02": "text"},
     "replace": true}

- Values come in exactly as given. A tag's 0 is stored as an entry, so a tag's series starts where the other app's
  did and no day is marked reviewed (R7). ``time`` values are minutes after midnight, so they keep their clock time;
  everything else sits at local noon.
- Each day has a stable entry id, so a repeat adds only new days. An entry you changed or removed here stays as it is.
- Logging in both apps: a day that already has an entry made here keeps it, and the import skips that day.
- ``replace`` makes ``tags`` the day's whole tag list and archives every other tracker. Both keep their history.

Reports counts only: diary text is never printed or logged (R11).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import Counter
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.orm import Session

from . import capture, dayrating
from .auth import now_utc
from .models import Observation, Tracker
from .timeutil import current_day, local_day
from .trackers import DAY_TAGS_KEY, DIARY_KEY, TrackerInputError, tag_slug

NAMESPACE = uuid.UUID("8f4a3c1e-3f0b-5a61-9d27-6c1b0e7a2d44")
NOON = dt.time(12, 0)
KEPT = (DAY_TAGS_KEY, DIARY_KEY)


def entry_id(source: str, tracker: str, tag: str, day: dt.date) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{source}|{tracker}|{tag}|{day.isoformat()}")


def _at(day: dt.date, zone: ZoneInfo, clock: dt.time = NOON) -> dt.datetime:
    return dt.datetime.combine(day, clock, zone)


def _logged_here(db: Session, tracker: Tracker, day: dt.date, tag: str | None, source: str) -> bool:
    tag_match = Observation.tag.is_(None) if tag is None else Observation.tag == tag
    query = sa.select(Observation.client_id).where(
        Observation.tracker_id == tracker.id,
        Observation.day == day,
        tag_match,
        Observation.deleted.is_(False),
        Observation.source != source,
    )
    return db.execute(query.limit(1)).first() is not None


def _days(raw: dict, today: dt.date):
    """Complete days with a value, oldest first: today is still being logged."""
    for text in sorted(raw):
        value, day = raw[text], dt.date.fromisoformat(text)
        if value is not None and day < today:
            yield day, value


def _import_tags(db, data, source, zone, boundary, today, counts) -> None:
    names = list(data.get("tags", {}))
    if not names:
        return
    tracker = capture.add_day_tags(db, names)
    if data.get("replace"):
        capture.update_tracker(db, tracker, tags=names)
    for name, raw in data["tags"].items():
        slug = tag_slug(name)
        for day, value in _days(raw, today):
            cid = entry_id(source, DAY_TAGS_KEY, slug, day)
            if db.get(Observation, cid) is not None:
                counts["already here"] += 1
            elif _logged_here(db, tracker, day, slug, source):
                counts["kept yours"] += 1
            else:
                how = {"observed_at": _at(day, zone), "client_id": cid, "source": source}
                capture.record_tag(db, tracker, name, bool(value), **how, zone=zone, boundary=boundary)
                counts["tags"] += 1


def _tracker(db: Session, spec: dict) -> Tracker:
    fields = {k: v for k, v in spec.items() if k != "days"}
    tracker = db.execute(sa.select(Tracker).where(Tracker.key == spec["key"])).scalar_one_or_none()
    if tracker is None:
        return capture.create_tracker(db, in_review=True, **fields)
    if tracker.type != spec["type"]:
        raise TrackerInputError(f"{spec['key']} is already a {tracker.type} tracker")
    return capture.update_tracker(db, tracker, archived=False)


def _log_days(db, tracker, raw, source, zone, boundary, today, counts, counter) -> None:
    for day, value in _days(raw, today):
        cid = entry_id(source, tracker.key, "", day)
        if db.get(Observation, cid) is not None:
            counts["already here"] += 1
        elif _logged_here(db, tracker, day, None, source):
            counts["kept yours"] += 1
        else:
            at, raw_value = _at(day, zone), value
            if tracker.type == "time":
                at, raw_value = _at(day, zone, dt.time(int(value) // 60, int(value) % 60)), None
            if local_day(at, zone, boundary) != day:
                raise TrackerInputError(f"{tracker.key}: an entry on {day} falls on another day")
            capture.log(
                db, tracker, raw_value, observed_at=at, client_id=cid, source=source, zone=zone, boundary=boundary
            )
            counts[counter] += 1


def run(db: Session, data: dict, zone: ZoneInfo, boundary: dt.time) -> Counter:
    """Apply the document (the caller commits, or rolls back for a dry run). Returns what happened, as counts."""
    source = f"import:{data['source']}"
    today = current_day(now_utc(), zone, boundary)
    counts: Counter = Counter()
    _import_tags(db, data, source, zone, boundary, today, counts)
    imported = set()
    for spec in data.get("trackers", ()):
        tracker = _tracker(db, spec)
        imported.add(tracker.key)
        _log_days(db, tracker, spec["days"], source, zone, boundary, today, counts, "entries")
    if data.get("diary"):
        _log_days(db, capture.diary(db), data["diary"], source, zone, boundary, today, counts, "diary entries")
    if data.get("replace"):
        for tracker in db.execute(sa.select(Tracker)).scalars():
            keep = tracker.key in imported or tracker.key in KEPT or dayrating.is_built_in(tracker.key)
            if not keep and not tracker.archived:
                capture.update_tracker(db, tracker, archived=True)
                counts["trackers archived"] += 1
    return counts
