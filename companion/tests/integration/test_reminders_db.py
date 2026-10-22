"""Reminders against the database: sealed into the outbox when due, once a day, skipped once answered, and
devices the push service says are gone are forgotten (risks.md E8). Files only, no network."""

from __future__ import annotations

import datetime as dt
import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from app import capture, dayrating, push, reminders
from app.config import get_settings
from app.models import PushSubscription


@pytest.fixture
def settings(tmp_path):
    public, private = push.generate_keys()
    return get_settings().model_copy(
        update={"vapid_public_key": public, "vapid_private_key": private, "push_dir": tmp_path}
    )


@pytest.fixture
def phone(db):
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    row = PushSubscription(
        endpoint="https://web.push.apple.com/synthetic", p256dh=push.b64url(public), auth=push.b64url(os.urandom(16))
    )
    db.add(row)
    db.flush()
    return row


def _at(settings, hour: int, minute: int = 2) -> dt.datetime:
    return dt.datetime(2026, 10, 1, hour, minute, tzinfo=settings.zone).astimezone(dt.UTC)


def _outbox(settings) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((settings.push_dir / "outbox").glob("*.json"))]


def test_a_due_reminder_is_sealed_once_for_each_device(db, settings, phone):
    assert reminders.run_due(db, settings, _at(settings, 19)) == ["evening"]
    assert [e["endpoint"] for e in _outbox(settings)] == [phone.endpoint]
    assert reminders.run_due(db, settings, _at(settings, 19, 30)) == []  # not twice a day
    assert len(_outbox(settings)) == 1


def test_an_answered_question_is_not_asked(db, settings, phone):
    tracker = dayrating.ensure(db, dayrating.EVENING_KEY)
    when = _at(settings, 18)
    capture.log(
        db,
        tracker,
        7,
        observed_at=when,
        client_id=None,
        source="test",
        zone=settings.zone,
        boundary=settings.day_boundary,
    )
    assert reminders.run_due(db, settings, _at(settings, 19)) == ["evening"]  # handled: marked for today
    assert _outbox(settings) == []


def test_without_keys_nothing_is_prepared(db, settings, phone):
    off = settings.model_copy(update={"vapid_private_key": ""})
    assert reminders.run_due(db, off, _at(settings, 19)) == []
    assert not (settings.push_dir / "outbox").exists()


def test_a_gone_device_is_forgotten(db, settings, phone):
    (settings.push_dir / "results").mkdir(parents=True)
    (settings.push_dir / "results" / "a.json").write_text(json.dumps({"endpoint": phone.endpoint, "status": 410}))
    assert reminders.apply_results(db, settings) == 1
    assert db.execute(select(PushSubscription)).first() is None
