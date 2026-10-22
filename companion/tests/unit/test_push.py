"""Reminders (risks.md E8): sealed for the phone only, signed for the push service, allowlisted hosts, and a
courier that delivers what it can't read. No network: the courier posts to a fake. Synthetic values only (R4)."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os

import http_ece
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from app import push, reminders
from tests.unit.test_collector import collector

NOW = dt.datetime(2026, 10, 22, 23, 5, tzinfo=dt.UTC)
APPLE = "https://web.push.apple.com/QGuQyavXutnMH7Zxhe-example"


def _phone():
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = os.urandom(16)
    return key, push.Subscription(APPLE, push.b64url(public), push.b64url(auth)), auth


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        (APPLE, True),
        ("https://fcm.googleapis.com/fcm/send/abc", True),
        ("https://wns2-by3p.notify.windows.com/w/?token=x", True),
        ("http://web.push.apple.com/x", False),
        ("https://evil.example/web.push.apple.com", False),
        ("https://web.push.apple.com.evil.example/x", False),
        ("https://127.0.0.1/x", False),
    ],
)
def test_only_push_services_are_allowed_and_the_courier_agrees(url, ok):
    assert push.endpoint_allowed(url) is ok
    assert collector.push_host_allowed(url) is ok


def test_a_sealed_reminder_opens_only_with_the_phones_key():
    phone, sub, auth = _phone()
    public, private = push.generate_keys()
    entry = push.seal({"title": "How was today?"}, sub, public, private, "mailto:a@example.org", NOW)
    body = base64.b64decode(entry["body"])
    assert b"How was today" not in body
    opened = http_ece.decrypt(body, private_key=phone, auth_secret=auth, version="aes128gcm")
    assert json.loads(opened) == {"title": "How was today?"}
    other, _, _ = _phone()
    with pytest.raises(Exception):  # noqa: B017 - any failure: another key can't open it
        http_ece.decrypt(body, private_key=other, auth_secret=auth, version="aes128gcm")


def test_the_vapid_token_is_signed_for_the_push_service():
    public, private = push.generate_keys()
    header = push.vapid_header(APPLE, public, private, "mailto:a@example.org", NOW)
    token = header.split("t=")[1].split(",")[0]
    assert header.endswith(f"k={public}")
    head, claims, sig = token.split(".")
    assert json.loads(push.unb64url(claims))["aud"] == "https://web.push.apple.com"
    raw = push.unb64url(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.unb64url(public))
    key.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if forged


def test_the_courier_delivers_refuses_and_reports(tmp_path):
    _, sub, _ = _phone()
    public, private = push.generate_keys()
    good = push.seal({"title": "t"}, sub, public, private, "mailto:a@example.org", NOW)
    good["headers"]["X-Extra"] = "dropped"
    push.write_outbox(tmp_path, good)
    push.write_outbox(tmp_path, {**good, "id": "evil", "endpoint": "https://evil.example/x"})
    push.write_outbox(tmp_path, {**good, "id": "old", "created": (NOW - dt.timedelta(hours=5)).isoformat()})
    calls = []
    posted = collector.deliver_once(tmp_path, NOW, lambda url, headers, body: calls.append((url, headers)) or 201)
    assert posted == 1 and [c[0] for c in calls] == [APPLE]
    assert "X-Extra" not in calls[0][1] and calls[0][1]["Content-Encoding"] == "aes128gcm"
    assert list((tmp_path / "outbox").glob("*.json")) == []
    statuses = sorted(r.status for r in push.take_results(tmp_path))
    assert statuses == [-2, -1, 201]
    assert push.take_results(tmp_path) == []  # read once


def test_reminders_are_due_once_a_day_and_not_hours_late():
    zone = dt.timezone(dt.timedelta(hours=-4))
    times = reminders.schedule(None)
    at = lambda h, m: dt.datetime(2026, 10, 22, h, m, tzinfo=zone)  # noqa: E731
    assert reminders.due(at(9, 59), times, {}) == []
    assert reminders.due(at(10, 0), times, {}) == ["morning"]
    assert reminders.due(at(10, 1), times, {"morning": "2026-10-22"}) == []
    assert reminders.due(at(12, 30), times, {}) == []  # too late after downtime
    assert reminders.due(at(19, 3), times, {"morning": "2026-10-22"}) == ["evening"]
    assert reminders.due(at(19, 3), reminders.schedule({"evening": ""}), {}) == []  # turned off
