"""Render the Companion's pages with synthetic data, for the design-review page (see run.sh).

Runs against the throwaway test DB as the ``companion`` role, inside one transaction that is rolled
back at the end. All data is synthetic (R4): 90 days with three planted relationships
(sleep ↔ productivity, sleep ↔ coffee, feeling anxious → next-day sleep). The insight sentences are
the engine's real output on that data. Pages are saved as static HTML with links and forms made inert.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sys
import uuid

import numpy as np

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://companion:companion-test-password@127.0.0.1:55432/companion_test"
)
os.environ.setdefault("TZ", "America/New_York")

import sqlalchemy as sa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import auth, capture, today  # noqa: E402
from app.analysis import run as analysis  # noqa: E402
from app.analysis.engine import FeatureMeta, analyse  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import DailyFeature, FeatureDef, Insight  # noqa: E402
from app.timeutil import current_day  # noqa: E402

N_DAYS = 90
PASSWORD = "preview password 123"
FEATURES = [  # feature, label, unit, source, kind, family
    ("hl.step_count", "Steps", "count", "healthlog", "continuous", "activity"),
    ("hl.resting_heart_rate", "Resting heart rate", "bpm", "healthlog", "continuous", "vital"),
    ("sleep.total_h", "Sleep (total)", "h", "sleep", "continuous", "sleep"),
    ("stress.mean", "Stress (mean of measured minutes)", None, "stress", "continuous", "vital"),
    ("tracker.productivity.mean", "Productivity", None, "tracker", "continuous", "tracker:productivity"),
    ("tracker.coffee.total", "Coffee", "cups", "tracker", "count", "tracker:coffee"),
    ("mood.label.anxious", "Feeling: anxious", None, "mood", "count", "mood"),
]
PLANTED = {
    tuple(sorted(p))
    for p in (
        ("sleep.total_h", "tracker.productivity.mean"),
        ("sleep.total_h", "tracker.coffee.total"),
        ("mood.label.anxious", "sleep.total_h"),
    )
}
TODAY_SENTENCES = [
    "You slept 7 h 05 min last night, about your 30-day average (7 h 12 min, 28 nights).",
    "HRV averaged 61 ms yesterday, 6 ms above your 30-day average (55 ms, 27 days).",
    "Resting heart rate was 55 bpm yesterday, about your 30-day average (56 bpm, 27 days).",
    "You walked 8,412 steps yesterday, 1,203 more than your 30-day average (7,209 steps, 30 days).",
    "Average stress was 29 yesterday, 3 below your 30-day average (32, 26 days).",
    "Your energy reserve ranged from 24 to 81 yesterday.",
    "You logged 2 mood entries yesterday, average valence +0.25 on a -1 to +1 scale, most often calm (2).",
]


def synthesize(seed: int, days: list[dt.date]) -> dict[str, dict[dt.date, float]]:
    rng = np.random.default_rng(seed)
    n = len(days)
    sleep = 7.2 + 0.6 * rng.normal(size=n)
    anxious = (rng.random(n) < 0.3).astype(float)
    sleep[1:] -= 0.8 * anxious[:-1]
    prod = np.clip(np.round(3 + 1.4 * (sleep - 7.2) + 0.45 * rng.normal(size=n)), 1, 5)
    coffee = np.clip(np.round(2 - 1.3 * (sleep - 7.2) + 0.5 * rng.normal(size=n)), 0, 6)
    measured = {
        "hl.step_count": 7000 + 1800 * rng.normal(size=n),
        "hl.resting_heart_rate": 56 + 2.5 * rng.normal(size=n),
        "sleep.total_h": sleep,
        "stress.mean": 32 + 6 * rng.normal(size=n),
    }
    logged = rng.random(n) < 0.8  # self-logged days; the others stay unknown, never zero
    logged[-30:] = rng.random(30) < 0.72
    mine = {"tracker.productivity.mean": prod, "tracker.coffee.total": coffee, "mood.label.anxious": anxious}
    values = {f: {days[i]: float(v[i]) for i in range(n)} for f, v in measured.items()}
    values |= {f: {days[i]: float(v[i]) for i in range(n) if logged[i]} for f, v in mine.items()}
    return values


def pick_dataset(days: list[dt.date], day: dt.date) -> dict[str, dict[dt.date, float]]:
    """The first seed whose findings include every planted pair (a preview shouldn't lead with a chance hit)."""
    meta = {f: FeatureMeta(label, unit, kind, family) for f, label, unit, _, kind, family in FEATURES}
    for seed in range(1, 200):
        values = synthesize(seed, days)
        found = {tuple(sorted((f.a, f.b))) for f in analyse(values, meta, day) if f.kind == "association"}
        if PLANTED <= found:
            return values
    return values


def seed_database(db: Session, day: dt.date) -> None:
    settings = get_settings()
    days = [day - dt.timedelta(days=N_DAYS - i) for i in range(N_DAYS)]
    for f, label, unit, source, kind, family in FEATURES:
        db.add(FeatureDef(feature=f, label=label, unit=unit, source=source, kind=kind, family=family))
    for f, series in pick_dataset(days, day).items():
        for d, v in series.items():
            db.add(DailyFeature(day=d, feature=f, value=v))
    db.flush()
    analysis.run(db, day)

    coffee = capture.create_tracker(db, key="coffee", name="Coffee", type="count", unit="cups", pinned=True)
    productivity = capture.create_tracker(
        db,
        key="productivity",
        name="Productivity",
        type="scale",
        scale_min=1,
        scale_max=5,
        scale_labels={"1": "nothing done", "3": "normal", "5": "best day"},
        polarity="good",
        pinned=True,
    )
    capture.create_tracker(
        db,
        key="work_day",
        name="Work day",
        type="scale",
        scale_min=1,
        scale_max=10,
        pinned=True,
    )
    day_tags = capture.add_day_tags(db, ["meeting heavy", "in-fighting", "deadline", "travel", "late night"])
    capture.create_tracker(db, key="lunch", name="Lunch", type="choice", options=["home", "takeout", "skipped"])
    anger = capture.create_tracker(db, key="anger", name="Anger", type="moment", pinned=True)
    now = dt.datetime.now(settings.zone)
    for tracker, value, hour in ((coffee, 1, 7), (coffee, 1, 10), (productivity, 4, 9), (anger, 2, 8)):
        when = min(now - dt.timedelta(minutes=5), now.replace(hour=hour, minute=10))
        capture.log(
            db,
            tracker,
            value,
            observed_at=when,
            client_id=uuid.uuid4(),
            source="web",
            zone=settings.zone,
            boundary=settings.day_boundary,
        )
    for tag in ("meeting heavy", "deadline"):
        capture.toggle_tag(
            db, day_tags, tag, day, observed_at=None, source="web", zone=settings.zone, boundary=settings.day_boundary
        )
    auth.set_password(db, PASSWORD)
    db.flush()


def static_page(page: str, links: dict[str, str]) -> str:
    page = page.replace('href="/static/style.css"', 'href="style.css"')
    page = re.sub(r'href="(/[^"]*)"', lambda m: f'href="{links.get(m.group(1).split("?")[0], "#")}"', page)
    page = re.sub(r'<form method="post" action="[^"]*"', '<form method="dialog"', page)  # inert in the preview
    return re.sub(r'name="csrf" value="[^"]*"', 'name="csrf" value=""', page)


def main(out: str) -> None:
    settings = get_settings()
    day = current_day(dt.datetime.now(dt.UTC), settings.zone, settings.day_boundary)
    engine = sa.create_engine(os.environ["DATABASE_URL"])
    conn = engine.connect()
    trans = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        seed_database(db, day)
        # HealthLog's own tables are empty in the test DB: show representative baseline sentences instead.
        tiles = (
            today.tile("sleep", 7 + 5 / 60, today.Baseline(7.2, 28)),
            today.tile("hrv", 61, today.Baseline(55, 27)),
            today.tile("resting_hr", 55, today.Baseline(56, 27)),
            today.tile("steps", 8412, today.Baseline(7209, 30)),
            today.tile("stress", 29, today.Baseline(32, 26)),
            today.energy_tile((24, 81)),
            today.mood_tile([(0.3, ("calm",)), (0.2, ("calm",))]),
        )
        today.load_today = lambda *_args: today.TodayView(day, TODAY_SENTENCES, [], tiles)

        app = create_app(check_on_startup=False)
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app, base_url="https://testserver")
        login = client.get("/login").text
        csrf = re.search(r'name="csrf" value="([^"]+)"', login).group(1)
        pages = {"signin": login}
        client.post("/login", data={"password": PASSWORD, "csrf": csrf})

        first = (
            db.execute(sa.select(Insight.id).where(Insight.kind == "association").order_by(Insight.score.desc()))
            .scalars()
            .first()
        )
        routes = {
            "overview": "/",
            "good-days": "/good-days",
            "discover": "/insights",
            "evidence": f"/insights/{first}",
            "log": "/review",
            "metrics": "/metrics",
            "metric": "/metrics/tracker.productivity.mean",
            "trackers": "/trackers",
            "tracker": "/trackers/coffee",
            "connect": "/trackers/coffee/connect",
        }
        links = {path: f"{name}.html" for name, path in routes.items()}
        for name, path in routes.items():
            response = client.get(path)
            if response.status_code != 200:
                raise SystemExit(f"{path}: HTTP {response.status_code}")
            pages[name] = response.text
        for name, page in pages.items():
            with open(f"{out}/{name}.html", "w") as fh:
                fh.write(static_page(page, links))
        count = db.execute(sa.select(sa.func.count()).select_from(Insight)).scalar_one()
        print(f"rendered {len(pages)} pages, {count} insights")
    finally:
        trans.rollback()
        conn.close()


if __name__ == "__main__":
    main(sys.argv[1])
