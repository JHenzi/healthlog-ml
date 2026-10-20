"""Web and API auth (risks.md D1-D4): lockout, CSRF, cookie flags, token scopes, escaping, headers."""

from __future__ import annotations

import logging
import re

import pytest
from sqlalchemy import select, text

from app import auth, today
from app.models import ApiToken

PASSWORD = "correct horse battery staple"


def _csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def user(db):
    auth.set_password(db, PASSWORD)
    db.flush()


def _login(client, password: str = PASSWORD):
    page = client.get("/login")
    return client.post("/login", data={"password": password, "csrf": _csrf(page.text)}, follow_redirects=False)


@pytest.fixture
def no_upstream_reads(monkeypatch):
    monkeypatch.setattr(
        today, "load_today", lambda db, zone, boundary, day, country=None: today.TodayView(day, ["line"], [])
    )


def test_login_page_says_when_no_password_is_set(client):
    assert "companion set-password" in client.get("/login").text


def test_short_password_rejected(db):
    with pytest.raises(ValueError):
        auth.set_password(db, "short")


def test_login_without_valid_csrf_is_403(client, user):
    client.get("/login")
    assert client.post("/login", data={"password": PASSWORD, "csrf": "forged"}).status_code == 403


def test_wrong_password_is_401(client, user):
    assert _login(client, "nope nope nope").status_code == 401


def test_lockout_after_max_failures_even_with_right_password(client, user):
    for _ in range(5):
        assert _login(client, "wrong password!!").status_code == 401
    assert _login(client).status_code == 429


def test_login_sets_strict_secure_httponly_cookie_and_today_requires_it(client, user, no_upstream_reads):
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    response = _login(client)
    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert client.get("/").status_code == 200


def test_session_is_stored_hashed(client, db, user):
    raw = _login(client).cookies[auth.SESSION_COOKIE]
    stored = db.execute(text("SELECT token_hash FROM companion.sessions")).scalars().all()
    assert raw not in stored and auth.sha256(raw) in stored


def test_logout_requires_csrf(client, user, no_upstream_reads):
    _login(client)
    assert client.post("/logout", data={"csrf": "forged"}).status_code == 403
    csrf = _csrf(client.get("/").text)
    assert client.post("/logout", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    assert client.get("/", follow_redirects=False).status_code == 303


def test_user_text_is_escaped(client, user, monkeypatch):
    payload = '<script>alert(1)</script>"><img src=x onerror=alert(1)>'
    monkeypatch.setattr(
        today, "load_today", lambda db, zone, boundary, day, country=None: today.TodayView(day, [payload], [payload])
    )
    _login(client)
    html = client.get("/").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_security_headers(client):
    headers = client.get("/login").headers
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    ("scope", "expected"),
    [("all", 200), ("read", 200), ("log:coffee", 403)],
)
def test_token_scope_matrix_on_read_endpoint(client, db, scope, expected, no_upstream_reads):
    raw, _ = auth.create_token(db, "test", scope)
    response = client.get("/api/today", headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code == expected


@pytest.mark.parametrize("header", [None, "Bearer hlc_not-a-real-token", "Bearer ", "Basic abc"])
def test_missing_or_unknown_token_is_401(client, header):
    headers = {"Authorization": header} if header else {}
    assert client.get("/api/today", headers=headers).status_code == 401


def test_revoked_token_is_401_and_tokens_are_stored_hashed(client, db, no_upstream_reads):
    raw, row = auth.create_token(db, "phone", "read")
    assert db.execute(select(ApiToken.token_hash)).scalar_one() == auth.sha256(raw)
    assert client.get("/api/today", headers={"Authorization": f"Bearer {raw}"}).status_code == 200
    assert auth.revoke_token(db, row.id)
    assert client.get("/api/today", headers={"Authorization": f"Bearer {raw}"}).status_code == 401


def test_secrets_never_reach_the_log(client, db, user, caplog, no_upstream_reads):
    caplog.set_level(logging.DEBUG)
    _login(client)
    _login(client, "a wrong password")
    raw, _ = auth.create_token(db, "t", "read")
    client.get("/api/today", headers={"Authorization": f"Bearer {raw}"})
    logged = caplog.text
    assert PASSWORD not in logged and "a wrong password" not in logged and raw not in logged
