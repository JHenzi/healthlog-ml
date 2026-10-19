"""JSON API, authenticated by scoped bearer tokens (Shortcuts can't do interactive login)."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import auth, capture, today
from .auth import TRACKER_KEY_RE
from .config import get_settings
from .db import get_db
from .models import ApiToken, Insight, Observation, Tracker
from .timeutil import current_day
from .trackers import TrackerInputError

router = APIRouter(prefix="/api")


def require_scope(needed: str) -> Callable[..., ApiToken]:
    def dependency(request: Request, db: Session = Depends(get_db)) -> ApiToken:
        header = request.headers.get("authorization", "")
        raw = header[7:].strip() if header.lower().startswith("bearer ") else None
        token = auth.token_for(db, raw)
        if token is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing token")
        if not auth.scope_allows(token.scope, needed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "token scope does not allow this")
        db.commit()  # persist last_used_at
        return token

    return dependency


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(sa.text("SELECT 1"))
    return {"status": "ok"}


@router.get("/today")
def get_today(db: Session = Depends(get_db), _token: ApiToken = Depends(require_scope("read"))) -> dict:
    settings = get_settings()
    day = current_day(dt.datetime.now(dt.UTC), settings.zone, settings.day_boundary)
    view = today.load_today(db, settings.zone, settings.day_boundary, day)
    return {"day": view.day.isoformat(), "sentences": view.sentences, "problems": view.problems}


@router.get("/insights")
def get_insights(db: Session = Depends(get_db), _token: ApiToken = Depends(require_scope("read"))) -> dict:
    rows = db.execute(sa.select(Insight).order_by(Insight.score.desc())).scalars().all()
    return {
        "insights": [
            {
                "id": i.id,
                "kind": i.kind,
                "horizon": i.horizon,
                "sentence": i.sentence,
                "feature_a": i.feature_a,
                "feature_b": i.feature_b,
                "lag": i.lag,
                "method": i.method,
                "effect": i.effect,
                "p_adj": i.p_adj,
                "n": i.n,
                "strength": i.strength,
                "computed_at": i.computed_at.isoformat(),
            }
            for i in rows
        ]
    }


# --- capture (M4) -----------------------------------------------------------


def _bearer(request: Request, db: Session) -> ApiToken:
    header = request.headers.get("authorization", "")
    raw = header[7:].strip() if header.lower().startswith("bearer ") else None
    token = auth.token_for(db, raw)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing token")
    return token


class LogRequest(BaseModel):
    """``value`` per the tracker's type (count default 1, check default yes); ``time`` ISO 8601 with offset."""

    value: float | int | str | bool | None = None
    time: dt.datetime | None = None
    client_id: uuid.UUID | None = None
    source: str = Field(default="api", max_length=32)


def _entry_json(o: Observation, t: Tracker) -> dict:
    return {
        "client_id": str(o.client_id),
        "tracker": t.key,
        "value": o.value_text if o.value_text is not None else o.value_num,
        "time": o.observed_at.isoformat(),
        "day": o.day.isoformat(),
        "tag": o.tag,
    }


@router.post("/log/{key}")
def log_entry(key: str, body: LogRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    """Log one entry. A ``log:<key>`` token can log only that tracker (design §5.3)."""
    token = _bearer(request, db)
    if not TRACKER_KEY_RE.match(key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such tracker")
    if not auth.scope_allows(token.scope, f"log:{key}"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "token scope does not allow logging this tracker")
    tracker = db.execute(sa.select(Tracker).where(Tracker.key == key)).scalar_one_or_none()
    if tracker is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such tracker")
    settings = get_settings()
    try:
        logged = capture.log(
            db,
            tracker,
            body.value,
            observed_at=body.time,
            client_id=body.client_id,
            source=body.source,
            zone=settings.zone,
            boundary=settings.day_boundary,
        )
    except TrackerInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    db.commit()
    response.status_code = status.HTTP_201_CREATED if logged.created else status.HTTP_200_OK
    local = logged.observation.observed_at.astimezone(settings.zone)
    return {
        **_entry_json(logged.observation, tracker),
        "created": logged.created,
        # What a Shortcut speaks back, so a misheard entry is caught immediately.
        "message": f"Logged {tracker.name} at {local:%H:%M}",
    }


@router.get("/trackers")
def list_trackers(db: Session = Depends(get_db), _token: ApiToken = Depends(require_scope("read"))) -> dict:
    rows = db.execute(sa.select(Tracker).where(Tracker.archived.is_(False)).order_by(Tracker.name)).scalars()
    return {
        "trackers": [
            {
                "key": t.key,
                "name": t.name,
                "type": t.type,
                "unit": t.unit,
                "scale": [t.scale_min, t.scale_max] if t.type == "scale" else None,
                "options": list(t.options or []) if t.type == "choice" else None,
                "pinned": t.pinned,
            }
            for t in rows
        ]
    }


@router.delete("/entries/{client_id}")
def delete_entry(client_id: uuid.UUID, request: Request, db: Session = Depends(get_db)) -> dict:
    token = _bearer(request, db)
    if token.scope != "all":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "deleting needs a token with scope 'all'")
    if not capture.delete(db, client_id, source="api"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such entry")
    db.commit()
    return {"deleted": str(client_id)}
