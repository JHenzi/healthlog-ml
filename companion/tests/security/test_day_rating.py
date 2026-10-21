"""The built-in day rating: on the Overview and in Capture, created on first use, fixed, and a feature (R7, R17)."""

from __future__ import annotations

import datetime as dt
import re

import pytest
from sqlalchemy import select

from app import auth, dayrating, features
from app.auth import now_utc
from app.config import get_settings
from app.models import DailyFeature, FeatureDef, Observation, Tracker
from app.timeutil import current_day

PASSWORD = "day rating password"


def _csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def signed_in(client, db):
    auth.set_password(db, PASSWORD)
    db.flush()
    page = client.get("/login")
    client.post("/login", data={"password": PASSWORD, "csrf": _csrf(page.text)})
    return client


def _today() -> dt.date:
    settings = get_settings()
    return current_day(now_utc(), settings.zone, settings.day_boundary)


def _rate(client, csrf, key, value, day):
    return client.post(
        f"/log/{key}", data={"csrf": csrf, "value": str(value), "day": day.isoformat()}, follow_redirects=False
    )


def test_both_questions_are_on_the_overview_before_any_rating(signed_in, db):
    html = signed_in.get("/").text
    assert "How was today?" in html and "Looking back, how was yesterday?" in html
    assert db.execute(select(Tracker).where(Tracker.key.in_(dayrating.KEYS))).first() is None  # nothing stored yet


def test_evening_and_look_back_land_on_the_day_they_are_about(signed_in, db):
    csrf = _csrf(signed_in.get("/").text)
    yesterday = _today() - dt.timedelta(days=1)
    assert _rate(signed_in, csrf, dayrating.EVENING_KEY, 6, yesterday).status_code == 303
    assert _rate(signed_in, csrf, dayrating.LOOKBACK_KEY, 8, yesterday).status_code == 303
    rows = db.execute(select(Tracker.key, Observation.day, Observation.value_num).join(Observation)).all()
    assert sorted(rows) == [(dayrating.EVENING_KEY, yesterday, 6.0), (dayrating.LOOKBACK_KEY, yesterday, 8.0)]
    assert "That evening you said <strong>6</strong>" in signed_in.get("/").text


def test_the_look_back_waits_until_the_day_is_over(signed_in, db):
    csrf = _csrf(signed_in.get("/").text)
    refused = _rate(signed_in, csrf, dayrating.LOOKBACK_KEY, 5, _today())
    assert "error=look" in refused.headers["location"]
    assert db.execute(select(Observation)).first() is None
    review = signed_in.get(f"/review?day={_today().isoformat()}").text
    assert "How was" in review and "Looking back" not in review


def test_the_rating_is_built_in_not_a_tracker_you_manage(signed_in, db):
    csrf = _csrf(signed_in.get("/").text)
    _rate(signed_in, csrf, dayrating.EVENING_KEY, 7, _today())
    assert "How was today?" not in signed_in.get("/trackers").text
    refused = signed_in.post("/trackers", data={"csrf": csrf, "name": "Day rating", "type": "scale"})
    assert refused.status_code == 422 and "built in" in refused.text
    edit = signed_in.post(f"/trackers/{dayrating.EVENING_KEY}/edit", data={"csrf": csrf, "name": "x", "archived": "on"})
    assert "can&#39;t be changed" in edit.text
    tracker = db.execute(select(Tracker).where(Tracker.key == dayrating.EVENING_KEY)).scalar_one()
    assert not tracker.archived and tracker.name == "How was today?"


def test_a_shortcut_can_log_tonights_rating_but_not_the_look_back(client, db):
    raw, _ = auth.create_token(db, "t", "all")
    headers = {"Authorization": f"Bearer {raw}"}
    assert client.post(f"/api/log/{dayrating.EVENING_KEY}", json={"value": 7}, headers=headers).status_code == 201
    assert client.post(f"/api/log/{dayrating.LOOKBACK_KEY}", json={"value": 7}, headers=headers).status_code == 422


def test_ratings_become_one_family_of_features(signed_in, db):
    csrf = _csrf(signed_in.get("/").text)
    yesterday = _today() - dt.timedelta(days=1)
    _rate(signed_in, csrf, dayrating.EVENING_KEY, 6, yesterday)
    _rate(signed_in, csrf, dayrating.LOOKBACK_KEY, 4, yesterday)
    settings = get_settings()
    features.rebuild(db, settings.zone, settings.day_boundary)
    values = dict(
        db.execute(select(DailyFeature.feature, DailyFeature.value).where(DailyFeature.day == yesterday)).all()
    )
    assert (values[dayrating.EVENING], values[dayrating.LOOKBACK], values[dayrating.SHIFT]) == (6.0, 4.0, -2.0)
    families = set(db.execute(select(FeatureDef.family).where(FeatureDef.source == dayrating.SOURCE)).scalars())
    assert families == {dayrating.FAMILY}
    assert db.execute(select(FeatureDef).where(FeatureDef.feature.like("tracker.day_rating%"))).first() is None
