"""The Trends page, pins and the Overview card: sign-in, CSRF, known series only, same-site redirects."""

from __future__ import annotations

import re

import pytest

from app import auth, signals
from app.models import FeatureDef

PASSWORD = "trends page password"


def _csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def signed_in(client, db):
    auth.set_password(db, PASSWORD)
    db.add(FeatureDef(feature="hl.step_count", label="Steps", unit="count", source="healthlog", kind="continuous"))
    db.add(FeatureDef(feature="hl.flights_climbed", label="Flights", unit="count", source="healthlog", kind="count"))
    db.flush()
    page = client.get("/login")
    client.post("/login", data={"password": PASSWORD, "csrf": _csrf(page.text)})
    return client


def test_the_page_and_pinning_need_sign_in(client):
    assert client.get("/trends", follow_redirects=False).status_code == 303
    assert client.post("/pins/hl.step_count", data={"csrf": "x"}, follow_redirects=False).status_code == 303


def test_the_page_lists_series_with_up_and_down_only(signed_in):
    html = signed_in.get("/trends").text
    assert "Trends" in html and "Steps" in html
    assert "never better or worse" in html


def test_pinning_needs_csrf_and_a_known_series(signed_in, db):
    csrf = _csrf(signed_in.get("/trends").text)
    assert signed_in.post("/pins/hl.step_count", data={"csrf": "forged"}).status_code == 403
    assert signed_in.post("/pins/no.such", data={"csrf": csrf}).status_code == 404
    back = {"csrf": csrf, "back": "/metrics/hl.flights_climbed"}
    r = signed_in.post("/pins/hl.flights_climbed", data=back, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/metrics/hl.flights_climbed"
    assert "hl.flights_climbed" in signals.load_pins(db)
    signed_in.post("/pins/hl.flights_climbed", data={"csrf": csrf})
    assert "hl.flights_climbed" not in signals.load_pins(db)
    # A preset pin unpins on the first tap, and the choice sticks.
    signed_in.post("/pins/hl.step_count", data={"csrf": csrf})
    assert "hl.step_count" not in signals.load_pins(db)


def test_pinning_never_redirects_off_site(signed_in):
    csrf = _csrf(signed_in.get("/trends").text)
    r = signed_in.post("/pins/hl.step_count", data={"csrf": csrf, "back": "//evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/trends"


def test_the_overview_has_the_card(signed_in):
    html = signed_in.get("/").text
    assert 'id="noticing"' in html and "Worth noticing" in html
