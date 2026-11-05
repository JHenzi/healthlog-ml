"""Analysis run against the feature table, plus the Insights pages and API (synthetic data, R4)."""

from __future__ import annotations

import datetime as dt
import re

import numpy as np
import pytest
from sqlalchemy import delete, func, select

from app import auth
from app.analysis import run as analysis
from app.models import DailyFeature, EarlierInsight, FeatureDef, Insight

START = dt.date(2026, 6, 1)
DAYS = 100
TODAY = START + dt.timedelta(days=DAYS)
PASSWORD = "insights page password"


@pytest.fixture
def planted(db):
    """Steps and sleep with a planted same-day link; an unrelated mood series."""
    rng = np.random.default_rng(42)
    steps = 7000 + 1500 * rng.normal(size=DAYS)
    sleep = 7 + 0.0004 * (steps - 7000) + 0.4 * rng.normal(size=DAYS)
    noise = rng.normal(size=DAYS)
    defs = [
        FeatureDef(
            feature="hl.step_count",
            label="Steps",
            unit="count",
            source="healthlog",
            kind="continuous",
            family="activity",
        ),
        FeatureDef(
            feature="sleep.total_h", label="Sleep (total)", unit="h", source="sleep", kind="continuous", family="sleep"
        ),
        FeatureDef(
            feature="mood.valence_mean",
            label="Mood valence (mean)",
            unit=None,
            source="mood",
            kind="continuous",
            family="mood",
        ),
    ]
    db.add_all(defs)
    for i in range(DAYS):
        day = START + dt.timedelta(days=i)
        db.add_all(
            [
                DailyFeature(day=day, feature="hl.step_count", value=float(steps[i])),
                DailyFeature(day=day, feature="sleep.total_h", value=float(sleep[i])),
                DailyFeature(day=day, feature="mood.valence_mean", value=float(noise[i])),
            ]
        )
    db.flush()


def test_run_stores_ranked_insights_with_evidence(db, planted):
    result = analysis.run(db, TODAY)
    assert result.insights >= 1
    rows = db.execute(select(Insight).order_by(Insight.score.desc())).scalars().all()
    link = [
        i for i in rows if i.kind == "association" and {i.feature_a, i.feature_b} == {"hl.step_count", "sleep.total_h"}
    ]
    assert link and link[0].lag == 0 and link[0].effect > 0
    assert "days" in link[0].sentence and link[0].p_adj <= 0.10
    assert not any(i.kind == "association" and "mood.valence_mean" in (i.feature_a, i.feature_b) for i in rows)


def test_run_replaces_previous_insights(db, planted):
    analysis.run(db, TODAY)
    first = db.execute(select(func.count()).select_from(Insight)).scalar_one()
    analysis.run(db, TODAY)
    assert db.execute(select(func.count()).select_from(Insight)).scalar_one() == first


def _steps_sleep(rows):
    return [i for i in rows if {i.feature_a, i.feature_b} == {"hl.step_count", "sleep.total_h"}]


def test_a_finding_that_drops_out_is_kept_as_earlier_and_moves_back_when_it_returns(db, planted):
    """Roadmap B17: the list is still replaced every run, but a dropped finding stays visible, with its days."""
    analysis.run(db, TODAY - dt.timedelta(days=1))
    analysis.run(db, TODAY)
    link = _steps_sleep(db.execute(select(Insight)).scalars().all())[0]
    assert link.first_seen == TODAY - dt.timedelta(days=1) and link.last_seen == TODAY  # carried over

    saved = db.execute(select(DailyFeature).where(DailyFeature.feature == "sleep.total_h")).scalars().all()
    kept = [(d.day, d.value) for d in saved]
    db.execute(delete(DailyFeature).where(DailyFeature.feature == "sleep.total_h"))
    later = TODAY + dt.timedelta(days=1)
    analysis.run(db, later)
    assert not _steps_sleep(db.execute(select(Insight)).scalars().all())
    earlier = _steps_sleep(db.execute(select(EarlierInsight)).scalars().all())
    assert earlier and earlier[0].last_held == TODAY and earlier[0].dropped_on == later
    assert earlier[0].first_seen == TODAY - dt.timedelta(days=1) and earlier[0].sentence == link.sentence

    db.add_all(DailyFeature(day=day, feature="sleep.total_h", value=value) for day, value in kept)
    db.flush()
    analysis.run(db, later + dt.timedelta(days=1))
    assert _steps_sleep(db.execute(select(Insight)).scalars().all())
    assert not _steps_sleep(db.execute(select(EarlierInsight)).scalars().all())


def test_earlier_discoveries_expire(db, planted):
    analysis.run(db, TODAY)
    db.execute(delete(DailyFeature).where(DailyFeature.feature == "sleep.total_h"))
    analysis.run(db, TODAY)
    assert db.execute(select(func.count()).select_from(EarlierInsight)).scalar_one() >= 1
    analysis.run(db, TODAY + dt.timedelta(days=200))
    assert db.execute(select(func.count()).select_from(EarlierInsight)).scalar_one() == 0


def _sign_in(client, db):
    auth.set_password(db, PASSWORD)
    db.flush()
    page = client.get("/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    client.post("/login", data={"password": PASSWORD, "csrf": csrf})


def test_insights_pages_and_api(client, db, planted):
    analysis.run(db, TODAY)
    assert client.get("/insights", follow_redirects=False).status_code == 303  # signed out
    _sign_in(client, db)
    page = client.get("/insights")
    assert page.status_code == 200 and "Relationships" in page.text
    insight_id = db.execute(select(Insight.id).where(Insight.kind == "association")).scalars().first()
    detail = client.get(f"/insights/{insight_id}")
    assert detail.status_code == 200 and "Benjamini-Hochberg" in detail.text
    assert client.get("/insights/999999").status_code == 404
    assert "Earlier discoveries" not in page.text and "since " in page.text

    db.execute(delete(DailyFeature).where(DailyFeature.feature == "sleep.total_h"))
    analysis.run(db, TODAY + dt.timedelta(days=1))
    page = client.get("/insights")
    assert "Earlier discoveries" in page.text and "no longer clears the bar" in page.text

    raw, _ = auth.create_token(db, "t", "read")
    api = client.get("/api/insights", headers={"Authorization": f"Bearer {raw}"}).json()
    assert "insights" in api and api["earlier"] and {"sentence", "n", "strength", "last_held"} <= set(api["earlier"][0])
    log_only, _ = auth.create_token(db, "t2", "log:coffee")
    assert client.get("/api/insights", headers={"Authorization": f"Bearer {log_only}"}).status_code == 403
