"""Today page against real HealthLog tables (synthetic rows, R4)."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app import upstream
from app.timeutil import local_day
from app.today import load_today

NY = ZoneInfo("America/New_York")
FOUR = dt.time(4, 0)
TODAY = dt.date(2026, 10, 17)
YESTERDAY = dt.date(2026, 10, 16)

UPSTREAM_TABLES = ("metric_samples", "sleep_sessions", "stress_intraday", "body_battery_intraday")


@pytest.fixture
def upstream_rows(admin_engine):
    """Commit synthetic HealthLog rows as the owner (the companion role can't write public), clean up after."""

    def at(day: dt.date, hour: int, minute: int = 0) -> dt.datetime:
        return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=NY)

    with admin_engine.begin() as conn:
        for i in range(1, 15):  # two weeks of history before yesterday
            day = YESTERDAY - dt.timedelta(days=i)
            conn.execute(
                text(
                    "INSERT INTO metric_samples (time, metric, source, unit, qty) "
                    "VALUES (:t, 'step_count', '', 'count', 7000)"
                ),
                {"t": at(day, 12)},
            )
            conn.execute(
                text(
                    "INSERT INTO sleep_sessions (sleep_start, sleep_end, source, total_sleep_h) "
                    "VALUES (:s, :e, 'Watch', 7.5)"
                ),
                {"s": at(day - dt.timedelta(days=1), 23), "e": at(day, 6, 30)},
            )
        # Yesterday: merged stream 9000 (two samples) plus a device stream that must not be added.
        conn.execute(
            text(
                "INSERT INTO metric_samples (time, metric, source, unit, qty) VALUES "
                "(:a, 'step_count', '', 'count', 5000), (:b, 'step_count', '', 'count', 4000), "
                "(:a, 'step_count', 'Watch', 'count', 6000)"
            ),
            {"a": at(YESTERDAY, 10), "b": at(TODAY, 2)},  # 02:00 on the 17th is still the 16th's day
        )
        conn.execute(
            text(
                "INSERT INTO sleep_sessions (sleep_start, sleep_end, source, total_sleep_h) "
                "VALUES (:s, :e, 'Watch', 6.5)"
            ),
            {"s": at(YESTERDAY, 23, 30), "e": at(TODAY, 6)},
        )
        conn.execute(
            text(
                "INSERT INTO stress_intraday (ts, stress, hr, state) VALUES "
                "(:a, 20, 60, 'low'), (:b, 40, 70, 'medium'), (:c, 90, 140, 'active')"
            ),
            {"a": at(YESTERDAY, 9), "b": at(YESTERDAY, 15), "c": at(YESTERDAY, 18)},
        )
        conn.execute(
            text("INSERT INTO body_battery_intraday (ts, level) VALUES (:a, 80), (:b, 35)"),
            {"a": at(YESTERDAY, 7), "b": at(YESTERDAY, 22)},
        )
    yield
    with admin_engine.begin() as conn:
        for table in UPSTREAM_TABLES:
            conn.execute(text(f"DELETE FROM {table}"))


def test_today_sentences_from_healthlog_tables(db, upstream_rows):
    view = load_today(db, NY, FOUR, TODAY)
    assert view.problems == []
    lines = "\n".join(view.sentences)
    assert "You slept 6 h 30 min last night, 1 h 00 min below your 30-day average (7 h 30 min, 14 nights)." in lines
    assert "You walked 9,000 steps yesterday, 2,000 more than your 30-day average (7,000 steps, 14 days)." in lines
    assert "Average stress was 30 yesterday" in lines  # the active minute is not scored
    assert "Your energy reserve ranged from 35 to 80 yesterday." in lines


def test_sql_day_rule_matches_python_rule(db):
    """The SQL day expression and local_day agree around the boundary and across DST."""
    stamps = [
        dt.datetime(2026, 10, 17, 3, 59, tzinfo=NY),
        dt.datetime(2026, 10, 17, 4, 0, tzinfo=NY),
        dt.datetime(2026, 3, 8, 3, 30, tzinfo=NY),
        dt.datetime(2026, 11, 1, 1, 30, tzinfo=NY),
        dt.datetime(2026, 11, 1, 5, 0, tzinfo=dt.UTC),
    ]
    expr = upstream.sql_day_expr(":ts")
    for ts in stamps:
        got = db.execute(
            text(f"SELECT {expr}"), {"ts": ts, "tz": "America/New_York", "boundary": "4 hours 0 minutes"}
        ).scalar_one()
        assert got == local_day(ts, NY, FOUR), ts


def test_contract_matches_live_schema(db):
    assert upstream.check_upstream(db) == []


def test_highlights_read_the_feature_table(db):
    from app.highlights import RECORD_MIN_DAYS, load_highlights
    from app.models import DailyFeature, FeatureDef

    today = dt.date(2026, 10, 20)
    db.add(FeatureDef(feature="hl.step_count", label="Steps", unit=None, source="healthlog", kind="continuous"))
    db.add(FeatureDef(feature="mood.label.calm", label="Calm", unit=None, source="mood", kind="count"))
    for i in range(RECORD_MIN_DAYS):
        day = today - dt.timedelta(days=RECORD_MIN_DAYS - i)
        steps = 20000.0 if i == RECORD_MIN_DAYS - 1 else 5000.0 + i
        db.add(DailyFeature(day=day, feature="hl.step_count", value=steps))
        db.add(DailyFeature(day=day, feature="mood.label.calm", value=1.0))  # mood isn't a tracker: no streak
    db.flush()
    notes = load_highlights(db, today)
    assert [n.text for n in notes] == [f"Steps: 20,000 yesterday, the highest in {RECORD_MIN_DAYS} days of data."]
