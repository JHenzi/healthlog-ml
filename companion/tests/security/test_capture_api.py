"""Capture API and tracker pages: per-tracker tokens (D4), CSRF (D2), escaping (D3), key injection (D5)."""

from __future__ import annotations

import datetime as dt
import re
import uuid

import pytest
from sqlalchemy import select

from app import auth, capture
from app.models import ApiToken, Observation, Tracker

PASSWORD = "tracker pages password"


@pytest.fixture
def coffee(db):
    return capture.create_tracker(db, key="coffee", name="Coffee", type="count", unit="cups", pinned=True)


@pytest.fixture
def tea(db):
    return capture.create_tracker(db, key="tea", name="Tea", type="count")


def _bearer(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


@pytest.mark.parametrize(
    ("scope", "key", "expected"),
    [("all", "coffee", 201), ("log:coffee", "coffee", 201), ("log:coffee", "tea", 403), ("read", "coffee", 403)],
)
def test_log_scope_matrix(client, db, coffee, tea, scope, key, expected):
    raw, _ = auth.create_token(db, "t", scope)
    assert client.post(f"/api/log/{key}", json={}, headers=_bearer(raw)).status_code == expected


def test_log_without_token_is_401(client, coffee):
    assert client.post("/api/log/coffee", json={}).status_code == 401


def test_log_reply_and_idempotent_retry(client, db, coffee):
    raw, _ = auth.create_token(db, "t", "log:coffee")
    cid = str(uuid.uuid4())
    first = client.post("/api/log/coffee", json={"value": 2, "client_id": cid}, headers=_bearer(raw))
    assert first.status_code == 201 and first.json()["message"].startswith("Logged Coffee at ")
    retry = client.post("/api/log/coffee", json={"value": 2, "client_id": cid}, headers=_bearer(raw))
    assert retry.status_code == 200 and retry.json()["created"] is False
    assert len(db.execute(select(Observation)).scalars().all()) == 1


def test_invalid_value_is_422_and_unknown_tracker_404(client, db, coffee):
    raw, _ = auth.create_token(db, "t", "all")
    assert client.post("/api/log/coffee", json={"value": -2}, headers=_bearer(raw)).status_code == 422
    assert client.post("/api/log/nope", json={}, headers=_bearer(raw)).status_code == 404


@pytest.mark.parametrize("key", ["Coffee", "coffee;drop", "a b", "1abc", "x" * 70])
def test_malformed_keys_are_rejected(client, db, key):
    raw, _ = auth.create_token(db, "t", "all")
    assert client.post(f"/api/log/{key}", json={}, headers=_bearer(raw)).status_code == 404


def test_delete_needs_full_scope(client, db, coffee):
    full, _ = auth.create_token(db, "full", "all")
    log_only, _ = auth.create_token(db, "log", "log:coffee")
    cid = client.post("/api/log/coffee", json={}, headers=_bearer(full)).json()["client_id"]
    assert client.delete(f"/api/entries/{cid}", headers=_bearer(log_only)).status_code == 403
    assert client.delete(f"/api/entries/{cid}", headers=_bearer(full)).status_code == 200
    assert client.delete(f"/api/entries/{cid}", headers=_bearer(full)).status_code == 404


def test_tracker_list_needs_read(client, db, coffee):
    log_only, _ = auth.create_token(db, "log", "log:coffee")
    read, _ = auth.create_token(db, "read", "read")
    assert client.get("/api/trackers", headers=_bearer(log_only)).status_code == 403
    assert [t["key"] for t in client.get("/api/trackers", headers=_bearer(read)).json()["trackers"]] == ["coffee"]


# --- pages ------------------------------------------------------------------


def _csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def signed_in(client, db):
    auth.set_password(db, PASSWORD)
    db.flush()
    page = client.get("/login")
    client.post("/login", data={"password": PASSWORD, "csrf": _csrf(page.text)})
    return client


@pytest.mark.parametrize("path", ["/trackers", "/trackers/coffee", "/review"])
def test_pages_need_sign_in(client, coffee, path):
    assert client.get(path, follow_redirects=False).status_code == 303


@pytest.mark.parametrize(
    "path",
    [
        "/trackers",
        "/trackers/coffee/edit",
        "/trackers/coffee/show",
        "/trackers/coffee/token",
        "/log/coffee",
        "/log/coffee/tag",
        "/review",
    ],
)
def test_writes_need_csrf(signed_in, coffee, path):
    assert signed_in.post(path, data={"csrf": "forged", "name": "x", "day": "2026-10-10"}).status_code == 403


def test_create_tracker_page_flow_and_escaping(signed_in, db):
    csrf = _csrf(signed_in.get("/trackers").text)
    response = signed_in.post(
        "/trackers",
        data={
            "csrf": csrf,
            "name": "<script>alert(1)</script> Mood",
            "type": "scale",
            "polarity": "good",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    key = response.headers["location"].rsplit("/", 1)[1]
    assert key == "script_alert_1_script_mood"
    html = signed_in.get(f"/trackers/{key}").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    tracker = db.execute(select(Tracker).where(Tracker.key == key)).scalar_one()
    # Assumed, not asked: every rating is 1–10, and a new metric is in Quick add and the daily log.
    assert (tracker.scale_min, tracker.scale_max, tracker.pinned, tracker.in_review) == (1, 10, True, True)
    assert 'class="lvl-0"' in html and 'class="lvl-10"' in html and "pol-good" in html


def test_new_metric_form_asks_only_what_it_needs(signed_in, db):
    html = signed_in.get("/trackers").text
    for gone in ('name="key"', 'name="scale_min"', 'name="scale_labels"', 'name="category"'):
        assert gone not in html
    assert 'name="tags"' in html and "What are you tracking?" in html
    # Ideas are suggestions, not one-tap creates; Apple Health already has coffee and alcohol.
    assert 'href="/trackers?idea=work_day#new"' in html and "idea=coffee" not in html
    filled = signed_in.get("/trackers?idea=work_day").text
    assert 'value="Work day"' in filled and 'value="meeting heavy, in-fighting' in filled
    assert 'name="polarity" value="good"' in filled
    assert db.execute(select(Tracker)).first() is None
    created = signed_in.post(
        "/trackers",
        data={"csrf": _csrf(html), "name": "Work day", "type": "scale", "polarity": "good", "tags": "deadline"},
        follow_redirects=False,
    )
    assert created.headers["location"] == "/trackers/work_day"
    assert "idea=work_day" not in signed_in.get("/trackers").text


def test_trackers_page_sets_where_each_shows_and_todays_tags(signed_in, db, coffee):
    capture.create_tracker(db, key="day_tags", name="Day tags", type="tags", tags=["travel"], in_review=True)
    html = signed_in.get("/trackers").text
    assert "Today's tags" in html and 'aria-pressed="false">travel' in html
    csrf = _csrf(html)
    signed_in.post("/log/day_tags/tag", data={"csrf": csrf, "tag": "travel", "back": "/trackers"})
    assert 'aria-pressed="true">travel' in signed_in.get("/trackers").text
    assert coffee.pinned
    signed_in.post("/trackers/coffee/show", data={"csrf": csrf, "field": "pinned"})
    db.refresh(coffee)
    assert not coffee.pinned
    assert signed_in.post("/trackers/coffee/show", data={"csrf": csrf, "field": "archived"}).status_code == 400


def test_tags_toggle_from_the_daily_log(signed_in, db):
    capture.create_tracker(
        db,
        key="work_day",
        name="Work day",
        type="scale",
        scale_min=1,
        scale_max=10,
        tags=["Meeting heavy"],
        pinned=True,
    )
    html = signed_in.get("/").text
    assert 'aria-pressed="false">Meeting heavy' in html
    csrf = _csrf(html)
    signed_in.post("/log/work_day/tag", data={"csrf": csrf, "tag": "Meeting heavy", "back": "/"})
    assert 'aria-pressed="true">Meeting heavy' in signed_in.get("/").text
    signed_in.post("/log/work_day/tag", data={"csrf": csrf, "tag": "Meeting heavy", "back": "/"})
    assert 'aria-pressed="false">Meeting heavy' in signed_in.get("/").text
    bad = signed_in.post("/log/work_day/tag", data={"csrf": csrf, "tag": "nope", "back": "/"}, follow_redirects=False)
    assert "error=" in bad.headers["location"]


def test_logging_an_earlier_day_lands_on_that_day(signed_in, db, coffee):
    review = signed_in.get("/review").text
    today = dt.date.fromisoformat(re.search(r'name="day" value="([0-9-]+)"', review).group(1))
    earlier = today - dt.timedelta(days=3)
    csrf = _csrf(review)
    signed_in.post("/log/coffee", data={"csrf": csrf, "day": earlier.isoformat(), "back": "/review"})
    assert db.execute(select(Observation)).scalar_one().day == earlier


def test_bad_definition_shows_an_error(signed_in):
    csrf = _csrf(signed_in.get("/trackers").text)
    page = signed_in.post("/trackers", data={"csrf": csrf, "name": "Lunch", "type": "choice", "options": "home"})
    assert page.status_code == 422 and "at least two options" in page.text


def test_quick_log_review_and_delete_from_pages(signed_in, db, coffee):
    today = signed_in.get("/").text
    assert "Quick add" in today and "+1" in today
    csrf = _csrf(today)
    signed_in.post("/log/coffee", data={"csrf": csrf, "client_id": str(uuid.uuid4()), "back": "/"})
    entry = db.execute(select(Observation)).scalar_one()
    assert "Logged today" in signed_in.get("/").text

    review = signed_in.get(f"/review?day={entry.day.isoformat()}")
    assert review.status_code == 200 and "Coffee" in review.text
    signed_in.post("/review", data={"csrf": csrf, "day": entry.day.isoformat(), "reviewed": "on"})
    assert capture.is_reviewed(db, entry.day)

    signed_in.post(f"/entries/{entry.client_id}/delete", data={"csrf": csrf, "back": "/"})
    db.refresh(entry)
    assert entry.deleted


def test_log_only_token_is_shown_once_and_never_from_the_url(signed_in, db, coffee):
    assert "hlc_" not in signed_in.get("/trackers/coffee?new_token=hlc_fake").text
    csrf = _csrf(signed_in.get("/trackers/coffee").text)
    page = signed_in.post("/trackers/coffee/token", data={"csrf": csrf})
    raw = re.search(r"hlc_[A-Za-z0-9_-]+", page.text).group(0)
    assert page.headers["cache-control"] == "no-store"
    stored = db.execute(select(ApiToken).where(ApiToken.scope == "log:coffee")).scalar_one()
    assert stored.token_hash == auth.sha256(raw) and raw not in signed_in.get("/trackers/coffee").text


def test_open_redirects_are_refused(signed_in, coffee):
    csrf = _csrf(signed_in.get("/").text)
    response = signed_in.post("/log/coffee", data={"csrf": csrf, "back": "//evil.example"}, follow_redirects=False)
    assert response.headers["location"] == "/"


def test_overview_coverage_strip_and_current_section(signed_in, db, coffee):
    html = signed_in.get("/").text
    assert "Data for analysis" in html and "0 of 30 days" in html
    assert html.count('class="missing"') == 30  # nothing logged yet: every day hatched, none drawn as zero
    assert '<a href="/" aria-current="page">Overview</a>' in html
