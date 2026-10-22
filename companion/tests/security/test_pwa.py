"""The installable app: manifest and service worker are public and fixed, pages say when they were rendered,
static files are versioned for long caching, and the CSP still allows only our own scripts (D2/D3)."""

from __future__ import annotations

import re

from app import pwa


def test_manifest_is_public_and_full_screen(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    assert r.json()["display"] == "standalone" and r.json()["start_url"] == "/"


def test_service_worker_carries_the_static_version_and_is_never_cached(client):
    r = client.get("/sw.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "no-cache"
    assert f'const VERSION = "{pwa.static_version()}"' in r.text and "__VERSION__" not in r.text


def test_the_service_worker_leaves_the_api_sign_in_and_posts_to_the_server(client):
    sw = client.get("/sw.js").text
    assert 'url.pathname.startsWith("/api/") || isSignIn(url)' in sw
    assert 'request.method !== "GET"' in sw


def test_pages_link_versioned_files_and_say_when_they_were_rendered(client):
    html = client.get("/login").text
    v = pwa.static_version()
    assert f'href="/static/style.css?v={v}"' in html and f'src="/static/app.js?v={v}"' in html
    assert re.search(r'<meta name="rendered-at" content="\d{4}-\d\d-\d\dT[^"]+">', html)
    assert 'rel="manifest"' in html and "viewport-fit=cover" in html


def test_versioned_static_files_are_kept_long(client):
    v = pwa.static_version()
    assert "immutable" in client.get(f"/static/app.js?v={v}").headers["cache-control"]
    assert "immutable" not in client.get("/static/app.js").headers["cache-control"]


def test_csp_still_allows_only_our_own_scripts(client):
    assert "script-src 'self'" in client.get("/login").headers["content-security-policy"]
