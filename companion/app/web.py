"""Server-rendered pages. Every state-changing form carries a CSRF token; templates autoescape."""

from __future__ import annotations

import datetime as dt
import logging
import secrets
from pathlib import Path

import jinja2
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import auth, today
from .config import get_settings
from .db import get_db
from .models import User, WebSession
from .proxies import client_ip
from .timeutil import current_day

log = logging.getLogger("companion.web")

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "web" / "templates"
templates = Jinja2Templates(env=jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATE_DIR), autoescape=True))

router = APIRouter()


def _cookie_kwargs() -> dict:
    return {"httponly": True, "secure": get_settings().cookie_secure, "samesite": "strict"}


def _client(request: Request) -> str | None:
    peer = request.client.host if request.client else None
    return client_ip(peer, request.headers.get("x-forwarded-for"), get_settings().trusted_proxies)


def current_session(request: Request, db: Session = Depends(get_db)) -> WebSession | None:
    return auth.session_for(db, request.cookies.get(auth.SESSION_COOKIE))


def _login_page(request: Request, db: Session, *, error: str = "", status_code: int = 200) -> Response:
    csrf = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(
        request,
        "login.html",
        {"csrf": csrf, "error": error, "has_user": db.get(User, auth.SINGLE_USER_ID) is not None},
        status_code=status_code,
    )
    response.set_cookie(auth.LOGIN_CSRF_COOKIE, csrf, path="/login", max_age=3600, **_cookie_kwargs())
    return response


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: Session = Depends(get_db)) -> Response:
    return _login_page(request, db)


@router.post("/login")
def login(request: Request, password: str = Form(""), csrf: str = Form(""), db: Session = Depends(get_db)) -> Response:
    if not auth.constant_time_equals(csrf, request.cookies.get(auth.LOGIN_CSRF_COOKIE)):
        return Response("CSRF check failed", status_code=status.HTTP_403_FORBIDDEN)
    settings = get_settings()
    result = auth.check_login(
        db, password, max_failures=settings.login_max_failures, lockout_minutes=settings.login_lockout_minutes
    )
    if not result.ok:
        db.commit()  # keep the failure count
        log.warning("login failed (%s) from %s", result.reason, _client(request))
        if result.reason == "locked":
            return _login_page(request, db, error="Too many attempts. Try again later.", status_code=429)
        return _login_page(request, db, error="Wrong password.", status_code=401)
    raw, _row = auth.create_session(db, settings.session_days)
    db.commit()
    log.info("login from %s", _client(request))
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(auth.SESSION_COOKIE, raw, max_age=settings.session_days * 86400, **_cookie_kwargs())
    response.delete_cookie(auth.LOGIN_CSRF_COOKIE, path="/login")
    return response


@router.post("/logout")
def logout(
    request: Request,
    csrf: str = Form(""),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if session is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if not auth.constant_time_equals(csrf, session.csrf_token):
        return Response("CSRF check failed", status_code=status.HTTP_403_FORBIDDEN)
    auth.end_session(db, request.cookies.get(auth.SESSION_COOKIE))
    db.commit()
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(auth.SESSION_COOKIE)
    return response


@router.get("/", response_class=HTMLResponse)
def today_page(
    request: Request, session: WebSession | None = Depends(current_session), db: Session = Depends(get_db)
) -> Response:
    if session is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    settings = get_settings()
    day = current_day(dt.datetime.now(dt.UTC), settings.zone, settings.day_boundary)
    view = today.load_today(db, settings.zone, settings.day_boundary, day)
    return templates.TemplateResponse(request, "today.html", {"view": view, "csrf": session.csrf_token})
