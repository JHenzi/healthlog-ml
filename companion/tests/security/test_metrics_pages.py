"""Metrics pages: sign-in required, CSRF on every write, user-visible text escaped (risks.md D2/D3)."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text

from app import auth
from app.models import DailyFeature, FeatureDef, MetricSetting

PASSWORD = "metrics page password"


def _csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def signed_in(client, db):
    auth.set_password(db, PASSWORD)
    db.flush()
    page = client.get("/login")
    client.post("/login", data={"password": PASSWORD, "csrf": _csrf(page.text)})
    return client


@pytest.fixture
def a_metric(db):
    db.add(MetricSetting(metric="step_count", display_name="<b>Steps</b>", unit="count", aggregation="sum"))
    db.add(
        FeatureDef(feature="hl.step_count", label="<b>Steps</b>", unit="count", source="healthlog", kind="continuous")
    )
    db.add(DailyFeature(day="2026-10-10", feature="hl.step_count", value=1234))
    db.flush()


@pytest.mark.parametrize("path", ["/metrics", "/metrics/hl.step_count"])
def test_pages_require_sign_in(client, path):
    assert client.get(path, follow_redirects=False).headers["location"] == "/login"


@pytest.mark.parametrize("path", ["/metrics/hl.step_count/settings", "/metrics/hl.step_count/reset", "/refresh"])
def test_writes_require_csrf(signed_in, a_metric, path):
    assert signed_in.post(path, data={"csrf": "forged", "aggregation": "avg"}).status_code == 403


def test_metric_pages_render_and_escape_labels(signed_in, a_metric):
    listing = signed_in.get("/metrics")
    assert listing.status_code == 200
    assert "<b>Steps</b>" not in listing.text and "&lt;b&gt;Steps&lt;/b&gt;" in listing.text
    detail = signed_in.get("/metrics/hl.step_count")
    assert detail.status_code == 200 and "Daily value" in detail.text


def test_unknown_metric_is_404(signed_in):
    assert signed_in.get("/metrics/hl.nope").status_code == 404


def test_saving_settings_persists_and_rebuilds(signed_in, db, a_metric):
    csrf = _csrf(signed_in.get("/metrics/hl.step_count").text)
    response = signed_in.post(
        "/metrics/hl.step_count/settings",
        data={
            "csrf": csrf,
            "aggregation": "max",
            "analyse": "on",
            "min_value": "",
            "max_value": "50000",
            "source_priority": "Watch, iPhone",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    row = db.execute(
        text(
            "SELECT aggregation, max_value, source_priority, user_edited "
            "FROM companion.metric_settings WHERE metric = 'step_count'"
        )
    ).one()
    assert tuple(row) == ("max", 50000.0, ["Watch", "iPhone"], True)


def test_bad_settings_show_an_error(signed_in, a_metric):
    csrf = _csrf(signed_in.get("/metrics/hl.step_count").text)
    response = signed_in.post(
        "/metrics/hl.step_count/settings",
        data={"csrf": csrf, "aggregation": "sum", "min_value": "10", "max_value": "1"},
    )
    assert "lower bound is above the upper bound" in response.text


def test_outside_and_almanac_series_are_listed(signed_in, db):
    db.add(
        FeatureDef(
            feature="weather.temp_mean", label="Temperature (mean)", unit="°C", source="weather", kind="continuous"
        )
    )
    db.add(FeatureDef(feature="almanac.moon", label="Moon (share lit)", unit="%", source="almanac", kind="continuous"))
    db.add(DailyFeature(day="2026-10-10", feature="weather.temp_mean", value=11.0))
    db.add(DailyFeature(day="2026-10-10", feature="almanac.moon", value=40.0))
    db.flush()
    listing = signed_in.get("/metrics").text
    assert "Weather" in listing and "Temperature (mean)" in listing
    assert "Almanac" in listing and "Moon (share lit)" in listing
    assert signed_in.get("/metrics/almanac.moon").status_code == 200
