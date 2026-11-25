"""The Trends page and pins (roadmap B20, app/signals.py): the long view of every series, and the ones you watch."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from . import auth, signals
from .db import get_db
from .glance import icon_for
from .models import FeatureDef, WebSession
from .web import _signed_in, _today, current_session, templates
from .web_trackers import _back

router = APIRouter()


@router.get("/trends", response_class=HTMLResponse)
def trends_page(
    request: Request,
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    pins, rows = signals.load_trends(db, _today())
    return templates.TemplateResponse(
        request,
        "trends.html",
        {"pins": pins, "rows": rows, "csrf": session.csrf_token, "icon_for": icon_for, "max_pins": signals.MAX_PINS},
    )


@router.post("/pins/{feature}")
def toggle_pin(
    feature: str,
    csrf: str = Form(""),
    back: str = Form("/trends"),
    session: WebSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    if (redirect := _signed_in(session)) is not None:
        return redirect
    if not auth.constant_time_equals(csrf, session.csrf_token):
        return Response("CSRF check failed", status_code=status.HTTP_403_FORBIDDEN)
    if db.get(FeatureDef, feature) is None:
        return Response("No such series", status_code=status.HTTP_404_NOT_FOUND)
    signals.toggle_pin(db, feature)
    db.commit()
    return RedirectResponse(_back(back, "/trends"), status_code=status.HTTP_303_SEE_OTHER)
