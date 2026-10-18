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
from app.models import DailyFeature, MetricSetting, StateOfMindEntry

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
