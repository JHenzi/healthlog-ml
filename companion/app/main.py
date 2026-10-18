"""FastAPI application: pages (session cookie) and API (scoped tokens)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from . import api, upstream, web, web_trackers
from .db import session_scope

log = logging.getLogger("companion")

WEB_DIR = Path(__file__).resolve().parents[1] / "web"

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def log_contract_problems() -> None:
    """Startup check (R3): a broken contract is logged loudly and shown on the page, never fatal."""
    try:
        with session_scope() as db:
            problems = upstream.check_upstream(db)
    except Exception as exc:  # noqa: BLE001 - the app must still start to show the problem
        log.error("upstream contract check could not run: %s", exc)
        return
    for problem in problems:
        log.warning("upstream contract: %s", problem)
    if not problems:
        log.info("upstream contract: ok (%d tables)", len(upstream.CONTRACT))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log_contract_problems()
    yield


def create_app(*, check_on_startup: bool = True) -> FastAPI:
    app = FastAPI(
        title="HealthLog Companion",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan if check_on_startup else None,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.include_router(api.router)
    app.include_router(web.router)
    app.include_router(web_trackers.router)
    return app


app = create_app()
