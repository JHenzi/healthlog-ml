"""R18: every route under /api is documented in docs/api.md, and every documented route exists (risks.md F6)."""

from __future__ import annotations

import re

from app.main import create_app
from tests.conftest import COMPANION_DIR

HEADING = re.compile(r"^### `([A-Z]+) (/api/\S*)`", re.MULTILINE)


def _served() -> set[tuple[str, str]]:
    """From the app's OpenAPI schema (FastAPI no longer lists included routes on ``app.routes``)."""
    paths = create_app(check_on_startup=False).openapi()["paths"]
    return {
        (method.upper(), re.sub(r"\{[^}]+\}", "{}", path))
        for path, ops in paths.items()
        if path.startswith("/api/")
        for method in ops
    }


def _documented() -> set[tuple[str, str]]:
    text = (COMPANION_DIR / "docs" / "api.md").read_text()
    return {(method, re.sub(r"<[^>]+>", "{}", path)) for method, path in HEADING.findall(text)}


def test_every_api_route_is_documented_and_every_documented_route_exists():
    served, documented = _served(), _documented()
    assert served, "no /api routes found"
    assert served - documented == set(), "add these routes to docs/api.md (R18)"
    assert documented - served == set(), "docs/api.md lists routes the app doesn't serve (R18)"
