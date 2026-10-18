"""Tracker pages: create and edit trackers, quick-add, entries, the Set up panel and the evening review."""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from . import auth, capture
from .config import get_settings
from .db import get_db
from .models import ApiToken, Observation, Tracker, WebSession
from .trackers import TYPE_LABELS, TYPES, TrackerInputError, slugify
from .web import _signed_in, _today, current_session, templates

router = APIRouter()

POLARITIES = ("neutral", "good", "bad")


def _csrf_ok(session: WebSession, csrf: str) -> bool:
    return auth.constant_time_equals(csrf, session.csrf_token)


def _forbidden() -> Response:
    return Response("CSRF check failed", status_code=status.HTTP_403_FORBIDDEN)


def _float(raw: str) -> float | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise TrackerInputError(f"{raw!r} is not a number") from exc


def _options(raw: str) -> list[str]:
    return [o.strip().lower().replace(" ", "_") for o in raw.split(",") if o.strip()]


def _scale_labels(raw: str) -> dict:
    """'1=nothing done, 5=best day' → {"1": "nothing done", "5": "best day"}."""
    labels = {}
    for part in raw.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip():
                labels[k.strip()] = v.strip()
    return labels


def _display(o: Observation, t: Tracker) -> str:
    if t.type == "choice":
        return (o.value_text or "").replace("_", " ")
    if t.type == "check":
        return "yes" if (o.value_num or 0) > 0 else "no"
    if t.type == "time":
        return ""
    if t.type == "moment":
        return f"intensity {o.value_num:g}" if o.value_num else ""
    unit = f" {t.unit}" if t.unit else ""
    return f"{o.value_num:g}{unit}" if o.value_num is not None else ""


def _local(ts: dt.datetime) -> dt.datetime:
    return ts.astimezone(get_settings().zone)


@router.get("/trackers", response_class=HTMLResponse)
def trackers_page(
    request: Request,
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
    error: str = "",
    form: dict | None = None,
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    rows = db.execute(sa.select(Tracker).order_by(Tracker.archived, Tracker.name)).scalars().all()
    counts = dict(
        db.execute(
            sa.select(Observation.tracker_id, sa.func.count())
            .where(Observation.deleted.is_(False))
            .group_by(Observation.tracker_id)
        ).all()
    )
    return templates.TemplateResponse(
        request,
        "trackers.html",
        {
            "trackers": rows,
            "counts": counts,
            "types": TYPES,
            "type_labels": TYPE_LABELS,
            "polarities": POLARITIES,
            "csrf": session.csrf_token,
            "error": error,
            "form": form or {},
        },
        status_code=422 if error else 200,
    )


@router.post("/trackers")
def create_tracker(
    request: Request,
    csrf: str = Form(""),
    name: str = Form(""),
    key: str = Form(""),
    type: str = Form("count"),
    unit: str = Form(""),
    scale_min: str = Form(""),
    scale_max: str = Form(""),
    scale_labels: str = Form(""),
    options: str = Form(""),
    polarity: str = Form("neutral"),
    category: str = Form(""),
    in_review: str = Form(""),
    always_logged: str = Form(""),
    pinned: str = Form(""),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not _csrf_ok(session, csrf):
        return _forbidden()
    form = dict(
        name=name,
        key=key,
        type=type,
        unit=unit,
        scale_min=scale_min,
        scale_max=scale_max,
        scale_labels=scale_labels,
        options=options,
        polarity=polarity,
        category=category,
    )
    try:
        if polarity not in POLARITIES:
            raise TrackerInputError("unknown polarity")
        tracker = capture.create_tracker(
            db,
            key=(key.strip() or slugify(name)),
            name=name.strip(),
            type=type,
            unit=unit.strip() or None,
            scale_min=_float(scale_min) if type == "scale" else None,
            scale_max=_float(scale_max) if type == "scale" else None,
            scale_labels=_scale_labels(scale_labels) if type == "scale" else {},
            options=_options(options) if type == "choice" else [],
            polarity=polarity,
            category=category.strip() or None,
            in_review=in_review == "on",
            always_logged=always_logged == "on",
            pinned=pinned == "on",
        )
    except TrackerInputError as exc:
        db.rollback()
        return trackers_page(request, session, db, error=str(exc), form=form)
    db.commit()
    return RedirectResponse(f"/trackers/{tracker.key}", status_code=status.HTTP_303_SEE_OTHER)


def _tracker_or_404(db: Session, key: str) -> Tracker | None:
    return db.execute(sa.select(Tracker).where(Tracker.key == key)).scalar_one_or_none()


@router.get("/trackers/{key}", response_class=HTMLResponse)
def tracker_detail(
    key: str,
    request: Request,
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    return _render_detail(key, request, session, db)


def _render_detail(
    key: str, request: Request, session: WebSession, db: Session, *, error: str = "", new_token: str = ""
) -> Response:
    """``error`` and ``new_token`` come only from the POST that produced them, never from the URL."""
    tracker = _tracker_or_404(db, key)
    if tracker is None:
        return Response("No such tracker", status_code=status.HTTP_404_NOT_FOUND)
    entries = (
        db.execute(
            sa.select(Observation)
            .where(Observation.tracker_id == tracker.id, Observation.deleted.is_(False))
            .order_by(Observation.observed_at.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    tokens = db.execute(sa.select(ApiToken).where(ApiToken.scope == f"log:{key}").order_by(ApiToken.id)).scalars().all()
    successor = db.get(Tracker, tracker.successor_id) if tracker.successor_id else None
    base_url = str(request.base_url).rstrip("/")
    return templates.TemplateResponse(
        request,
        "tracker_detail.html",
        {
            "t": tracker,
            "entries": [(e, _display(e, tracker), _local(e.observed_at)) for e in entries],
            "locked": capture.has_data(db, tracker),
            "tokens": tokens,
            "new_token": new_token,
            "log_url": f"{base_url}/api/log/{key}",
            "successor": successor,
            "polarities": POLARITIES,
            "type_labels": TYPE_LABELS,
            "csrf": session.csrf_token,
            "error": error,
            "new_id": lambda: str(uuid.uuid4()),
        },
        status_code=422 if error else 200,
    )


@router.post("/trackers/{key}/edit")
def edit_tracker(
    key: str,
    request: Request,
    csrf: str = Form(""),
    name: str = Form(""),
    category: str = Form(""),
    polarity: str = Form("neutral"),
    in_review: str = Form(""),
    always_logged: str = Form(""),
    pinned: str = Form(""),
    archived: str = Form(""),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not _csrf_ok(session, csrf):
        return _forbidden()
    tracker = _tracker_or_404(db, key)
    if tracker is None:
        return Response("No such tracker", status_code=status.HTTP_404_NOT_FOUND)
    try:
        if polarity not in POLARITIES:
            raise TrackerInputError("unknown polarity")
        capture.update_tracker(
            db,
            tracker,
            name=name.strip(),
            category=category.strip() or None,
            polarity=polarity,
            in_review=in_review == "on",
            always_logged=always_logged == "on",
            pinned=pinned == "on",
            archived=archived == "on",
        )
    except TrackerInputError as exc:
        db.rollback()
        return _render_detail(key, request, session, db, error=str(exc))
    db.commit()
    return RedirectResponse(f"/trackers/{key}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/trackers/{key}/version")
def version_tracker(
    key: str,
    request: Request,
    csrf: str = Form(""),
    unit: str = Form(""),
    scale_min: str = Form(""),
    scale_max: str = Form(""),
    options: str = Form(""),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    """Change a locked field by creating a successor; the old tracker keeps its history (R12)."""
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not _csrf_ok(session, csrf):
        return _forbidden()
    tracker = _tracker_or_404(db, key)
    if tracker is None:
        return Response("No such tracker", status_code=status.HTTP_404_NOT_FOUND)
    changes: dict = {"unit": unit.strip() or None}
    try:
        if tracker.type == "scale":
            changes |= {"scale_min": _float(scale_min), "scale_max": _float(scale_max)}
        if tracker.type == "choice":
            changes["options"] = _options(options)
        successor = capture.new_version(db, tracker, **changes)
    except TrackerInputError as exc:
        db.rollback()
        return _render_detail(key, request, session, db, error=str(exc))
    db.commit()
    return RedirectResponse(f"/trackers/{successor.key}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/trackers/{key}/token")
def create_tracker_token(
    key: str,
    request: Request,
    csrf: str = Form(""),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    """A token that can only log this tracker; shown once on the page that answers this post."""
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not _csrf_ok(session, csrf):
        return _forbidden()
    tracker = _tracker_or_404(db, key)
    if tracker is None:
        return Response("No such tracker", status_code=status.HTTP_404_NOT_FOUND)
    raw, _ = auth.create_token(db, f"{tracker.name} (log only)", f"log:{key}")
    db.commit()
    response = _render_detail(key, request, session, db, new_token=raw)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/tokens/{token_id}/revoke")
def revoke_token(
    token_id: int,
    csrf: str = Form(""),
    back: str = Form("/trackers"),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not _csrf_ok(session, csrf):
        return _forbidden()
    auth.revoke_token(db, token_id)
    db.commit()
    target = back if back.startswith("/") and not back.startswith("//") else "/trackers"
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


def _parse_local_time(day: dt.date, hhmm: str) -> dt.datetime | None:
    """'11:35' on a Companion day → an aware datetime; times before the boundary belong to the next date."""
    hhmm = hhmm.strip()
    if not hhmm:
        return None
    try:
        clock = dt.time.fromisoformat(hhmm)
    except ValueError as exc:
        raise TrackerInputError("use a time like 11:35") from exc
    settings = get_settings()
    date = day + dt.timedelta(days=1) if clock < settings.day_boundary else day
    return dt.datetime.combine(date, clock, tzinfo=settings.zone)


@router.post("/log/{key}")
def quick_log(
    key: str,
    request: Request,
    csrf: str = Form(""),
    value: str = Form(""),
    at: str = Form(""),
    day: str = Form(""),
    client_id: str = Form(""),
    back: str = Form("/"),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    """Quick-add from Today, the review or a tracker page. ``client_id`` from the form makes a double tap a no-op."""
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not _csrf_ok(session, csrf):
        return _forbidden()
    tracker = _tracker_or_404(db, key)
    if tracker is None:
        return Response("No such tracker", status_code=status.HTTP_404_NOT_FOUND)
    settings = get_settings()
    target = back if back.startswith("/") and not back.startswith("//") else "/"
    try:
        the_day = dt.date.fromisoformat(day) if day else _today()
        cid = uuid.UUID(client_id) if client_id else None
        capture.log(
            db,
            tracker,
            value if value != "" else None,
            observed_at=_parse_local_time(the_day, at),
            client_id=cid,
            source="web",
            zone=settings.zone,
            boundary=settings.day_boundary,
        )
    except (TrackerInputError, ValueError) as exc:
        db.rollback()
        sep = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{sep}error={str(exc)[:200]}", status_code=status.HTTP_303_SEE_OTHER)
    db.commit()
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/entries/{client_id}/delete")
def delete_entry(
    client_id: uuid.UUID,
    csrf: str = Form(""),
    back: str = Form("/"),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not _csrf_ok(session, csrf):
        return _forbidden()
    capture.delete(db, client_id, source="web")
    db.commit()
    target = back if back.startswith("/") and not back.startswith("//") else "/"
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/review", response_class=HTMLResponse)
def review_page(
    request: Request,
    day: str = "",
    error: str = "",
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    """The evening pass: every in-review tracker, what's logged so far, and 'mark the day reviewed'."""
    if (redirect := _signed_in(session)) is not None:
        return redirect
    today = _today()
    try:
        the_day = dt.date.fromisoformat(day) if day else today
    except ValueError:
        the_day = today
    if the_day > today:
        the_day = today
    entries = capture.entries_for_day(db, the_day)
    by_tracker: dict[int, list] = {}
    for o, t in entries:
        by_tracker.setdefault(t.id, []).append((o, _display(o, t), _local(o.observed_at)))
    rows = (
        db.execute(
            sa.select(Tracker).where(Tracker.archived.is_(False), Tracker.in_review.is_(True)).order_by(Tracker.name)
        )
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "day": the_day,
            "prev": the_day - dt.timedelta(days=1),
            "next": the_day + dt.timedelta(days=1) if the_day < today else None,
            "trackers": rows,
            "by_tracker": by_tracker,
            "reviewed": capture.is_reviewed(db, the_day),
            "csrf": session.csrf_token,
            "error": error,
            "new_id": lambda: str(uuid.uuid4()),
        },
    )


@router.post("/review")
def submit_review(
    day: str = Form(""),
    csrf: str = Form(""),
    reviewed: str = Form("on"),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not _csrf_ok(session, csrf):
        return _forbidden()
    try:
        the_day = dt.date.fromisoformat(day)
    except ValueError:
        return Response("Bad day", status_code=status.HTTP_400_BAD_REQUEST)
    if the_day > _today():
        return Response("Can't review a future day", status_code=status.HTTP_400_BAD_REQUEST)
    capture.set_reviewed(db, the_day, reviewed == "on", source="web")
    db.commit()
    return RedirectResponse(f"/review?day={the_day.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)


def today_capture(db: Session, day: dt.date) -> dict:
    """Pinned trackers and today's entries, for the Today page."""
    pinned = (
        db.execute(
            sa.select(Tracker).where(Tracker.archived.is_(False), Tracker.pinned.is_(True)).order_by(Tracker.name)
        )
        .scalars()
        .all()
    )
    entries = [(o, t, _display(o, t), _local(o.observed_at)) for o, t in capture.entries_for_day(db, day)]
    return {"pinned": pinned, "entries": entries, "new_id": lambda: str(uuid.uuid4())}
