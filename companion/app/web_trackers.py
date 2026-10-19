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
from .trackers import (
    COMMON_TYPES,
    DAY_TAGS_KEY,
    DEFAULT_SCALE,
    TYPE_HINTS,
    TYPE_LABELS,
    TrackerInputError,
    parse_tags,
    slugify,
    tag_slug,
)
from .web import _signed_in, _today, current_session, templates

router = APIRouter()

# Ideas for a new tracker, by the kind of life they fit. Choosing one fills in the form; nothing is created
# until you tap Create. Caffeine, alcohol, water and mood are left out: Apple Health already records them.
IDEAS = (
    (
        "At work",
        (
            {"name": "Work day", "type": "scale"},
            {"name": "Focus", "type": "scale"},
            {"name": "Meetings", "type": "count", "unit": "meetings"},
            {"name": "Deep work", "type": "duration"},
        ),
    ),
    (
        "Training",
        (
            {"name": "Soreness", "type": "scale"},
            {"name": "Motivation", "type": "scale"},
            {"name": "Stretched", "type": "check"},
        ),
    ),
    (
        "Pain",
        (
            {"name": "Headache", "type": "moment"},
            {"name": "Pain", "type": "scale"},
            {"name": "Back pain", "type": "scale"},
        ),
    ),
    (
        "Hobbies",
        (
            {"name": "Crochet", "type": "duration"},
            {"name": "Reading", "type": "count", "unit": "pages"},
            {"name": "Articles proofread", "type": "count", "unit": "articles"},
        ),
    ),
    (
        "Anyone",
        (
            {"name": "Energy", "type": "scale"},
            {"name": "Productivity", "type": "scale"},
            {"name": "Screens after 10pm", "type": "check"},
        ),
    ),
)
IDEAS_BY_SLUG = {slugify(i["name"]): i for _, ideas in IDEAS for i in ideas}
# Tags describe the day ("meeting heavy", "travel"); each one is its own yes/no series in the analysis.
TAG_IDEAS = (
    ("Work", ("meeting heavy", "in-fighting", "deadline", "focused", "good teamwork", "worked from home", "on call")),
    ("Body", ("headache", "back pain", "sick", "allergies", "hungover")),
    ("Life", ("travel", "social", "late night", "family time", "hosting", "kids up at night", "alone time")),
)


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


def _display(o: Observation, t: Tracker) -> str:
    if o.tag is not None:
        names = {tag_slug(x): x for x in t.tags or ()}
        return f"#{names.get(o.tag, o.tag.replace('_', ' '))}"
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
    idea: str = "",
    tag_error: str = "",
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
    keys = {t.key for t in rows}
    if form is None and (picked := IDEAS_BY_SLUG.get(idea)) is not None:
        form = dict(picked)
    day = capture.day_tags(db)
    have = {tag_slug(t) for t in day.tags} if day else set()
    return templates.TemplateResponse(
        request,
        "trackers.html",
        {
            "trackers": [t for t in rows if not t.archived and t.key != DAY_TAGS_KEY],
            "archived": [t for t in rows if t.archived and t.key != DAY_TAGS_KEY],
            "day": day,
            "tagged": capture.tags_for_day(db, _today()).get(day.id, set()) if day else set(),
            "tag_ideas": [(who, [x for x in tags if tag_slug(x) not in have]) for who, tags in TAG_IDEAS],
            "counts": counts,
            "type_labels": TYPE_LABELS,
            "type_hints": list(TYPE_HINTS.items()),
            "common_types": COMMON_TYPES,
            "ideas": [
                (who, [(slugify(i["name"]), i) for i in ideas if slugify(i["name"]) not in keys])
                for who, ideas in IDEAS
            ],
            "csrf": session.csrf_token,
            "error": error,
            "tag_error": tag_error,
            "form": form or {},
        },
        status_code=422 if error else 200,
    )


@router.post("/trackers")
def create_tracker(
    request: Request,
    csrf: str = Form(""),
    name: str = Form(""),
    type: str = Form("scale"),
    unit: str = Form(""),
    options: str = Form(""),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not _csrf_ok(session, csrf):
        return _forbidden()
    form = dict(name=name, type=type, unit=unit, options=options)
    try:
        # Assume what we can: the key comes from the name, every rating is 1–10 with 10 high, and a new
        # tracker shows up in Quick add and the daily log. Which way is "better" is left to the data.
        if type == "tags" or slugify(name) == DAY_TAGS_KEY:
            raise TrackerInputError("tags belong to the day: add them under Day tags")
        tracker = capture.create_tracker(
            db,
            key=slugify(name),
            name=name.strip(),
            type=type,
            unit=(unit.strip() or None) if type in ("count", "quantity") else None,
            scale_min=DEFAULT_SCALE[0] if type == "scale" else None,
            scale_max=DEFAULT_SCALE[1] if type == "scale" else None,
            options=_options(options) if type == "choice" else [],
            in_review=True,
            pinned=True,
        )
    except TrackerInputError as exc:
        db.rollback()
        return trackers_page(request, session, db, error=str(exc), form=form, idea="", tag_error="")
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
            "tagged": capture.tags_for_day(db, _today()).get(tracker.id, set()),
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
    always_logged: str = Form(""),
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
        capture.update_tracker(
            db,
            tracker,
            name=name.strip(),
            category=category.strip() or None,
            always_logged=always_logged == "on",
            archived=archived == "on",
        )
    except TrackerInputError as exc:
        db.rollback()
        return _render_detail(key, request, session, db, error=str(exc))
    db.commit()
    return RedirectResponse(f"/trackers/{key}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/day-tags")
def add_day_tags(
    csrf: str = Form(""),
    tags: str = Form(""),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    """Add one or more tags (separated by commas) to the day's list."""
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not _csrf_ok(session, csrf):
        return _forbidden()
    try:
        capture.add_day_tags(db, parse_tags(tags))
    except TrackerInputError as exc:
        db.rollback()
        return RedirectResponse(f"/trackers?tag_error={str(exc)[:200]}#tags", status_code=status.HTTP_303_SEE_OTHER)
    db.commit()
    return RedirectResponse("/trackers#tags", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/day-tags/remove")
def remove_day_tag(
    csrf: str = Form(""),
    tag: str = Form(""),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not _csrf_ok(session, csrf):
        return _forbidden()
    capture.remove_day_tag(db, tag)
    db.commit()
    return RedirectResponse("/trackers#tags", status_code=status.HTTP_303_SEE_OTHER)


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
    target = _back(back, "/trackers")
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


def _when(day: dt.date, hhmm: str) -> dt.datetime | None:
    """The entry's time: as typed, else now for today and midday for an earlier day (so it lands on that day)."""
    if hhmm.strip() or day >= _today():
        return _parse_local_time(day, hhmm)
    return _parse_local_time(day, "12:00")


def _back(back: str, default: str = "/") -> str:
    return back if back.startswith("/") and not back.startswith("//") else default


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
    target = _back(back)
    try:
        the_day = dt.date.fromisoformat(day) if day else _today()
        cid = uuid.UUID(client_id) if client_id else None
        capture.log(
            db,
            tracker,
            value if value != "" else None,
            observed_at=_when(the_day, at),
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


@router.post("/log/{key}/tag")
def toggle_tag(
    key: str,
    csrf: str = Form(""),
    tag: str = Form(""),
    day: str = Form(""),
    back: str = Form("/"),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    """Tap a tag to pick it for the day; tap it again to unpick it."""
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not _csrf_ok(session, csrf):
        return _forbidden()
    tracker = _tracker_or_404(db, key)
    if tracker is None:
        return Response("No such tracker", status_code=status.HTTP_404_NOT_FOUND)
    settings = get_settings()
    target = _back(back)
    try:
        the_day = dt.date.fromisoformat(day) if day else _today()
        if the_day > _today():
            raise TrackerInputError("that day is in the future")
        capture.toggle_tag(
            db,
            tracker,
            tag,
            the_day,
            observed_at=_when(the_day, ""),
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
    target = _back(back)
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
        if o.tag is None:  # picked tags show as pressed chips instead
            by_tracker.setdefault(t.id, []).append((o, _display(o, t), _local(o.observed_at)))
    rows = _active(db)
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "day_tags": capture.day_tags(db),
            "day": the_day,
            "prev": the_day - dt.timedelta(days=1),
            "next": the_day + dt.timedelta(days=1) if the_day < today else None,
            "trackers": [t for t in rows if t.key != DAY_TAGS_KEY],
            "by_tracker": by_tracker,
            "tagged": capture.tags_for_day(db, the_day),
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


def _active(db: Session) -> list[Tracker]:
    """Every tracker that isn't archived: all of them show in Quick add and the daily log."""
    return list(db.execute(sa.select(Tracker).where(Tracker.archived.is_(False)).order_by(Tracker.name)).scalars())


def today_capture(db: Session, day: dt.date) -> dict:
    """Trackers, the day's tags and today's entries, for the Overview page."""
    rows = _active(db)
    entries = [
        (o, t, _display(o, t), _local(o.observed_at)) for o, t in capture.entries_for_day(db, day) if o.tag is None
    ]
    return {
        "trackers": [t for t in rows if t.key != DAY_TAGS_KEY],
        "day_tags": next((t for t in rows if t.key == DAY_TAGS_KEY), None),
        "entries": entries,
        "tagged": capture.tags_for_day(db, day),
        "new_id": lambda: str(uuid.uuid4()),
    }
