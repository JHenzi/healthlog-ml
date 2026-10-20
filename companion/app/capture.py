"""Capture: tracker definitions and the event log (design §5, §7).

Every change is first appended to ``events`` (the source of truth), then
applied to the derived tables (``observations``, ``day_reviews``).
``rebuild`` replays the whole log, so derived state can always be recreated,
and a test checks that replaying gives the same state as the incremental path
(risks.md B10). Logging is idempotent on the client id, so a retried Shortcut
or an offline queue never doubles an entry (B7). Deletes are tombstones.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .auth import now_utc
from .models import DayReview, Event, Observation, Tracker
from .timeutil import local_day
from .trackers import (
    DAY_TAGS_KEY,
    TrackerInputError,
    TrackerSpec,
    check_time,
    parse_tag,
    parse_value,
    tag_slug,
    validate_definition,
)

LOCKED_FIELDS = ("type", "unit", "scale_min", "scale_max", "options")


class LockedError(Exception):
    """A locked field of a tracker with data was changed; create a new version instead (R12)."""


def spec_of(t: Tracker) -> TrackerSpec:
    return TrackerSpec(
        key=t.key,
        name=t.name,
        type=t.type,
        unit=t.unit,
        scale_min=t.scale_min,
        scale_max=t.scale_max,
        options=tuple(t.options or ()),
        always_logged=t.always_logged,
        tags=tuple(t.tags or ()),
        archived=bool(t.archived),
    )


# --- tracker definitions ---------------------------------------------------


def create_tracker(db: Session, **fields) -> Tracker:
    tracker = Tracker(**fields)
    validate_definition(spec_of(tracker))
    if db.execute(sa.select(Tracker.id).where(Tracker.key == tracker.key)).first():
        raise TrackerInputError(f"a tracker with the key {tracker.key!r} already exists")
    db.add(tracker)
    db.flush()
    return tracker


def has_data(db: Session, tracker: Tracker) -> bool:
    return (
        db.execute(sa.select(Observation.client_id).where(Observation.tracker_id == tracker.id).limit(1)).first()
        is not None
    )


def update_tracker(db: Session, tracker: Tracker, **fields) -> Tracker:
    """Free fields change freely; type, unit, scale and options are locked once data exists."""
    if has_data(db, tracker):
        changed = [k for k in LOCKED_FIELDS if k in fields and fields[k] != getattr(tracker, k)]
        if changed:
            raise LockedError(
                f"{', '.join(changed)} can't change once the tracker has data; create a new version instead"
            )
    for key, value in fields.items():
        setattr(tracker, key, value)
    validate_definition(spec_of(tracker))
    tracker.updated_at = now_utc()
    return tracker


def day_tags(db: Session) -> Tracker | None:
    """The tracker that holds the day's tags (created with the first tag)."""
    return db.execute(sa.select(Tracker).where(Tracker.key == DAY_TAGS_KEY)).scalar_one_or_none()


def add_day_tags(db: Session, names: list[str]) -> Tracker:
    """Add tags to the day's list; ones already there are skipped. Tags describe the day, not a measure."""
    tracker = day_tags(db)
    if tracker is None:
        tracker = create_tracker(db, key=DAY_TAGS_KEY, name="Day", type="tags", tags=[], in_review=True, pinned=True)
    have = {tag_slug(t) for t in tracker.tags or ()}
    new = [n for n in names if tag_slug(n) not in have]
    return update_tracker(db, tracker, tags=[*(tracker.tags or ()), *new], archived=False)


def remove_day_tag(db: Session, name: str) -> None:
    """Take a tag off the list. Its past entries stay in the event log."""
    tracker = day_tags(db)
    if tracker is not None:
        update_tracker(db, tracker, tags=[t for t in tracker.tags or () if tag_slug(t) != tag_slug(name)])


def new_version(db: Session, tracker: Tracker, **changes) -> Tracker:
    """Archive ``tracker`` and create its successor with ``changes`` (history stays with the old one)."""
    n = 2
    while db.execute(sa.select(Tracker.id).where(Tracker.key == f"{tracker.key}_v{n}")).first():
        n += 1
    base = {
        c: getattr(tracker, c)
        for c in (
            "name",
            "type",
            "unit",
            "scale_min",
            "scale_max",
            "scale_labels",
            "options",
            "tags",
            "polarity",
            "category",
            "in_review",
            "always_logged",
            "pinned",
        )
    }
    successor = create_tracker(db, **{**base, **changes, "key": f"{tracker.key}_v{n}"})
    tracker.archived = True
    tracker.successor_id = successor.id
    tracker.updated_at = now_utc()
    return successor


# --- the event log ---------------------------------------------------------


def _append(db: Session, op: str, client_id: uuid.UUID, payload: dict, source: str) -> Event:
    event = Event(client_id=client_id, op=op, payload=payload, source=source)
    db.add(event)
    db.flush()
    return event


def _trackers_by_key(db: Session) -> dict[str, Tracker]:
    return {t.key: t for t in db.execute(sa.select(Tracker)).scalars()}


def apply(db: Session, event: Event, trackers: dict[str, Tracker], zone: ZoneInfo, boundary: dt.time) -> None:
    """Apply one event to the derived tables. Deterministic, so replaying the log rebuilds them."""
    p = event.payload
    if event.op in ("log", "edit"):
        observed_at = dt.datetime.fromisoformat(p["observed_at"])
        tracker = trackers[p["tracker"]]
        row = db.get(Observation, event.client_id)
        values = {
            "tracker_id": tracker.id,
            "observed_at": observed_at,
            "day": local_day(observed_at, zone, boundary),
            "value_num": p.get("value_num"),
            "value_text": p.get("value_text"),
            "tag": p.get("tag"),
            "updated_seq": event.seq,
        }
        if row is None:
            if event.op == "log":
                db.add(Observation(client_id=event.client_id, source=event.source, deleted=False, **values))
        elif not row.deleted:
            for k, v in values.items():
                setattr(row, k, v)
    elif event.op == "delete":
        row = db.get(Observation, event.client_id)
        if row is not None:
            row.deleted = True
            row.updated_seq = event.seq
    elif event.op == "review":
        day = dt.date.fromisoformat(p["day"])
        row = db.get(DayReview, day)
        if row is None:
            db.add(DayReview(day=day, completed_at=event.received_at or now_utc()))
    elif event.op == "unreview":
        db.execute(sa.delete(DayReview).where(DayReview.day == dt.date.fromisoformat(p["day"])))
    db.flush()


def rebuild(db: Session, zone: ZoneInfo, boundary: dt.time) -> int:
    """Recreate observations and reviews from the event log; returns the number of events replayed."""
    db.execute(sa.delete(Observation))
    db.execute(sa.delete(DayReview))
    trackers = _trackers_by_key(db)
    count = 0
    for event in db.execute(sa.select(Event).order_by(Event.seq)).scalars():
        apply(db, event, trackers, zone, boundary)
        count += 1
    return count


@dataclass(frozen=True)
class Logged:
    observation: Observation
    tracker: Tracker
    created: bool  # False when the client id was already logged (idempotent retry)


def log(
    db: Session,
    tracker: Tracker,
    raw_value: object,
    *,
    observed_at: dt.datetime | None,
    client_id: uuid.UUID | None,
    source: str,
    zone: ZoneInfo,
    boundary: dt.time,
) -> Logged:
    """Validate and record one entry. The same ``client_id`` twice returns the first entry unchanged."""
    if tracker.archived:
        raise TrackerInputError("this tracker is archived")
    client_id = client_id or uuid.uuid4()
    existing = db.get(Observation, client_id)
    if existing is not None:
        return Logged(existing, tracker, created=False)
    now = now_utc()
    when = observed_at or now
    check_time(when, now)
    value_num, value_text = parse_value(spec_of(tracker), raw_value)
    payload = {
        "tracker": tracker.key,
        "observed_at": when.isoformat(),
        "value_num": value_num,
        "value_text": value_text,
    }
    event = _append(db, "log", client_id, payload, source)
    apply(db, event, {tracker.key: tracker}, zone, boundary)
    return Logged(db.get(Observation, client_id), tracker, created=True)


SINGLE_VALUE_TYPES = ("scale", "check", "choice")  # one value per day: a new tap replaces it


def day_values(db: Session, tracker: Tracker, day: dt.date) -> list[Observation]:
    """The tracker's live entries on ``day`` (tags excluded), oldest first."""
    return list(
        db.execute(
            sa.select(Observation)
            .where(
                Observation.tracker_id == tracker.id,
                Observation.day == day,
                Observation.tag.is_(None),
                Observation.deleted.is_(False),
            )
            .order_by(Observation.observed_at)
        ).scalars()
    )


def set_day_value(
    db: Session,
    tracker: Tracker,
    raw_value: object,
    day: dt.date,
    *,
    observed_at: dt.datetime | None,
    client_id: uuid.UUID | None,
    source: str,
    zone: ZoneInfo,
    boundary: dt.time,
) -> bool:
    """A rating, yes/no or pick-one has one value a day: a new tap replaces it, the same tap clears it.

    The replaced entries are tombstoned in the event log, so the history is kept. Returns whether a value is set.
    """
    if client_id is not None and db.get(Observation, client_id) is not None:
        return True  # a double tap
    value_num, value_text = parse_value(spec_of(tracker), raw_value)
    current = day_values(db, tracker, day)
    same = len(current) == 1 and (current[0].value_num, current[0].value_text) == (value_num, value_text)
    for o in current:
        delete(db, o.client_id, source=source)
    if same:
        return False
    logged = log(
        db,
        tracker,
        raw_value,
        observed_at=observed_at,
        client_id=client_id,
        source=source,
        zone=zone,
        boundary=boundary,
    )
    if logged.observation.day != day:
        raise TrackerInputError("the time isn't on that day")
    return True


def undo_last(db: Session, tracker: Tracker, day: dt.date, *, source: str) -> bool:
    """Take back the day's latest entry (the minus button). It stays in the event log as a tombstone."""
    current = day_values(db, tracker, day)
    return bool(current) and delete(db, current[-1].client_id, source=source)


def toggle_tag(
    db: Session,
    tracker: Tracker,
    tag: str,
    day: dt.date,
    *,
    observed_at: dt.datetime | None,
    source: str,
    zone: ZoneInfo,
    boundary: dt.time,
) -> bool:
    """Pick a tag for ``day``, or unpick it if it's already picked. Returns whether it's now picked."""
    if tracker.archived:
        raise TrackerInputError("this tracker is archived")
    slug = parse_tag(spec_of(tracker), tag)
    picked = (
        db.execute(
            sa.select(Observation.client_id).where(
                Observation.tracker_id == tracker.id,
                Observation.day == day,
                Observation.tag == slug,
                Observation.deleted.is_(False),
            )
        )
        .scalars()
        .all()
    )
    if picked:
        for client_id in picked:
            delete(db, client_id, source=source)
        return False
    now = now_utc()
    when = observed_at or now
    check_time(when, now)
    if local_day(when, zone, boundary) != day:
        raise TrackerInputError("the time isn't on that day")
    client_id = uuid.uuid4()
    payload = {"tracker": tracker.key, "observed_at": when.isoformat(), "value_num": None, "value_text": None}
    event = _append(db, "log", client_id, payload | {"tag": slug}, source)
    apply(db, event, {tracker.key: tracker}, zone, boundary)
    return True


def tags_for_day(db: Session, day: dt.date) -> dict[int, set[str]]:
    """Tracker id → the tag slugs picked on ``day``."""
    out: dict[int, set[str]] = {}
    rows = db.execute(
        sa.select(Observation.tracker_id, Observation.tag).where(
            Observation.day == day, Observation.tag.is_not(None), Observation.deleted.is_(False)
        )
    )
    for tracker_id, tag in rows:
        out.setdefault(tracker_id, set()).add(tag)
    return out


def edit(
    db: Session,
    client_id: uuid.UUID,
    raw_value: object,
    *,
    observed_at: dt.datetime | None,
    source: str,
    zone: ZoneInfo,
    boundary: dt.time,
) -> Observation:
    row = db.get(Observation, client_id)
    if row is None or row.deleted:
        raise KeyError(client_id)
    if row.tag is not None:
        raise TrackerInputError("a tag has no value to edit; unpick it instead")
    tracker = db.get(Tracker, row.tracker_id)
    when = observed_at or row.observed_at
    check_time(when, now_utc())
    value_num, value_text = parse_value(spec_of(tracker), raw_value)
    payload = {
        "tracker": tracker.key,
        "observed_at": when.isoformat(),
        "value_num": value_num,
        "value_text": value_text,
    }
    apply(db, _append(db, "edit", client_id, payload, source), {tracker.key: tracker}, zone, boundary)
    return row


def delete(db: Session, client_id: uuid.UUID, *, source: str) -> bool:
    row = db.get(Observation, client_id)
    if row is None or row.deleted:
        return False
    event = _append(db, "delete", client_id, {}, source)
    apply(db, event, {}, ZoneInfo("UTC"), dt.time(0))
    return True


def set_reviewed(db: Session, day: dt.date, reviewed: bool, *, source: str) -> None:
    op = "review" if reviewed else "unreview"
    # A review is about a day, not an observation: a stable id per day keeps the log readable.
    client_id = uuid.uuid5(uuid.NAMESPACE_URL, f"companion:review:{day.isoformat()}")
    event = _append(db, op, client_id, {"day": day.isoformat()}, source)
    apply(db, event, {}, ZoneInfo("UTC"), dt.time(0))


def entries_for_day(db: Session, day: dt.date) -> list[tuple[Observation, Tracker]]:
    rows = db.execute(
        sa.select(Observation, Tracker)
        .join(Tracker, Tracker.id == Observation.tracker_id)
        .where(Observation.day == day, Observation.deleted.is_(False))
        .order_by(Observation.observed_at)
    ).all()
    return [(o, t) for o, t in rows]


def is_reviewed(db: Session, day: dt.date) -> bool:
    return db.get(DayReview, day) is not None
