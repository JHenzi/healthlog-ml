"""The daily feature table: one value per (Companion day, feature) over every source (design §4.1).

Sources so far: every HealthLog metric (``hl.<metric>``), sleep, stress, energy
reserve, workouts and State of Mind. Trackers (M4) and weather (M3) join the
same table. Assembly is pure (``assemble``); ``rebuild`` reads through the
read contract and replaces the cache in one transaction, so new feature
definitions apply to all history.

Missing is not zero (R7): a day without data for a feature has no row, never 0.
Overlapping sources are never summed (R16): one source per metric and day.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.orm import Session

from . import mood, upstream
from .models import DailyFeature, FeatureDef, MetricSetting, StateOfMindEntry
from .today import pick_source
from .upstream import MetricDayRow, SleepDayRow, SourceDay

log = logging.getLogger("companion.features")


@dataclass(frozen=True)
class Def:
    feature: str
    label: str
    unit: str | None
    source: str
    kind: str = "continuous"
    analyse: bool = True
    family: str = "other"


# HealthLog registry categories that don't fit how the metrics relate.
FAMILY_OVERRIDES = {
    "time_in_daylight": "environment",
    "heart_rate_variability_rmssd": "vital",
    "caffeine": "nutrition",
}


def metric_family(metric: str, category: str | None) -> str:
    return FAMILY_OVERRIDES.get(metric) or (category if category and category != "unknown" else f"metric:{metric}")


@dataclass
class FeatureSet:
    defs: dict[str, Def] = field(default_factory=dict)
    values: dict[str, dict[dt.date, float]] = field(default_factory=dict)

    def add(self, d: Def, values: dict[dt.date, float]) -> None:
        if values:
            self.defs[d.feature] = d
            self.values[d.feature] = values


@dataclass(frozen=True)
class MetricRule:
    """The parts of a metric setting the assembly needs (DB-free)."""

    aggregation: str = "avg"
    min_value: float | None = None
    max_value: float | None = None
    source_priority: tuple[str, ...] = ()
    display_name: str | None = None
    unit: str | None = None
    analyse: bool = True
    category: str | None = None


def pick_metric_value(rows: list[MetricDayRow], rule: MetricRule) -> float | None:
    """One day's value for one metric under its rule: source first (R16), then aggregation, then bounds."""
    if not rows:
        return None
    chosen: MetricDayRow | None = None
    for source in rule.source_priority:
        chosen = next((r for r in rows if r.source == source), None)
        if chosen:
            break
    if chosen is None:
        merged = [r for r in rows if r.source == ""]
        chosen = merged[0] if merged else max(rows, key=lambda r: r.n)
    value = getattr(chosen, rule.aggregation)
    if value is None:
        return None
    if rule.min_value is not None and value < rule.min_value:
        return None
    if rule.max_value is not None and value > rule.max_value:
        return None
    return float(value)


def metric_features(rows: Iterable[MetricDayRow], rules: dict[str, MetricRule]) -> FeatureSet:
    grouped: dict[tuple[str, dt.date], list[MetricDayRow]] = {}
    for r in rows:
        grouped.setdefault((r.metric, r.day), []).append(r)
    by_metric: dict[str, dict[dt.date, float]] = {}
    for (metric, day), day_rows in grouped.items():
        value = pick_metric_value(day_rows, rules.get(metric, MetricRule()))
        if value is not None:
            by_metric.setdefault(metric, {})[day] = value
    out = FeatureSet()
    for metric, values in by_metric.items():
        rule = rules.get(metric, MetricRule())
        out.add(
            Def(
                f"hl.{metric}",
                rule.display_name or metric,
                rule.unit,
                "healthlog",
                analyse=rule.analyse,
                family=metric_family(metric, rule.category),
            ),
            values,
        )
    return out


SLEEP_PARTS = (
    ("total_h", "Sleep (total)"),
    ("deep_h", "Deep sleep"),
    ("core_h", "Core sleep"),
    ("rem_h", "REM sleep"),
    ("awake_h", "Awake in bed"),
)


def sleep_features(rows: Iterable[SleepDayRow]) -> FeatureSet:
    """Per wake date; one source per night (the one with the most total sleep, as on Today)."""
    best: dict[dt.date, SleepDayRow] = {}
    for r in rows:
        if r.day not in best or r.total_h > best[r.day].total_h:
            best[r.day] = r
    out = FeatureSet()
    for attr, label in SLEEP_PARTS:
        values = {day: float(getattr(r, attr)) for day, r in best.items() if getattr(r, attr) is not None}
        out.add(Def(f"sleep.{attr}", label, "h", "sleep", family="sleep"), values)
    return out


def assemble(
    metric_rows: Iterable[MetricDayRow],
    rules: dict[str, MetricRule],
    sleep_rows: Iterable[SleepDayRow],
    stress_rows: Iterable[SourceDay],
    energy: dict[dt.date, tuple[int, int]],
    workout_rows: Iterable[SourceDay],
    mood_entries: Iterable[mood.MoodEntry],
    zone: ZoneInfo,
    boundary: dt.time,
) -> FeatureSet:
    out = metric_features(metric_rows, rules)
    for part in (sleep_features(sleep_rows),):
        out.defs |= part.defs
        out.values |= part.values
    # Stress and energy reserve are computed from heart rate and HRV: same family as the vitals.
    out.add(
        Def("stress.mean", "Stress (mean of measured minutes)", None, "stress", family="vital"),
        pick_source(stress_rows),
    )
    out.add(
        Def("energy.low", "Energy reserve (low)", None, "energy", family="vital"),
        {d: float(v[0]) for d, v in energy.items()},
    )
    out.add(
        Def("energy.high", "Energy reserve (high)", None, "energy", family="vital"),
        {d: float(v[1]) for d, v in energy.items()},
    )
    out.add(Def("workout.minutes", "Workout minutes", "min", "workout", family="activity"), pick_source(workout_rows))
    mood_values, mood_names = mood.daily_features(mood_entries, zone, boundary)
    for feature, values in mood_values.items():
        kind = (
            "count" if feature == "mood.entries" or feature.startswith(("mood.label.", "mood.assoc.")) else "continuous"
        )
        out.add(Def(feature, mood_names[feature], None, "mood", kind, family="mood"), values)
    return out


# --- DB --------------------------------------------------------------------


def load_rules(db: Session) -> dict[str, MetricRule]:
    return {
        s.metric: MetricRule(
            aggregation=s.aggregation,
            min_value=s.min_value,
            max_value=s.max_value,
            source_priority=tuple(s.source_priority or ()),
            display_name=s.display_name,
            unit=s.unit,
            analyse=s.analyse,
            category=s.category,
        )
        for s in db.execute(sa.select(MetricSetting)).scalars()
    }


def load_mood_entries(db: Session) -> list[mood.MoodEntry]:
    return [
        mood.MoodEntry(e.start_time, e.kind, e.valence, tuple(e.labels or ()), tuple(e.associations or ()))
        for e in db.execute(sa.select(StateOfMindEntry)).scalars()
    ]


@dataclass(frozen=True)
class RebuildResult:
    features: int
    rows: int
    first_day: dt.date | None
    last_day: dt.date | None


def rebuild(db: Session, zone: ZoneInfo, boundary: dt.time) -> RebuildResult:
    """Recompute every feature from scratch and replace the cache (caller commits)."""
    fs = assemble(
        upstream.metric_day_rows(db, zone, boundary),
        load_rules(db),
        upstream.sleep_day_rows(db, zone),
        upstream.stress_day_rows(db, zone, boundary),
        upstream.energy_day_rows(db, zone, boundary),
        upstream.workout_day_rows(db, zone, boundary),
        load_mood_entries(db),
        zone,
        boundary,
    )
    db.execute(sa.delete(DailyFeature))
    db.execute(sa.delete(FeatureDef))
    if fs.defs:
        db.execute(
            sa.insert(FeatureDef),
            [
                {
                    "feature": d.feature,
                    "label": d.label,
                    "unit": d.unit,
                    "source": d.source,
                    "kind": d.kind,
                    "analyse": d.analyse,
                    "family": d.family,
                }
                for d in fs.defs.values()
            ],
        )
    rows = [{"day": day, "feature": f, "value": v} for f, values in fs.values.items() for day, v in values.items()]
    for start in range(0, len(rows), 5000):
        db.execute(sa.insert(DailyFeature), rows[start : start + 5000])
    days = [r["day"] for r in rows]
    result = RebuildResult(len(fs.defs), len(rows), min(days, default=None), max(days, default=None))
    log.info("daily features rebuilt: %d features, %d rows", result.features, result.rows)
    return result


def series(db: Session, feature: str) -> dict[dt.date, float]:
    rows = db.execute(sa.select(DailyFeature.day, DailyFeature.value).where(DailyFeature.feature == feature))
    return {r.day: r.value for r in rows}


def all_series(db: Session) -> dict[str, dict[dt.date, float]]:
    out: dict[str, dict[dt.date, float]] = {}
    for r in db.execute(sa.select(DailyFeature.feature, DailyFeature.day, DailyFeature.value)):
        out.setdefault(r.feature, {})[r.day] = r.value
    return out
