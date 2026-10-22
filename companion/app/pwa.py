"""The installable web app: manifest, service worker and the static-file version (design §7, M4 part 2).

Added to the Home Screen, the Companion runs full screen (no Safari toolbar). The service worker
(``web/static/sw.js``) keeps a saved copy of each page, shows it at once and refreshes it in the background;
``rendered_at`` in every page lets the page say how old the copy is. Static files carry ``?v=<version>`` so the
phone can keep them for a long time and still gets new ones after a deploy.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from functools import cache
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response

STATIC_DIR = Path(__file__).resolve().parents[1] / "web" / "static"
THEME = "#4f7a4a"  # moss, warm.css --color-accent
BACKGROUND = "#f6f1e7"  # paper, warm.css --color-bg

router = APIRouter()


@cache
def static_version() -> str:
    """A short hash of every static file: changes whenever one does, so ``?v=`` busts the phone's cache."""
    h = hashlib.sha256()
    for path in sorted(p for p in STATIC_DIR.rglob("*") if p.is_file()):
        h.update(path.relative_to(STATIC_DIR).as_posix().encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:12]


def rendered_at() -> str:
    """When the page was rendered (UTC, ISO 8601): a saved copy says its age from this."""
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


MANIFEST = {
    "name": "Companion",
    "short_name": "Companion",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": BACKGROUND,
    "theme_color": THEME,
    "icons": [
        {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "/static/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}


@router.get("/manifest.webmanifest", include_in_schema=False)
def manifest() -> Response:
    return Response(json.dumps(MANIFEST), media_type="application/manifest+json")


@router.get("/sw.js", include_in_schema=False)
def service_worker() -> Response:
    """Served from the root so it can look after every page; never cached, so a new version is picked up."""
    body = (STATIC_DIR / "sw.js").read_text().replace("__VERSION__", static_version())
    return Response(body, media_type="text/javascript", headers={"Cache-Control": "no-cache"})
