"""State of Mind parsing and daily mood features (synthetic entries, R4; missing is not zero, R7)."""

from __future__ import annotations

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

import pytest

from app.mood import MoodEntry, daily_features, parse_entry
from app.today import mood_sentence

NY = ZoneInfo("America/New_York")
FOUR = dt.time(4, 0)
ID = "1C9E2F4A-8B7D-4E6F-9A1B-3C5D7E9F0A2B"


def _raw(**overrides) -> dict:
    entry = {
        "id": ID,
        "kind": "momentary_emotion",
        "start": "2026-10-16T18:00:00Z",
        "end": "2026-10-16T18:00:00Z",
        "valence": -0.5,
        "valenceClassification": "slightly_unpleasant",
        "labels": ["stressed"],
        "associations": ["work"],
    }
    entry.update(overrides)
    return entry


def test_parse_iso_entry():
    row = parse_entry(_raw())
    assert row["hae_id"] == uuid.UUID(ID)
    assert row["start_time"] == dt.datetime(2026, 10, 16, 18, 0, tzinfo=dt.UTC)
    assert (row["valence"], row["labels"], row["associations"]) == (-0.5, ["stressed"], ["work"])


def test_parse_accepts_hae_format_and_int_valence():
    row = parse_entry(_raw(start="2026-10-16 14:00:00 -0400", valence=1))
    assert row["start_time"].utcoffset() == dt.timedelta(hours=-4) and row["valence"] == 1.0


def test_parse_rejects_unusable_entries():
    assert parse_entry(_raw(id="nope")) is None
    assert parse_entry(_raw(start="2026-10-16T18:00:00")) is None  # no offset: not guessed
    assert parse_entry(_raw(start=None)) is None
    assert parse_entry("not a dict") is None


def test_out_of_range_or_bool_valence_is_dropped_but_entry_kept():
    assert parse_entry(_raw(valence=3.0))["valence"] is None
    assert parse_entry(_raw(valence=True))["valence"] is None


def _entry(when: dt.datetime, valence: float | None, kind: str, labels=(), assocs=()) -> MoodEntry:
    return MoodEntry(when, kind, valence, tuple(labels), tuple(assocs))


def test_daily_features_counts_are_zero_only_on_observed_days():
    entries = [
        _entry(dt.datetime(2026, 10, 15, 12, tzinfo=NY), -0.6, "momentary_emotion", ["anxious"], ["work"]),
        _entry(dt.datetime(2026, 10, 15, 21, tzinfo=NY), 0.2, "daily_mood", ["calm"]),
        _entry(dt.datetime(2026, 10, 17, 12, tzinfo=NY), 0.8, "daily_mood", ["calm"], ["family"]),
    ]
    values, names = daily_features(entries, NY, FOUR)
    d15, d16, d17 = dt.date(2026, 10, 15), dt.date(2026, 10, 16), dt.date(2026, 10, 17)
    assert values["mood.entries"] == {d15: 2.0, d17: 1.0}  # no row for the 16th: unknown, not 0
    assert values["mood.label.anxious"] == {d15: 1.0, d17: 0.0}
    assert values["mood.assoc.family"] == {d15: 0.0, d17: 1.0}
    assert values["mood.valence_mean"][d15] == pytest.approx(-0.2)
    assert values["mood.daily_valence"] == {d15: 0.2, d17: 0.8}
    assert values["mood.momentary_valence"] == {d15: -0.6}
    assert values["mood.valence_min"][d15] == -0.6
    assert d16 not in values["mood.valence_mean"]
    assert names["mood.label.anxious"] == "Feeling: anxious"


def test_late_night_entry_belongs_to_the_evening_before():
    values, _ = daily_features([_entry(dt.datetime(2026, 10, 17, 2, tzinfo=NY), 0.0, "daily_mood")], NY, FOUR)
    assert values["mood.entries"] == {dt.date(2026, 10, 16): 1.0}


def test_mood_sentence():
    assert mood_sentence([]) == "No mood logged yesterday."
    s = mood_sentence([(-0.5, ("stressed", "worried")), (0.1, ("stressed",)), (None, ())])
    assert s == (
        "You logged 3 mood entries yesterday, average valence -0.20 on a -1 to +1 scale, "
        "most often stressed (2), worried (1)."
    )
