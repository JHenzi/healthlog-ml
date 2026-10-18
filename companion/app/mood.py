"""Apple Health State of Mind: parse entries from HealthLog's raw archive and turn them into daily features.

Until HealthLog stores State of Mind itself (upstream PR #111), we read the
``stateOfMind`` arrays straight from archived payloads, with a cursor so each
payload is read once. Entries are deduplicated by HAE's id; a later payload
carrying the same id (an edit on the phone) wins. Parsing is our own code, not
HealthLog's (design §8.4), and pure.

Daily features follow "missing is not zero" (R7): label and association
counts are 0 only on days that have at least one entry; days without entries
have no mood features at all.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from . import upstream
from .models import Setting, StateOfMindEntry
from .timeutil import local_day

log = logging.getLogger("companion.mood")

CURSOR_KEY = "state_of_mind_cursor"


def _aware(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    for parse in (dt.datetime.fromisoformat, lambda v: dt.datetime.strptime(v, "%Y-%m-%d %H:%M:%S %z")):
        try:
            parsed = parse(text)
        except ValueError:
            continue
        return parsed if parsed.tzinfo is not None else None
    return None


def _strings(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str) and v] if isinstance(value, list) else []


def parse_entry(entry: object) -> dict | None:
    """One HAE ``stateOfMind`` element → a row dict, or None when it has no usable id or start."""
    if not isinstance(entry, dict):
        return None
    try:
        hae_id = uuid.UUID(str(entry.get("id")))
    except ValueError:
        return None
    start = _aware(entry.get("start"))
    if start is None:
        return None
    valence = entry.get("valence")
    valence = float(valence) if isinstance(valence, int | float) and not isinstance(valence, bool) else None
    if valence is not None and not -1.0 <= valence <= 1.0:
        valence = None
    return {
        "hae_id": hae_id,
        "start_time": start,
        "kind": entry.get("kind") if isinstance(entry.get("kind"), str) else None,
        "valence": valence,
        "valence_classification": entry.get("valenceClassification")
        if isinstance(entry.get("valenceClassification"), str)
        else None,
        "labels": _strings(entry.get("labels")),
        "associations": _strings(entry.get("associations")),
    }


@dataclass
class SyncResult:
    payloads: int = 0
    entries: int = 0
    skipped: int = 0


def sync_from_raw(db: Session, batch: int = 200) -> SyncResult:
    """Copy new State of Mind entries from HealthLog's raw archive; advances the cursor. Idempotent."""
    setting = db.get(Setting, CURSOR_KEY)
    cursor = int(setting.value.get("payload_id", 0)) if setting else 0
    result = SyncResult()
    while True:
        chunk = upstream.raw_state_of_mind_since(db, cursor, limit=batch)
        if not chunk:
            break
        for raw_id, entries in chunk:
            result.payloads += 1
            rows = []
            for entry in entries or []:
                row = parse_entry(entry)
                if row is None:
                    result.skipped += 1
                    continue
                rows.append({**row, "payload_id": raw_id})
            # Last occurrence wins within a payload, like across payloads.
            by_id = {r["hae_id"]: r for r in rows}
            for row in by_id.values():
                stmt = pg_insert(StateOfMindEntry).values(row)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["hae_id"], set_={k: stmt.excluded[k] for k in row if k != "hae_id"}
                )
                db.execute(stmt)
            result.entries += len(by_id)
            cursor = raw_id
    if setting is None:
        db.add(Setting(key=CURSOR_KEY, value={"payload_id": cursor}))
    else:
        setting.value = {"payload_id": cursor}
    if result.skipped:
        log.warning("state of mind: %d entries without a usable id/start skipped", result.skipped)
    return result


# --- daily features (pure) -------------------------------------------------


@dataclass(frozen=True)
class MoodEntry:
    start_time: dt.datetime
    kind: str | None
    valence: float | None
    labels: tuple[str, ...]
    associations: tuple[str, ...]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def daily_features(
    entries: Iterable[MoodEntry], zone: ZoneInfo, boundary: dt.time
) -> tuple[dict[str, dict[dt.date, float]], dict[str, str]]:
    """``(feature → {day → value}, feature → label)`` for mood.

    Features: entry count, mean valence (all / daily mood / momentary), lowest
    valence, and per-day counts of each label and association.
    """
    by_day: dict[dt.date, list[MoodEntry]] = {}
    for e in entries:
        by_day.setdefault(local_day(e.start_time, zone, boundary), []).append(e)
    labels = sorted({lab for es in by_day.values() for e in es for lab in e.labels})
    assocs = sorted({a for es in by_day.values() for e in es for a in e.associations})

    out: dict[str, dict[dt.date, float]] = {}
    names: dict[str, str] = {
        "mood.entries": "Mood entries",
        "mood.valence_mean": "Mood valence (mean)",
        "mood.valence_min": "Mood valence (lowest)",
        "mood.daily_valence": "Daily mood valence",
        "mood.momentary_valence": "Momentary emotion valence",
    }
    names |= {f"mood.label.{x}": f"Feeling: {x.replace('_', ' ')}" for x in labels}
    names |= {f"mood.assoc.{x}": f"Mood about: {x.replace('_', ' ')}" for x in assocs}

    def put(feature: str, day: dt.date, value: float | None) -> None:
        if value is not None:
            out.setdefault(feature, {})[day] = value

    for day, es in by_day.items():
        valences = [e.valence for e in es if e.valence is not None]
        put("mood.entries", day, float(len(es)))
        put("mood.valence_mean", day, _mean(valences))
        put("mood.valence_min", day, min(valences) if valences else None)
        put(
            "mood.daily_valence",
            day,
            _mean([e.valence for e in es if e.kind == "daily_mood" and e.valence is not None]),
        )
        put(
            "mood.momentary_valence",
            day,
            _mean([e.valence for e in es if e.kind == "momentary_emotion" and e.valence is not None]),
        )
        for x in labels:  # observed day: absent label counts as 0 (R7)
            put(f"mood.label.{x}", day, float(sum(x in e.labels for e in es)))
        for x in assocs:
            put(f"mood.assoc.{x}", day, float(sum(x in e.associations for e in es)))
    return out, names
