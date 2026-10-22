"""Server-rendered pages. Every state-changing form carries a CSRF token; templates autoescape."""

from __future__ import annotations

import datetime as dt
import logging
import secrets
from pathlib import Path

import jinja2
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import auth, capture, features, glance, goodday, jobs, metric_settings, metrics_view, pwa, today, upstream
from .analysis import run as analysis_run
from .config import get_settings
from .db import get_db
from .models import DailyFeature, FeatureDef, Insight, MetricSetting, Setting, User, WebSession
from .proxies import client_ip
from .timeutil import current_day
from .trackers import tag_slug

log = logging.getLogger("companion.web")

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "web" / "templates"
templates = Jinja2Templates(env=jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATE_DIR), autoescape=True))
templates.env.filters["tag_slug"] = tag_slug
templates.env.globals["rendered_at"] = pwa.rendered_at
templates.env.globals["static_v"] = pwa.static_version()

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
    request: Request,
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
    error: str = "",
) -> Response:
    if session is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    settings = get_settings()
    day = current_day(dt.datetime.now(dt.UTC), settings.zone, settings.day_boundary)
    view = today.load_today(db, settings.zone, settings.day_boundary, day)
    from .web_trackers import today_capture  # late import: web_trackers builds on this module

    return templates.TemplateResponse(
        request,
        "today.html",
        {
            "view": view,
            "csrf": session.csrf_token,
            "capture": today_capture(db, day),
            "overview": _overview(db, day),
            "goodday": goodday.load_view(db, day),
            "error": error[:200],
        },
    )


# Self-logged features: HealthLog measures every day, so coverage is about what you log yourself.
LOGGED_PREFIXES = ("tracker.%", "mood.%", "rating.%")
PRELIMINARY_DAYS = 30  # wireframe 1a: "most comparisons need about 30 logged days"


def _overview(db: Session, day: dt.date) -> dict:
    """Coverage strip and the top discoveries for the Overview (wireframe 1a)."""
    end = day - dt.timedelta(days=1)
    start = end - dt.timedelta(days=metrics_view.WINDOW_DAYS - 1)
    logged_days = set(
        db.execute(
            sa.select(DailyFeature.day)
            .where(
                DailyFeature.day.between(start, end),
                sa.or_(*(DailyFeature.feature.like(p) for p in LOGGED_PREFIXES)),
            )
            .distinct()
        ).scalars()
    )
    cells = metrics_view.coverage(logged_days, end)
    top = (
        db.execute(sa.select(Insight).where(Insight.kind == "association").order_by(Insight.score.desc()).limit(2))
        .scalars()
        .all()
    )
    return {
        "cells": cells,
        "recorded": sum(1 for _, ok in cells if ok),
        "top": top,
        "cards": _cards(db, top),
        "preliminary_days": PRELIMINARY_DAYS,
    }


def _cards(db: Session, insights: list[Insight]) -> dict[int, glance.Card]:
    """Each insight's at-a-glance head, keyed by id."""
    features = {f for i in insights for f in (i.feature_a, i.feature_b) if f}
    defs = {d.feature: d for d in db.execute(sa.select(FeatureDef).where(FeatureDef.feature.in_(features))).scalars()}
    day = capture.day_tags(db)
    tags = glance.tag_colours(day.tags if day else ())
    return {i.id: glance.card(i, defs, tags) for i in insights}


# --- metrics (M2) -----------------------------------------------------------


def _signed_in(session: WebSession | None) -> Response | None:
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER) if session is None else None


def _today() -> dt.date:
    settings = get_settings()
    return current_day(dt.datetime.now(dt.UTC), settings.zone, settings.day_boundary)


SOURCE_ORDER = (
    "goodday",
    "rating",
    "tracker",
    "sleep",
    "healthlog",
    "stress",
    "energy",
    "workout",
    "mood",
    "weather",
    "almanac",
)
SOURCE_TITLES = {
    "goodday": "Good day",
    "rating": "Day rating",
    "tracker": "Your trackers",
    "sleep": "Sleep",
    "healthlog": "HealthLog metrics",
    "stress": "Stress",
    "energy": "Energy reserve",
    "workout": "Workouts",
    "mood": "Mood (State of Mind)",
    "weather": "Weather",
    "almanac": "Almanac",
}


@router.get("/metrics", response_class=HTMLResponse)
def metrics_page(
    request: Request, session: WebSession | None = Depends(current_session), db: Session = Depends(get_db)
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    day = _today()
    defs = {d.feature: d for d in db.execute(sa.select(FeatureDef)).scalars()}
    all_values = features.all_series(db)
    groups = []
    for source in SOURCE_ORDER:
        items = [
            (d, metrics_view.summarize(all_values.get(d.feature, {}), day))
            for d in sorted((d for d in defs.values() if d.source == source), key=lambda d: d.label.lower())
        ]
        if items:
            groups.append((SOURCE_TITLES[source], items))
    return templates.TemplateResponse(
        request,
        "metrics.html",
        {"groups": groups, "csrf": session.csrf_token, "fmt": metrics_view.fmt, "empty": not defs},
    )


@router.get("/metrics/{feature}", response_class=HTMLResponse)
def metric_detail(
    feature: str,
    request: Request,
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
    error: str = "",
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    definition = db.get(FeatureDef, feature)
    if definition is None:
        return Response("No such metric", status_code=status.HTTP_404_NOT_FOUND)
    day = _today()
    values = features.series(db, feature)
    end = day - dt.timedelta(days=1)
    recent = [(end - dt.timedelta(days=i), values.get(end - dt.timedelta(days=i))) for i in range(30)]
    metric = feature.removeprefix("hl.") if feature.startswith("hl.") else None
    setting = db.get(MetricSetting, metric) if metric else None
    return templates.TemplateResponse(
        request,
        "metric_detail.html",
        {
            "d": definition,
            "s": metrics_view.summarize(values, day),
            "spark": metrics_view.sparkline(values, end).split("|"),
            "recent": recent,
            "weekdays": metrics_view.WEEKDAYS,
            "fmt": metrics_view.fmt,
            "setting": setting,
            "sources": upstream.metric_sources(db, metric) if setting else [],
            "aggregations": metric_settings.AGGREGATIONS,
            "csrf": session.csrf_token,
            "error": error,
            "provenance": metrics_view.PROVENANCE.get(definition.source, "Imported"),
        },
    )


def _optional_float(raw: str) -> float | None:
    raw = raw.strip()
    return float(raw) if raw else None


@router.post("/metrics/{feature}/settings")
def save_metric_settings(
    feature: str,
    request: Request,
    csrf: str = Form(""),
    aggregation: str = Form("avg"),
    analyse: str = Form(""),
    min_value: str = Form(""),
    max_value: str = Form(""),
    source_priority: str = Form(""),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not auth.constant_time_equals(csrf, session.csrf_token):
        return Response("CSRF check failed", status_code=status.HTTP_403_FORBIDDEN)
    if not feature.startswith("hl."):
        return Response("Only HealthLog metrics have settings", status_code=status.HTTP_404_NOT_FOUND)
    try:
        metric_settings.update(
            db,
            feature.removeprefix("hl."),
            aggregation=aggregation,
            analyse=analyse == "on",
            min_value=_optional_float(min_value),
            max_value=_optional_float(max_value),
            source_priority=source_priority.split(","),
        )
    except KeyError:
        return Response("No such metric", status_code=status.HTTP_404_NOT_FOUND)
    except ValueError as exc:  # raised before anything changed
        return metric_detail(feature, request, session, db, error=str(exc))
    settings = get_settings()
    features.rebuild(db, settings.zone, settings.day_boundary, settings.latitude, settings.holiday_country)
    db.commit()
    return RedirectResponse(f"/metrics/{feature}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/metrics/{feature}/reset")
def reset_metric_settings(
    feature: str,
    csrf: str = Form(""),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not auth.constant_time_equals(csrf, session.csrf_token):
        return Response("CSRF check failed", status_code=status.HTTP_403_FORBIDDEN)
    metric_settings.reset(db, feature.removeprefix("hl."))
    jobs.refresh(db)
    db.commit()
    return RedirectResponse(f"/metrics/{feature}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/refresh")
def refresh_now(
    csrf: str = Form(""),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not auth.constant_time_equals(csrf, session.csrf_token):
        return Response("CSRF check failed", status_code=status.HTTP_403_FORBIDDEN)
    jobs.refresh(db)
    db.commit()
    return RedirectResponse("/metrics", status_code=status.HTTP_303_SEE_OTHER)


# --- good days ----------------------------------------------------------------


@router.get("/good-days", response_class=HTMLResponse)
def good_days_page(
    request: Request, session: WebSession | None = Depends(current_session), db: Session = Depends(get_db)
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    view = goodday.load_view(db, _today())
    return templates.TemplateResponse(
        request,
        "good_days.html",
        {
            "g": view,
            "cards": _cards(db, [c.insight for c in view.common]),
            "fmt": metrics_view.fmt,
            "min_parts": goodday.MIN_PARTS,
            "min_scored": goodday.MIN_SCORED_DAYS,
            "preliminary_days": PRELIMINARY_DAYS,
            "csrf": session.csrf_token,
        },
    )


# --- insights (M5) ----------------------------------------------------------

INSIGHT_SECTIONS = (
    ("Relationships", lambda i: i.kind == "association"),
    ("This week", lambda i: i.kind == "change" and i.horizon == "week"),
    ("This month", lambda i: i.kind == "change" and i.horizon == "month"),
    ("Weekly rhythm", lambda i: i.kind == "weekday"),
)

METHOD_NAMES = {
    "spearman": "Spearman rank correlation on residuals (weekday profile and 28-day trend removed)",
    "mann_whitney": "Mann-Whitney U test with Cliff's delta",
    "mean_shift": "difference in means with autocorrelation-adjusted sample sizes (effect: Cliff's delta)",
    "fisher": "Fisher's exact test (effect: phi coefficient)",
    "kruskal": "Kruskal-Wallis test across weekdays (effect: eta squared)",
    "distributed_lag": "distributed lag model over days 0–7, one smooth curve per pair, F test on the effective "
    "number of days (effect: signed square root of the variance it explains)",
}


@router.get("/insights", response_class=HTMLResponse)
def insights_page(
    request: Request, session: WebSession | None = Depends(current_session), db: Session = Depends(get_db)
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    rows = db.execute(sa.select(Insight).order_by(Insight.score.desc())).scalars().all()
    sections = [(title, [i for i in rows if keep(i)]) for title, keep in INSIGHT_SECTIONS]
    last_run = db.get(Setting, analysis_run.STATS_KEY)
    return templates.TemplateResponse(
        request,
        "insights.html",
        {
            "sections": sections,
            "cards": _cards(db, list(rows)),
            "ranges": {i.id: glance.likely_range(i) for i in rows},
            "adjusted": {i.id: glance.adjusted(i) for i in rows},
            "run": last_run.value if last_run else None,
            "csrf": session.csrf_token,
            "any": bool(rows),
            "preliminary_days": PRELIMINARY_DAYS,
        },
    )


@router.get("/insights/{insight_id}", response_class=HTMLResponse)
def insight_detail(
    insight_id: int,
    request: Request,
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    insight = db.get(Insight, insight_id)
    if insight is None:
        return Response("No such insight", status_code=status.HTTP_404_NOT_FOUND)
    defs = {
        d.feature: d
        for d in db.execute(
            sa.select(FeatureDef).where(FeatureDef.feature.in_([insight.feature_a, insight.feature_b or ""]))
        ).scalars()
    }
    return templates.TemplateResponse(
        request,
        "insight_detail.html",
        {
            "i": insight,
            "defs": defs,
            "method": METHOD_NAMES.get(insight.method, insight.method),
            "likely": glance.likely_range(insight),
            "lag_bars": glance.lag_bars(insight),
            "adjusted": glance.adjusted(insight),
            "csrf": session.csrf_token,
        },
    )
