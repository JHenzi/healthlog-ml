"""The Reminders page and subscribe routes: sign-in, CSRF, push-service hosts only (D2, risks.md E8)."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app import auth, push, reminders, web_reminders
from app.config import get_settings
from app.models import PushSubscription

PASSWORD = "reminders page password"
SUB = {
    "endpoint": "https://web.push.apple.com/synthetic",
    "keys": {"p256dh": push.b64url(b"\x04" + b"\x01" * 64), "auth": push.b64url(b"\x02" * 16)},
}


def _csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def signed_in(client, db):
    auth.set_password(db, PASSWORD)
    db.flush()
    page = client.get("/login")
    client.post("/login", data={"password": PASSWORD, "csrf": _csrf(page.text)})
    return client


def test_the_page_needs_sign_in(client):
    assert client.get("/reminders", follow_redirects=False).status_code == 303


def test_off_on_the_server_the_page_shows_the_keys_command(signed_in):
    html = signed_in.get("/reminders").text
    assert "companion push keys" in html and "data-push-on" not in html


def test_on_the_server_the_page_offers_this_phone(signed_in, monkeypatch):
    public, private = push.generate_keys()
    on = get_settings().model_copy(update={"vapid_public_key": public, "vapid_private_key": private})
    monkeypatch.setattr(web_reminders, "get_settings", lambda: on)
    html = signed_in.get("/reminders").text
    assert f'data-public-key="{public}"' in html and private not in html


def test_subscribe_needs_csrf_and_a_push_service(signed_in, db):
    csrf = _csrf(signed_in.get("/reminders").text)
    assert signed_in.post("/push/subscribe", json={"csrf": "forged", "subscription": SUB}).status_code == 403
    evil = {**SUB, "endpoint": "https://evil.example/x"}
    assert signed_in.post("/push/subscribe", json={"csrf": csrf, "subscription": evil}).status_code == 422
    assert signed_in.post("/push/subscribe", json={"csrf": csrf, "subscription": SUB}).status_code == 200
    assert [r.endpoint for r in db.execute(select(PushSubscription)).scalars()] == [SUB["endpoint"]]
    assert signed_in.post("/push/unsubscribe", json={"csrf": csrf, "endpoint": SUB["endpoint"]}).status_code == 200
    assert db.execute(select(PushSubscription)).first() is None


def test_subscribe_without_sign_in_is_refused(client):
    assert client.post("/push/subscribe", json={"csrf": "x", "subscription": SUB}).status_code == 401


def test_times_are_saved_and_can_be_turned_off(signed_in, db):
    csrf = _csrf(signed_in.get("/reminders").text)
    r = signed_in.post(
        "/reminders",
        data={"csrf": csrf, "morning": "09:30", "morning_on": "on", "evening": "19:00"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    times = reminders.load_schedule(db)
    assert times["morning"].isoformat(timespec="minutes") == "09:30" and times["evening"] is None
