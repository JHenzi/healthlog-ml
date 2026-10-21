"""The good-day page and the Overview card: sign-in required, synthetic data renders, labels escaped (D2/D3)."""

from __future__ import annotations

import datetime as dt
import re

import pytest

from app import auth
from app.auth import now_utc
from app.config import get_settings
from app.goodday import FEATURE
from app.models import DailyFeature, FeatureDef, Insight
from app.timeutil import current_day

PASSWORD = "good days page password"


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
def scored(db):
    settings = get_settings()
    today = current_day(now_utc(), settings.zone, settings.day_boundary)
    for feature, label in (("hl.step_count", "Steps"), ("sleep.total_h", "Sleep"), ("hl.hrv", "<b>HRV</b>")):
        db.add(FeatureDef(feature=feature, label=label, unit=None, source="healthlog", kind="continuous"))
        for k in range(1, 21):
            db.add(DailyFeature(day=today - dt.timedelta(days=k), feature=feature, value=float(30 - k)))
    db.add(FeatureDef(feature=FEATURE, label="Good-day score", unit=None, source="goodday", kind="continuous"))
    db.add(
        Insight(
            kind="association",
            horizon="day",
            feature_a=FEATURE,
            feature_b="hl.hrv",
            lag=0,
            method="spearman",
            effect=0.6,
            p=0.001,
            p_adj=0.01,
            n=20,
            strength="strong",
            score=1.0,
            sentence="Days with higher good-day score tend to have higher HRV (20 days, strong).",
            details={},
        )
    )
    db.flush()


def test_the_page_requires_sign_in(client):
    assert client.get("/good-days", follow_redirects=False).status_code == 303


def test_the_page_shows_parts_best_days_and_what_they_share(signed_in, scored):
    html = signed_in.get("/good-days").text
    assert "What your best days have in common" in html
    assert "higher HRV" in html and "&lt;b&gt;HRV&lt;/b&gt;: median" in html and "<b>HRV</b>" not in html
    assert "The top quarter of your 20 scored days" in html
    assert html.count('class="goodday-parts"') >= 1 and "no data" in html  # water and mood: no data, not 0


def test_the_overview_has_the_good_day_card(signed_in, scored):
    html = signed_in.get("/").text
    assert "Good day" in html and "/ 100 yesterday" in html and "Higher than 95% of your 20 scored days" in html


def test_without_scores_the_page_says_what_it_needs(signed_in):
    html = signed_in.get("/good-days").text
    assert "Nothing stands out yet" in html and "needs at least 12" in html
    assert "No score for yesterday" in signed_in.get("/").text
