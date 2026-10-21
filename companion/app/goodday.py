"""The good-day score: one number per day for "was this a good day?", built the way the user defined it.

A good day is active, isn't short on sleep or water, and has a good mood. Four parts, equal weights:

- **Active**: steps, exercise minutes and active energy.
- **Sleep**: total sleep, the night before the day (sleep is keyed by wake date).
- **Water**: water logged.
- **Mood**: mean State of Mind valence.

Each component is ranked against your own history: its percentile among all your recorded days (0 the lowest,
100 the highest; ties share a rank). A part is the mean of its components that day, and the score is the mean of
the parts that day, needing at least ``MIN_PARTS`` of them. Missing is not zero (R7): a part without data is
left out, never counted as 0. Higher counts as better for every part, because that is the definition; goals
(enough sleep, enough water) are a later setting, not a guess. Ranks use all of the history, so a day's score
can move a little as more days arrive.

The score is a daily feature like any other (``goodday.score``): the engine tests it against every series except
the families it is built from, which are linked to it by definition (R17). Pure, apart from ``load_view``.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Mapping
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .models import DailyFeature, FeatureDef, Insight

FEATURE = "goodday.score"
LABEL = "Good-day score"
SOURCE = FAMILY = "goodday"
PARTS = (
    ("active", "Active", ("hl.step_count", "hl.apple_exercise_time", "hl.active_energy")),
    ("sleep", "Sleep", ("sleep.total_h",)),
    ("water", "Water", ("hl.dietary_water",)),
    ("mood", "Mood", ("mood.valence_mean",)),
)
COMPONENTS = tuple(f for _, _, features in PARTS for f in features)
MIN_PARTS = 2  # one part alone would be that part's rank, not a day's score
MIN_COMPONENT_DAYS = 14  # a rank among fewer days says little
BEST_SHARE = 0.25  # "your best days": the top quarter
MIN_SCORED_DAYS = 12  # before this, there is no top quarter to speak of
RECENT_DAYS = 14


def percentiles(values: Mapping[dt.date, float]) -> dict[dt.date, float]:
    """Each day's percentile rank among all the days (0–100): the share below it, plus half the share equal."""
    ordered = sorted(values.values())
    n = len(ordered)
    out = {}
    for day, v in values.items():
        below = _count_below(ordered, v)
        equal = _count_below(ordered, v, inclusive=True) - below
        out[day] = (below + equal / 2) / n * 100
    return out


def _count_below(ordered: list[float], v: float, inclusive: bool = False) -> int:
    lo, hi = 0, len(ordered)
    while lo < hi:
        mid = (lo + hi) // 2
        if ordered[mid] < v or (inclusive and ordered[mid] == v):
            lo = mid + 1
        else:
            hi = mid
    return lo


@dataclass(frozen=True)
class DayScore:
    day: dt.date
    score: float
    parts: dict[str, float]  # part key -> 0–100, only the parts with data that day


def scores(series: Mapping[str, Mapping[dt.date, float]]) -> dict[dt.date, DayScore]:
    ranks = {f: percentiles(series[f]) for f in COMPONENTS if len(series.get(f, {})) >= MIN_COMPONENT_DAYS}
    days = {day for r in ranks.values() for day in r}
    out = {}
    for day in sorted(days):
        parts = {}
        for key, _, features in PARTS:
            found = [ranks[f][day] for f in features if f in ranks and day in ranks[f]]
            if found:
                parts[key] = statistics.fmean(found)
        if len(parts) >= MIN_PARTS:
            out[day] = DayScore(day, statistics.fmean(parts.values()), parts)
    return out


def built_from(families: Mapping[str, str]) -> tuple[str, ...]:
    """The families of the components present (feature -> family): the score is linked to these by definition."""
    return tuple(sorted({families[f] for f in COMPONENTS if f in families}))


def best_days(day_scores: Mapping[dt.date, DayScore]) -> tuple[float | None, set[dt.date]]:
    """The top quarter of scored days: the threshold and the days at or above it (none before enough days)."""
    if len(day_scores) < MIN_SCORED_DAYS:
        return None, set()
    values = sorted(s.score for s in day_scores.values())
    threshold = values[min(len(values) - 1, int(len(values) * (1 - BEST_SHARE)))]
    return threshold, {d for d, s in day_scores.items() if s.score >= threshold}


def rank_of(score: float, day_scores: Mapping[dt.date, DayScore]) -> int:
    """The share of scored days (in %) below this score."""
    return round(sum(1 for s in day_scores.values() if s.score < score) / len(day_scores) * 100)


# --- the page -----------------------------------------------------------------


@dataclass(frozen=True)
class Part:
    key: str
    label: str
    value: float | None


@dataclass(frozen=True)
class Day:
    day: dt.date
    score: float | None
    parts: tuple[Part, ...]
    best: bool


@dataclass(frozen=True)
class Common:
    """A reported finding about the score, with the other series' medians on best days and the rest (same day)."""

    insight: Insight
    label: str
    unit: str | None
    best: float | None
    rest: float | None
    n_best: int
    n_rest: int


@dataclass(frozen=True)
class GoodDayView:
    yesterday: Day
    rank: int | None  # yesterday's score is higher than this % of scored days
    scored: int
    recent: tuple[Day, ...]  # newest first
    threshold: float | None
    best: tuple[dt.date, ...]  # newest first
    common: tuple[Common, ...]
    present: tuple[str, ...]  # part labels with enough data to count


def _day(day: dt.date, day_scores: Mapping[dt.date, DayScore], best: set[dt.date]) -> Day:
    s = day_scores.get(day)
    parts = tuple(Part(key, label, s.parts.get(key) if s else None) for key, label, _ in PARTS)
    return Day(day, s.score if s else None, parts, day in best)


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def common(
    insights: list[Insight],
    series: Mapping[str, Mapping[dt.date, float]],
    defs: Mapping[str, FeatureDef],
    day_scores: Mapping[dt.date, DayScore],
    best: set[dt.date],
) -> tuple[Common, ...]:
    out = []
    for i in insights:
        if i.kind != "association" or FEATURE not in (i.feature_a, i.feature_b):
            continue
        other = i.feature_b if i.feature_a == FEATURE else i.feature_a
        d = defs.get(other)
        values = series.get(other, {})
        on_best = [values[day] for day in day_scores if day in best and day in values]
        on_rest = [values[day] for day in day_scores if day not in best and day in values]
        out.append(
            Common(
                i,
                d.label if d else other,
                d.unit if d else None,
                _median(on_best),
                _median(on_rest),
                len(on_best),
                len(on_rest),
            )
        )
    return tuple(out)


def view(
    series: Mapping[str, Mapping[dt.date, float]],
    defs: Mapping[str, FeatureDef],
    insights: list[Insight],
    today: dt.date,
) -> GoodDayView:
    day_scores = scores(series)
    threshold, best = best_days(day_scores)
    yesterday = today - dt.timedelta(days=1)
    y = _day(yesterday, day_scores, best)
    rank = rank_of(y.score, day_scores) if y.score is not None else None
    recent = tuple(_day(yesterday - dt.timedelta(days=k), day_scores, best) for k in range(RECENT_DAYS))
    present = tuple(
        label for _, label, features in PARTS if any(len(series.get(f, {})) >= MIN_COMPONENT_DAYS for f in features)
    )
    return GoodDayView(
        y,
        rank,
        len(day_scores),
        recent,
        threshold,
        tuple(sorted(best, reverse=True)),
        common(insights, series, defs, day_scores, best),
        present,
    )


def load_view(db: Session, today: dt.date) -> GoodDayView:
    insights = list(
        db.execute(
            sa.select(Insight)
            .where(sa.or_(Insight.feature_a == FEATURE, Insight.feature_b == FEATURE))
            .order_by(Insight.score.desc())
        ).scalars()
    )
    others = {i.feature_b if i.feature_a == FEATURE else i.feature_a for i in insights} - {None}
    wanted = [*COMPONENTS, *others]
    series: dict[str, dict[dt.date, float]] = {}
    rows = db.execute(
        sa.select(DailyFeature.feature, DailyFeature.day, DailyFeature.value).where(
            DailyFeature.feature.in_(wanted), DailyFeature.day < today
        )
    )
    for r in rows:
        series.setdefault(r.feature, {})[r.day] = r.value
    defs = {d.feature: d for d in db.execute(sa.select(FeatureDef).where(FeatureDef.feature.in_(wanted))).scalars()}
    return view(series, defs, insights, today)
