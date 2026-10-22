"""The Reminders page: turn reminders on for this phone, pick the times, send a test (app/reminders.py)."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from . import auth, push, reminders
from .config import get_settings
from .db import get_db
from .models import PushSubscription, WebSession
from .web import _signed_in, current_session, templates

router = APIRouter()

TEST_TITLE = "Reminders are on"
TEST_BODY = "This is how the Companion will nudge you."


def _csrf_ok(session: WebSession, csrf: object) -> bool:
    return isinstance(csrf, str) and auth.constant_time_equals(csrf, session.csrf_token)


@router.get("/reminders", response_class=HTMLResponse)
def reminders_page(
    request: Request,
    note: str = "",
    error: str = "",
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "reminders.html",
        {
            "on": settings.push_on,
            "public_key": settings.vapid_public_key,
            "times": reminders.load_schedule(db),
            "kinds": reminders.KINDS,
            "devices": reminders.subscriptions(db),
            "csrf": session.csrf_token,
            "note": note[:200],
            "error": error[:200],
        },
    )


@router.post("/reminders")
async def save_reminder_times(
    request: Request,
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    form = dict(await request.form())
    if not _csrf_ok(session, form.get("csrf")):
        return Response("CSRF check failed", status_code=status.HTTP_403_FORBIDDEN)
    times: dict[str, dt.time | None] = {}
    try:
        for kind in reminders.KINDS:
            raw = str(form.get(kind.key, "")).strip()
            times[kind.key] = dt.time.fromisoformat(raw) if raw and form.get(f"{kind.key}_on") == "on" else None
    except ValueError:
        return RedirectResponse("/reminders?error=pick a time like 19:00", status_code=status.HTTP_303_SEE_OTHER)
    reminders.save_schedule(db, times)
    db.commit()
    return RedirectResponse("/reminders?note=Times saved", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/push/subscribe")
async def subscribe(
    request: Request,
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    """Called by the page after the phone grants permission: store where and how to reach this device."""
    if session is None:
        return JSONResponse({"detail": "sign in first"}, status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        data = await request.json()
        raw = data["subscription"]
        sub = push.Subscription(str(raw["endpoint"]), str(raw["keys"]["p256dh"]), str(raw["keys"]["auth"]))
    except (ValueError, KeyError, TypeError):
        return JSONResponse({"detail": "malformed subscription"}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    if not _csrf_ok(session, data.get("csrf")):
        return JSONResponse({"detail": "CSRF check failed"}, status_code=status.HTTP_403_FORBIDDEN)
    if not push.valid_subscription(sub):
        return JSONResponse({"detail": "not a known push service"}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    row = db.execute(sa.select(PushSubscription).where(PushSubscription.endpoint == sub.endpoint)).scalar_one_or_none()
    if row is None:
        db.add(PushSubscription(endpoint=sub.endpoint, p256dh=sub.p256dh, auth=sub.auth))
    else:
        row.p256dh, row.auth = sub.p256dh, sub.auth
    db.commit()
    return JSONResponse({"subscribed": True})


@router.post("/push/unsubscribe")
async def unsubscribe(
    request: Request,
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if session is None:
        return JSONResponse({"detail": "sign in first"}, status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        data = await request.json()
        endpoint = str(data["endpoint"])
    except (ValueError, KeyError, TypeError):
        return JSONResponse({"detail": "malformed request"}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    if not _csrf_ok(session, data.get("csrf")):
        return JSONResponse({"detail": "CSRF check failed"}, status_code=status.HTTP_403_FORBIDDEN)
    db.execute(sa.delete(PushSubscription).where(PushSubscription.endpoint == endpoint))
    db.commit()
    return JSONResponse({"subscribed": False})


@router.post("/push/test")
def send_test(
    csrf: str = Form(""),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not _csrf_ok(session, csrf):
        return Response("CSRF check failed", status_code=status.HTTP_403_FORBIDDEN)
    sent = reminders.send(db, get_settings(), TEST_TITLE, TEST_BODY, "/reminders")
    db.commit()
    note = f"Test sent to {sent} device(s); it should arrive within a minute" if sent else "No devices to send to yet"
    return RedirectResponse(f"/reminders?note={note}", status_code=status.HTTP_303_SEE_OTHER)
