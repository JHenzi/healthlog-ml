"""JSON API, authenticated by scoped bearer tokens (Shortcuts can't do interactive login)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from . import auth, today
from .config import get_settings
from .db import get_db
from .models import ApiToken, Insight
from .timeutil import current_day

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
