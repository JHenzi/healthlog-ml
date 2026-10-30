"""M2 end to end: seed metric settings, sync State of Mind from the raw archive, rebuild daily features."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, text

from app import features, jobs, metric_settings, mood
from app.models import DailyFeature, FeatureDef, MetricSetting, StateOfMindEntry

NY = ZoneInfo("America/New_York")
ID_A = "2D4F6A8C-0E1B-4C3D-8E5F-7A9B1C3D5E7F"
ID_B = "9E8D7C6B-5A4F-4E3D-9C2B-1A0F9E8D7C6B"


def _som(hae_id: str, start: str, valence: float, labels: list[str]) -> dict:
    return {
        "id": hae_id,
        "kind": "momentary_emotion",
        "start": start,
        "end": start,
        "valence": valence,
        "valenceClassification": "neutral",
        "labels": labels,
        "associations": ["work"],
    }


@pytest.fixture
def archive(admin_engine):
    """Synthetic HealthLog rows, committed as the owner; removed afterwards."""

    def add_payload(conn, payload: dict) -> None:
        body = json.dumps(payload).encode()
        conn.execute(
            text("INSERT INTO raw_ingest (payload, content_hash) VALUES (CAST(:p AS jsonb), :h)"),
            {"p": body.decode(), "h": hashlib.sha256(body).digest()},
        )

    with admin_engine.begin() as conn:
        for i in range(10):
            conn.execute(
                text(
                    "INSERT INTO metric_samples (time, metric, source, unit, qty) "
                    "VALUES (:t, 'step_count', '', 'count', :q), (:t, 'step_count', 'Watch', 'count', 99999)"
                ),
                {"t": dt.datetime(2026, 10, 1 + i, 12, tzinfo=NY), "q": 1000 + i},
            )
        add_payload(conn, {"data": {"stateOfMind": [_som(ID_A, "2026-10-05T16:00:00Z", -0.4, ["stressed"])]}})
        add_payload(conn, {"data": {"metrics": []}})  # no State of Mind: skipped by the reader
        # A later payload re-sends entry A edited, plus a new entry B.
        add_payload(
            conn,
            {
                "data": {
                    "stateOfMind": [
                        _som(ID_A, "2026-10-05T16:00:00Z", -0.8, ["anxious"]),
                        _som(ID_B, "2026-10-06T16:00:00Z", 0.5, ["calm"]),
                        {"id": "broken"},
                    ]
                }
            },
        )
    yield
    with admin_engine.begin() as conn:
        for table in ("metric_samples", "raw_ingest"):
            conn.execute(text(f"DELETE FROM {table}"))


def test_refresh_end_to_end(db, archive):
    result = jobs.refresh(db)
    assert result.seeded.added > 0  # HealthLog's registry seeds our settings
    assert db.get(MetricSetting, "step_count").aggregation == "sum"

    assert result.mood.entries == 3  # upserts: A in two payloads, B once
    assert result.mood.skipped == 1
    entry_a = db.get(StateOfMindEntry, uuid.UUID(ID_A))
    assert entry_a.valence == -0.8 and entry_a.labels == ["anxious"]  # the later payload wins

    steps = features.series(db, "hl.step_count")
    assert steps[dt.date(2026, 10, 1)] == 1000  # merged stream only: the Watch's 99999 is never added
    assert len(steps) == 10
    assert features.series(db, "mood.label.anxious") == {dt.date(2026, 10, 5): 1.0, dt.date(2026, 10, 6): 0.0}


def test_refresh_is_idempotent_and_the_cursor_advances(db, archive):
    jobs.refresh(db)
    rows_before = db.execute(select(func.count()).select_from(DailyFeature)).scalar_one()
    second = jobs.refresh(db)
    assert second.mood.payloads == 0  # nothing new in the archive
    assert db.execute(select(func.count()).select_from(StateOfMindEntry)).scalar_one() == 2
    assert db.execute(select(func.count()).select_from(DailyFeature)).scalar_one() == rows_before


def test_user_edits_survive_reseeding_and_change_the_series(db, archive):
    jobs.refresh(db)
    metric_settings.update(
        db, "step_count", aggregation="sum", analyse=True, min_value=None, max_value=1005, source_priority=[]
    )
    jobs.refresh(db)
    setting = db.get(MetricSetting, "step_count")
    assert setting.user_edited and setting.max_value == 1005
    assert max(features.series(db, "hl.step_count").values()) == 1005  # days above the bound are missing


def test_invalid_edits_are_rejected(db, archive):
    jobs.refresh(db)
    with pytest.raises(ValueError):
        metric_settings.update(
            db, "step_count", aggregation="median", analyse=True, min_value=None, max_value=None, source_priority=[]
        )
    with pytest.raises(ValueError):
        metric_settings.update(
            db, "step_count", aggregation="sum", analyse=True, min_value=10, max_value=1, source_priority=[]
        )


def test_mood_sync_without_entries_is_a_no_op(db):
    assert mood.sync_from_raw(db).entries == 0


def test_only_one_refresh_runs_at_a_time(db, companion_engine):
    """A second refresh waits for the first instead of colliding on the feature table (seen live on a deploy)."""
    jobs.refresh(db)  # holds the lock until this test's transaction ends
    with companion_engine.connect() as other:
        taken = other.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": jobs.REFRESH_LOCK}).scalar_one()
        other.rollback()
    assert taken is False


@pytest.fixture
def outside_dir(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("OUTSIDE_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _weather_file(path, days: int, temp: str = "11.0") -> None:
    from app.outside import COLUMNS, FILE_NAME, HEADER

    start = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    lines = [",".join(HEADER)]
    for i in range(days * 24):
        stamp = (start + dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:00Z")
        values = {"temperature_c": temp, "pressure_hpa": "1012.0"}
        lines.append(",".join([stamp, *(values.get(c, "") for c in COLUMNS)]))
    (path / FILE_NAME).write_text("\n".join(lines) + "\n")


def test_weather_loads_from_the_collector_file_into_features(db, outside_dir):
    assert jobs.refresh(db).weather.status == "off"  # no file: weather is off, nothing else changes
    _weather_file(outside_dir, 5)
    result = jobs.refresh(db)
    assert (result.weather.status, result.weather.hours) == ("loaded", 120)
    temps = features.series(db, "weather.temp_mean")
    assert dt.date(2026, 10, 2) in temps and set(temps.values()) == {11.0}
    assert jobs.refresh(db).weather.hours == 120  # idempotent upsert


def test_a_bad_weather_file_loads_nothing_and_keeps_what_was_there(db, outside_dir):
    _weather_file(outside_dir, 3)
    jobs.refresh(db)
    before = features.series(db, "weather.temp_mean")
    _weather_file(outside_dir, 3, temp="999")  # outside the plausible range
    assert jobs.refresh(db).weather.status == "rejected"
    assert features.series(db, "weather.temp_mean") == before


def test_the_almanac_follows_latitude_and_country(db, archive, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("WEATHER_LATITUDE", "40.7")
    get_settings.cache_clear()
    try:
        jobs.refresh(db)  # TZ is America/New_York: US holidays by default
        defs = {f.feature: f for f in db.execute(select(FeatureDef)).scalars() if f.source == "almanac"}
        assert set(defs) == {"almanac.moon", "almanac.day_length", "almanac.holiday", "almanac.days_to_holiday"}
        assert all(d.analyse for d in defs.values()) and defs["almanac.holiday"].family == "almanac"
        assert set(features.series(db, "almanac.holiday").values()) <= {0.0, 1.0}
        monkeypatch.setenv("HOLIDAYS_COUNTRY", "none")
        monkeypatch.delenv("WEATHER_LATITUDE")
        get_settings.cache_clear()
        jobs.refresh(db)
        assert {f.feature for f in db.execute(select(FeatureDef)).scalars() if f.source == "almanac"} == {
            "almanac.moon"
        }
    finally:
        get_settings.cache_clear()


def test_the_good_day_score_is_a_feature_of_complete_days(db, admin_engine):
    from app.analysis.run import load_meta
    from app.auth import now_utc
    from app.config import get_settings
    from app.goodday import FEATURE, MIN_COMPONENT_DAYS
    from app.timeutil import current_day

    settings = get_settings()
    today = current_day(now_utc(), settings.zone, settings.day_boundary)
    days = [today - dt.timedelta(days=k) for k in range(MIN_COMPONENT_DAYS + 1)]  # yesterday back, and today
    with admin_engine.begin() as conn:
        for k, day in enumerate(days):
            noon = dt.datetime.combine(day, dt.time(12), tzinfo=settings.zone)
            conn.execute(
                text(
                    "INSERT INTO metric_samples (time, metric, source, unit, qty) VALUES "
                    "(:t, 'step_count', '', 'count', :s), (:t, 'dietary_water', '', 'mL', :w)"
                ),
                {"t": noon, "s": 1000 + 100 * k, "w": 2000 - 50 * k},
            )
    try:
        jobs.refresh(db)
        score = features.series(db, FEATURE)
        assert today not in score and len(score) == MIN_COMPONENT_DAYS
        assert all(0 <= v <= 100 for v in score.values())
        meta = load_meta(db)[FEATURE]
        assert meta.family == "goodday" and "activity" in meta.built_from and meta.analyse
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text("DELETE FROM metric_samples"))


def test_water_written_for_coffee_or_beer_is_its_own_series(db, admin_engine):
    day = dt.date(2026, 10, 1)
    at = {h: dt.datetime.combine(day, dt.time(h), tzinfo=NY) for h in (9, 12, 19)}
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO metric_samples (time, metric, source, unit, qty) VALUES "
                "(:coffee, 'caffeine', '', 'mg', 50), (:coffee, 'dietary_water', '', 'mL', 71), "
                "(:water, 'dietary_water', '', 'mL', 250), "
                "(:beer, 'alcohol_consumption', '', 'count', 1), (:beer, 'dietary_water', '', 'mL', -142)"
            ),
            {"coffee": at[9], "water": at[12], "beer": at[19]},
        )
    try:
        jobs.refresh(db)
        assert features.series(db, "hl.dietary_water") == {day: 250.0}
        assert features.series(db, "hl.dietary_water_from_caffeine") == {day: 71.0}
        assert features.series(db, "hl.dietary_water_from_alcohol_consumption") == {day: -142.0}
        assert features.series(db, "hl.caffeine") == {day: 50.0}
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text("DELETE FROM metric_samples"))
