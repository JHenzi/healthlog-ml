"""The ``back`` form field must never send anyone off the site (CodeQL py/url-redirection)."""

from __future__ import annotations

import pytest

from app.web_trackers import _back


@pytest.mark.parametrize("path", ["/", "/trackers", "/review?day=2026-10-31#mood"])
def test_same_site_paths_are_kept(path):
    assert _back(path) == path


@pytest.mark.parametrize(
    "target",
    ["", "https://evil.example", "//evil.example", "/\\evil.example", "/\\/evil.example", "/x\\y", "/\r\nX: y", "/\tx"],
)
def test_anything_else_falls_back(target):
    assert _back(target, "/home") == "/home"
