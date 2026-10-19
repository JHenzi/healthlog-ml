"""HAE exports of data types HealthLog doesn't parse yet (symptoms, medications).

Real export structure of synthetic test entries from a German-locale device, so
names, severities and statuses arrive localised (timestamps shifted, medication
renamed). They are fixtures for a future parser; until then a payload of these
types must still be accepted and archived verbatim, never rejected.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.ingest import ingest_bytes, parse_payload
from app.models import RawIngest

FIXTURES = Path(__file__).parent / "fixtures"


FIXTURE_KEYS = [("hae_symptoms_de.json", "symptoms"), ("hae_medications_de.json", "medications")]


@pytest.mark.parametrize(("name", "key"), FIXTURE_KEYS)
def test_fixture_has_entries(name, key):
    data = json.loads((FIXTURES / name).read_text())["data"]
    assert data[key], f"{name} should carry {key} entries"


@pytest.mark.parametrize("name", [name for name, _ in FIXTURE_KEYS])
def test_unparsed_types_are_accepted_and_archived(db, name):
    body = (FIXTURES / name).read_bytes()
    parsed = parse_payload(json.loads(body))
    assert (parsed.metric_rows, parsed.sleep_rows, parsed.workout_rows) == ([], [], [])

    status, _ = ingest_bytes(db, body)
    assert status == "stored"
    assert db.execute(select(func.count()).select_from(RawIngest)).scalar_one() == 1
