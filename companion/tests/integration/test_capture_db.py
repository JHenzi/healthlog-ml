"""The event log against the database: idempotency (B7), tombstones, locking (B9), rebuild (B10)."""

from __future__ import annotations

import datetime as dt
import random
import uuid
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app import capture, features
from app.models import DayReview, Event, Observation
from app.timeutil import local_day
from app.trackers import TrackerInputError

NY = ZoneInfo("America/New_York")
FOUR = dt.time(4, 0)


@pytest.fixture
def coffee(db):
    return capture.create_tracker(db, key="coffee", name="Coffee", type="count", unit="cups")


@pytest.fixture
def mood_scale(db):
    return capture.create_tracker(
        db,
        key="energy_level",
        name="Energy level",
        type="scale",
        scale_min=1,
        scale_max=5,
        tags=["Slept badly", "travel"],
    )


def _log(db, tracker, value=None, *, when=None, cid=None):
    return capture.log(db, tracker, value, observed_at=when, client_id=cid, source="test", zone=NY, boundary=FOUR)


def _state(db) -> tuple:
    """What the database holds (not the session's in-memory objects), with instants compared in UTC."""
    db.flush()
    db.expire_all()
    obs = sorted(
        (
            str(o.client_id),
            o.tracker_id,
            o.observed_at.astimezone(dt.UTC).isoformat(),
            o.day,
            o.value_num,
            o.value_text,
            o.tag,
            o.deleted,
        )
        for o in db.execute(select(Observation)).scalars()
    )
    reviews = sorted(r.day for r in db.execute(select(DayReview)).scalars())
    return obs, reviews


def test_same_client_id_logs_once(db, coffee):
    cid = uuid.uuid4()
    first = _log(db, coffee, cid=cid)
    again = _log(db, coffee, 5, cid=cid)  # a retry, even with another value, changes nothing
    assert first.created and not again.created
    assert again.observation.value_num == 1.0
    assert len(db.execute(select(Event)).scalars().all()) == 1


def test_late_night_entry_lands_on_the_evening_before(db, coffee):
    when = dt.datetime(2026, 10, 16, 1, 30, tzinfo=NY)
    assert _log(db, coffee, when=when).observation.day == dt.date(2026, 10, 15)


def test_invalid_value_and_future_time_are_rejected(db, mood_scale):
    with pytest.raises(TrackerInputError):
        _log(db, mood_scale, 9)
    with pytest.raises(TrackerInputError):
        _log(db, mood_scale, 3, when=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1))


def test_delete_is_a_tombstone_and_survives_rebuild(db, coffee):
    entry = _log(db, coffee).observation
    assert capture.delete(db, entry.client_id, source="test")
    capture.rebuild(db, NY, FOUR)
    row = db.get(Observation, entry.client_id)
    assert row is not None and row.deleted  # the row stays, marked deleted; the log has both events
    assert [e.op for e in db.execute(select(Event).order_by(Event.seq)).scalars()] == ["log", "delete"]


def test_locked_fields_and_versioning(db, mood_scale):
    capture.update_tracker(db, mood_scale, scale_max=10)  # no data yet: allowed
    _log(db, mood_scale, 7)
    with pytest.raises(capture.LockedError):
        capture.update_tracker(db, mood_scale, scale_max=5)
    capture.update_tracker(db, mood_scale, name="Energy")  # free fields stay editable
    successor = capture.new_version(db, mood_scale, scale_min=0, scale_max=4)
    assert successor.key == "energy_level_v2" and mood_scale.archived and mood_scale.successor_id == successor.id
    with pytest.raises(TrackerInputError):
        _log(db, mood_scale, 3)  # archived: no new entries


def test_rebuild_equals_incremental_state(db, coffee, mood_scale):
    """Property test (risks.md B10): random log / edit / delete / review sequences, then replay the log."""
    rng = random.Random(7)
    start = dt.datetime(2026, 10, 1, 9, 0, tzinfo=NY)
    live: list[uuid.UUID] = []
    for step in range(120):
        when = start + dt.timedelta(hours=rng.randint(0, 24 * 14))
        action = rng.random()
        if action < 0.5 or not live:
            tracker = coffee if rng.random() < 0.5 else mood_scale
            value = rng.randint(1, 3) if tracker is coffee else rng.randint(1, 5)
            live.append(_log(db, tracker, value, when=when).observation.client_id)
        elif action < 0.7:
            cid = rng.choice(live)
            row = db.get(Observation, cid)
            value = rng.randint(1, 3) if row.tracker_id == coffee.id else rng.randint(1, 5)
            capture.edit(db, cid, value, observed_at=when, source="test", zone=NY, boundary=FOUR)
        elif action < 0.78:
            tag = rng.choice(["Slept badly", "travel"])
            capture.toggle_tag(
                db, mood_scale, tag, local_day(when, NY, FOUR), observed_at=when, source="test", zone=NY, boundary=FOUR
            )
        elif action < 0.85:
            cid = live.pop(rng.randrange(len(live)))
            capture.delete(db, cid, source="test")
        else:
            capture.set_reviewed(db, when.date(), rng.random() < 0.7, source="test")
        assert step >= 0
    incremental = _state(db)
    replayed = capture.rebuild(db, NY, FOUR)
    assert replayed == len(db.execute(select(Event)).scalars().all())
    rebuilt = _state(db)
    only_incremental = set(incremental[0]) - set(rebuilt[0])
    only_rebuilt = set(rebuilt[0]) - set(incremental[0])
    assert (only_incremental, only_rebuilt) == (set(), set())
    assert rebuilt[1] == incremental[1]


def test_tracker_features_reach_the_feature_table(db, coffee):
    day = dt.date(2026, 10, 10)
    _log(db, coffee, 2, when=dt.datetime.combine(day, dt.time(8), tzinfo=NY))
    capture.set_reviewed(db, day + dt.timedelta(days=1), True, source="test")
    features.rebuild(db, NY, FOUR)
    assert features.series(db, "tracker.coffee.total") == {day: 2.0, day + dt.timedelta(days=1): 0.0}


def _toggle(db, tracker, tag, day):
    when = dt.datetime.combine(day, dt.time(18), tzinfo=NY)
    return capture.toggle_tag(db, tracker, tag, day, observed_at=when, source="test", zone=NY, boundary=FOUR)


def test_tag_toggles_on_and_off_and_reaches_features(db, mood_scale):
    day = dt.date(2026, 10, 10)
    assert _toggle(db, mood_scale, "slept badly", day) is True
    assert capture.tags_for_day(db, day) == {mood_scale.id: {"slept_badly"}}
    assert _toggle(db, mood_scale, "Slept badly", day) is False  # tapping again unpicks it
    assert capture.tags_for_day(db, day) == {}
    assert _toggle(db, mood_scale, "travel", day) is True
    with pytest.raises(TrackerInputError):
        _toggle(db, mood_scale, "not a tag", day)
    tag_row = db.execute(select(Observation).where(Observation.tag == "travel")).scalar_one()
    with pytest.raises(TrackerInputError):
        capture.edit(db, tag_row.client_id, 3, observed_at=None, source="test", zone=NY, boundary=FOUR)
    features.rebuild(db, NY, FOUR)
    assert features.series(db, "tracker.energy_level.tag.travel") == {day: 1.0}
    assert features.series(db, "tracker.energy_level.tag.slept_badly") == {day: 0.0}
