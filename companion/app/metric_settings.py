"""Per-metric settings: seeded from HealthLog's registry, then ours to edit (plan M2).

HealthLog's registry decides how *it* aggregates a metric and which 19 metrics
its analysis uses. The Companion keeps its own copy so every metric can be
analysed and its daily aggregation, plausibility bounds and source priority can
be changed without touching HealthLog. Re-seeding fills in new metrics and
refreshes untouched ones; it never overwrites a row the user edited.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from . import upstream
from .auth import now_utc
from .models import MetricSetting

AGGREGATIONS = ("sum", "avg", "min", "max")


def default_aggregation(agg_default: str | None) -> str:
    return agg_default if agg_default in AGGREGATIONS else "avg"


@dataclass
class SeedResult:
    added: int = 0
    refreshed: int = 0


def seed(db: Session) -> SeedResult:
    result = SeedResult()
    for row in upstream.registry(db):
        current = db.get(MetricSetting, row["metric"])
        values = {
            "display_name": row["display_name"] or row["metric"],
            "unit": row["unit_canonical"],
            "category": row["category"],
            "aggregation": default_aggregation(row["agg_default"]),
        }
        if current is None:
            db.add(MetricSetting(metric=row["metric"], **values))
            result.added += 1
        elif not current.user_edited and any(getattr(current, k) != v for k, v in values.items()):
            for key, value in values.items():
                setattr(current, key, value)
            current.updated_at = now_utc()
            result.refreshed += 1
    db.flush()
    return result


def update(
    db: Session,
    metric: str,
    *,
    aggregation: str,
    analyse: bool,
    min_value: float | None,
    max_value: float | None,
    source_priority: list[str],
) -> MetricSetting:
    """Validate and apply an edit from the Metrics page; marks the row as user-edited."""
    setting = db.get(MetricSetting, metric)
    if setting is None:
        raise KeyError(metric)
    if aggregation not in AGGREGATIONS:
        raise ValueError(f"aggregation must be one of {', '.join(AGGREGATIONS)}")
    if min_value is not None and max_value is not None and min_value > max_value:
        raise ValueError("the lower bound is above the upper bound")
    setting.aggregation = aggregation
    setting.analyse = analyse
    setting.min_value = min_value
    setting.max_value = max_value
    setting.source_priority = [s for s in (p.strip() for p in source_priority) if s]
    setting.user_edited = True
    setting.updated_at = now_utc()
    return setting


def reset(db: Session, metric: str) -> None:
    """Forget the user's edits; the next seed restores HealthLog's defaults."""
    setting = db.get(MetricSetting, metric)
    if setting is not None:
        setting.user_edited = False
        setting.min_value = None
        setting.max_value = None
        setting.source_priority = []
        setting.analyse = True
