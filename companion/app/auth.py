"""Authentication: the operator's password, browser sessions, CSRF and scoped API tokens.

``password`` mode (design §8.1): one argon2-hashed password → a session
cookie (``HttpOnly``, ``Secure``, ``SameSite=Strict``) plus a per-session CSRF
token on every form. API tokens are for Shortcuts and scripts: random,
stored as SHA-256 only, scoped (``all`` | ``read`` | ``log:<tracker_key>``),
revocable one at a time. No secret is ever logged (R11).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

import sqlalchemy as sa
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.orm import Session

from .models import ApiToken, User, WebSession

SESSION_COOKIE = "companion_session"
LOGIN_CSRF_COOKIE = "companion_login_csrf"
TOKEN_PREFIX = "hlc_"
SINGLE_USER_ID = 1

TRACKER_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")  # risks.md D5

_hasher = PasswordHasher()


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def constant_time_equals(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode(), b.encode())


# --- password --------------------------------------------------------------


def set_password(db: Session, password: str) -> None:
    if len(password) < 12:
        raise ValueError("use at least 12 characters")
    user = db.get(User, SINGLE_USER_ID)
    hashed = _hasher.hash(password)
    if user is None:
        db.add(User(id=SINGLE_USER_ID, password_hash=hashed, failed_logins=0))
    else:
        user.password_hash = hashed
        user.failed_logins = 0
        user.locked_until = None
    # Changing the password ends every existing session.
    db.execute(sa.delete(WebSession))


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    reason: str = ""  # "no_user" | "locked" | "bad_password"


def check_login(db: Session, password: str, *, max_failures: int, lockout_minutes: int) -> LoginResult:
    """Verify the password with a persistent lockout after ``max_failures`` (risks.md D1)."""
    user = db.get(User, SINGLE_USER_ID, with_for_update=True)
    if user is None:
        return LoginResult(False, "no_user")
    now = now_utc()
    if user.locked_until and user.locked_until > now:
        return LoginResult(False, "locked")
    try:
        _hasher.verify(user.password_hash, password)
    except (VerificationError, InvalidHashError):
        user.failed_logins += 1
        if user.failed_logins >= max_failures:
            user.locked_until = now + dt.timedelta(minutes=lockout_minutes)
            user.failed_logins = 0
        return LoginResult(False, "bad_password")
    user.failed_logins = 0
    user.locked_until = None
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = _hasher.hash(password)
    return LoginResult(True)


# --- sessions --------------------------------------------------------------


def create_session(db: Session, days: int) -> tuple[str, WebSession]:
    """Returns the raw cookie value (shown to the browser only) and the stored row."""
    raw = secrets.token_urlsafe(32)
    row = WebSession(
        token_hash=sha256(raw),
        user_id=SINGLE_USER_ID,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=now_utc() + dt.timedelta(days=days),
    )
    db.add(row)
    return raw, row


def session_for(db: Session, raw: str | None) -> WebSession | None:
    if not raw:
        return None
    row = db.get(WebSession, sha256(raw))
    if row is None or row.expires_at <= now_utc():
        return None
    return row


def end_session(db: Session, raw: str | None) -> None:
    if raw:
        db.execute(sa.delete(WebSession).where(WebSession.token_hash == sha256(raw)))


# --- API tokens ------------------------------------------------------------


def validate_scope(scope: str) -> str:
    if scope in ("all", "read"):
        return scope
    if scope.startswith("log:") and TRACKER_KEY_RE.match(scope[4:]):
        return scope
    raise ValueError("scope must be 'all', 'read' or 'log:<tracker_key>'")


def create_token(db: Session, name: str, scope: str) -> tuple[str, ApiToken]:
    """Returns the raw token (shown once, never stored) and the stored row."""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = ApiToken(name=name, token_hash=sha256(raw), scope=validate_scope(scope))
    db.add(row)
    db.flush()
    return raw, row


def token_for(db: Session, raw: str | None) -> ApiToken | None:
    if not raw or not raw.startswith(TOKEN_PREFIX):
        return None
    row = db.execute(sa.select(ApiToken).where(ApiToken.token_hash == sha256(raw))).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    row.last_used_at = now_utc()
    return row


def revoke_token(db: Session, token_id: int) -> bool:
    row = db.get(ApiToken, token_id)
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = now_utc()
    return True


def scope_allows(scope: str, needed: str) -> bool:
    """``needed`` is ``read`` or ``log:<key>``. ``all`` allows everything; ``read`` never allows logging."""
    if scope == "all":
        return True
    return scope == needed
