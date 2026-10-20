"""Streaks and personal records: descriptive notes for the Overview (plan M5 follow-ups).

Facts about your own series, not inferences: no p-values, nothing joins the
FDR family, and the wording judges nothing (a record is "the highest", never
"the best", R10). Every note names the days behind it (R13). Pure, from the
daily feature table; ``load_highlights`` does the read.

- **Record**: a continuous series reaches its highest or lowest value of at
  least ``RECORD_MIN_DAYS`` days of data.
- **Streak**: a tracker you log as yes/no or a count is above zero
  ``STREAK_MIN_DAYS`` days in a row, or at zero ``QUIET_MIN_DAYS`` days in a
  row after you had used it. Only recorded days count (R7): an unknown day
  ends a streak.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .models import DailyFeature, FeatureDef

RECORD_MIN_DAYS = 60
STREAK_MIN_DAYS = 3
QUIET_MIN_DAYS = 7
MAX_NOTES = 4
# Records say little for these: counts of labels, and values that are a sum of the day's choices.
RECORD_SOURCES = ("healthlog", "sleep", "stress", "energy", "workout", "weather")


@dataclass(frozen=True)
class Def:
    label: str
    unit: str | None
    source: str
    kind: str


@dataclass(frozen=True)
class Note:
    kind: str  # record | streak | quiet
    feature: str
    text: str
    days: int  # the days behind it (history length or streak length), for ordering


def fmt_value(value: float, unit: str | None) -> str:
    if unit == "h":
        h, m = divmod(round(value * 60), 60)
        return f"{h} h {m:02d} min" if h else f"{m} min"
    number = f"{round(value):,}" if abs(value) >= 100 else f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{number} {unit}" if unit else number


def _on(day: dt.date, today: dt.date) -> str:
    if day == today:
        return "today"
    return "yesterday" if day == today - dt.timedelta(days=1) else day.strftime("%a, %b %-d")


def record(feature: str, d: Def, values: Mapping[dt.date, float], day: dt.date, today: dt.date) -> Note | None:
    if d.kind != "continuous" or d.source not in RECORD_SOURCES or day not in values:
        return None
    history = [v for k, v in values.items() if k < day]
    if len(history) + 1 < RECORD_MIN_DAYS:
        return None
    value = values[day]
    if value > max(history):
        word = "highest"
    elif value < min(history):
        word = "lowest"
    else:
        return None
    n = len(history) + 1
    when = "last night" if d.source == "sleep" else _on(day, today)
    text = f"{d.label}: {fmt_value(value, d.unit)} {when}, the {word} in {n} days of data."
    return Note("record", feature, text, n)


def streak(feature: str, d: Def, values: Mapping[dt.date, float], day: dt.date, today: dt.date) -> Note | None:
    """A tracker's run of recorded days ending on ``day``: all above zero, or all zero after earlier use."""
    if d.source != "tracker" or d.kind != "count" or day not in values:
        return None
    on = values[day] > 0
    run = 0
    cursor = day
    while cursor in values and (values[cursor] > 0) == on:
        run += 1
        cursor -= dt.timedelta(days=1)
    if on and run >= STREAK_MIN_DAYS:
        return Note("streak", feature, f"{d.label}: {run} days in a row, through {_on(day, today)}.", run)
    used_before = any(v > 0 for k, v in values.items() if k < day)
    if not on and run >= QUIET_MIN_DAYS and used_before:
        return Note("quiet", feature, f"{d.label}: none for {run} recorded days in a row.", run)
    return None


def highlights(series: Mapping[str, Mapping[dt.date, float]], defs: Mapping[str, Def], today: dt.date) -> list[Note]:
    """Notes for the Overview: streaks first (you made them), then records, longest history first."""
    yesterday = today - dt.timedelta(days=1)
    notes: list[Note] = []
    for feature, values in series.items():
        d = defs.get(feature)
        if d is None:
            continue
        day = today if d.source == "sleep" else yesterday  # sleep is keyed by wake date
        note = streak(feature, d, values, day, today) or record(feature, d, values, day, today)
        if note:
            notes.append(note)
    order = {"streak": 0, "quiet": 1, "record": 2}
    notes.sort(key=lambda n: (order[n.kind], -n.days, n.feature))
    return notes[:MAX_NOTES]


def load_highlights(db: Session, today: dt.date) -> list[Note]:
    defs = {
        r.feature: Def(r.label, r.unit, r.source, r.kind)
        for r in db.execute(sa.select(FeatureDef)).scalars()
        if r.source in (*RECORD_SOURCES, "tracker")
    }
    series: dict[str, dict[dt.date, float]] = {}
    rows = db.execute(
        sa.select(DailyFeature.feature, DailyFeature.day, DailyFeature.value).where(
            DailyFeature.feature.in_(list(defs)), DailyFeature.day <= today
        )
    )
    for r in rows:
        series.setdefault(r.feature, {})[r.day] = r.value
    return highlights(series, defs, today)
