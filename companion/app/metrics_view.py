"""The Metrics page: each daily series' recent level against its baseline, and its weekday profile (pure)."""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

from .goodday import percentiles

WINDOW_DAYS = 30
MIN_DAYS = 7
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class WindowStat:
    mean: float
    n: int


def window(values: dict[dt.date, float], end: dt.date, days: int = WINDOW_DAYS) -> WindowStat | None:
    """Mean over ``(end - days, end]``; None below ``MIN_DAYS`` observed days."""
    vals = [v for d, v in values.items() if end - dt.timedelta(days=days) < d <= end]
    return WindowStat(statistics.fmean(vals), len(vals)) if len(vals) >= MIN_DAYS else None


@dataclass(frozen=True)
class Summary:
    latest_day: dt.date | None
    latest: float | None
    recent: WindowStat | None  # last 30 days
    prior: WindowStat | None  # the 30 days before that
    change_pct: float | None
    weekday: tuple[WindowStat | None, ...]  # Mon..Sun over the whole history
    days: int


def summarize(values: dict[dt.date, float], today: dt.date) -> Summary:
    if not values:
        return Summary(None, None, None, None, None, (None,) * 7, 0)
    latest_day = max(d for d in values if d <= today) if any(d <= today for d in values) else None
    end = today - dt.timedelta(days=1)  # today is still running
    recent = window(values, end)
    prior = window(values, end - dt.timedelta(days=WINDOW_DAYS))
    change = None
    if recent and prior and prior.mean:
        change = (recent.mean - prior.mean) / abs(prior.mean) * 100
    by_weekday: list[list[float]] = [[] for _ in range(7)]
    for d, v in values.items():
        by_weekday[d.weekday()].append(v)
    weekday = tuple(WindowStat(statistics.fmean(vs), len(vs)) if len(vs) >= 2 else None for vs in by_weekday)
    return Summary(
        latest_day,
        values.get(latest_day) if latest_day else None,
        recent,
        prior,
        change,
        weekday,
        len(values),
    )


def fmt(value: float | None, unit: str | None = None) -> str:
    if value is None:
        return "–"
    magnitude = abs(value)
    if magnitude >= 100 or float(value).is_integer():
        text = f"{value:,.0f}"  # counts and scale steps read as whole numbers: "3 cups", not "3.00 cups"
    else:
        text = f"{value:,.1f}" if magnitude >= 10 else f"{value:,.2f}"
    return f"{text} {unit}" if unit else text


def sparkline(values: dict[dt.date, float], end: dt.date, days: int = 60, width: int = 240, height: int = 40) -> str:
    """SVG polyline points for the last ``days`` days (gaps stay gaps: separate segments)."""
    start = end - dt.timedelta(days=days - 1)
    window_vals = {d: v for d, v in values.items() if start <= d <= end}
    if len(window_vals) < 2:
        return ""
    lo, hi = min(window_vals.values()), max(window_vals.values())
    span = (hi - lo) or 1.0
    segments: list[list[str]] = [[]]
    for i in range(days):
        day = start + dt.timedelta(days=i)
        if day not in window_vals:
            if segments[-1]:
                segments.append([])
            continue
        x = i * (width - 2) / (days - 1) + 1
        y = height - 1 - (window_vals[day] - lo) / span * (height - 2)
        segments[-1].append(f"{x:.1f},{y:.1f}")
    return "|".join(" ".join(seg) for seg in segments if seg)


def band(rank: float | None) -> int | None:
    """One of five colour bands for a 0–100 rank (clay low → sand → moss high), as on the Good days page."""
    return None if rank is None else min(int(rank // 20), 4)


@dataclass(frozen=True)
class Glance:
    """One tile on the My Metrics page: the latest value, how it ranks among your own days, and its last 60 days."""

    latest_rank: float | None  # 0–100 among every recorded day; None below MIN_RANK_DAYS
    spark: tuple[str, ...]  # polyline segments, gaps left as gaps
    dot: tuple[float, float] | None  # the newest point of the sparkline
    cells: tuple[tuple[dt.date, float | None, int | None], ...]  # last 30 days: (day, value, band)


MIN_RANK_DAYS = 14  # a rank among fewer days says little (same floor as the good-day score)


def ranks(values: dict[dt.date, float]) -> dict[dt.date, float]:
    """Each day's percentile among your own days, or nothing below ``MIN_RANK_DAYS`` days."""
    return percentiles(values) if len(values) >= MIN_RANK_DAYS else {}


def glance(values: dict[dt.date, float], summary: Summary, today: dt.date) -> Glance:
    end = today - dt.timedelta(days=1)
    ranked = ranks(values)
    spark = tuple(seg for seg in sparkline(values, end).split("|") if seg)
    dot = None
    if spark:
        x, y = spark[-1].split(" ")[-1].split(",")
        dot = (float(x), float(y))
    latest_rank = ranked.get(summary.latest_day) if summary.latest_day else None
    cells = tuple(
        (day, values.get(day), band(ranked.get(day)))
        for day in (end - dt.timedelta(days=i) for i in range(WINDOW_DAYS - 1, -1, -1))
    )
    return Glance(latest_rank, spark, dot, cells)


MOOD_SERIES = ("mood.valence_mean", "mood.valence_min", "mood.daily_valence", "mood.momentary_valence")


@dataclass(frozen=True)
class MoodBar:
    day: dt.date
    mean: float | None  # -1 (very unpleasant) .. 1 (very pleasant); None: nothing logged
    low: float | None  # the day's lowest moment
    band: int | None  # clay below neutral → moss above, the Good days colours


def mood_bars(mean: dict[dt.date, float], low: dict[dt.date, float], today: dt.date) -> list[MoodBar]:
    """The last 30 days of State of Mind as one chart: each day's average valence and its lowest moment."""
    end = today - dt.timedelta(days=1)
    out = []
    for i in range(WINDOW_DAYS - 1, -1, -1):
        day = end - dt.timedelta(days=i)
        m = mean.get(day)
        out.append(MoodBar(day, m, low.get(day), band((m + 1) / 2 * 100) if m is not None else None))
    return out


FLUID_WATER = "hl.dietary_water"
FLUID_SERIES = (FLUID_WATER, "hl.dietary_water_from_caffeine", "hl.dietary_water_from_alcohol_consumption")


@dataclass(frozen=True)
class FluidDay:
    day: dt.date
    water: float | None  # plain water
    coffee: float | None  # water Health counts for coffee
    alcohol: float | None  # negative: what Health takes off for a drink
    net: float | None  # the three added up: Apple Health's total; None when none of them has a value (R7)


@dataclass(frozen=True)
class FluidChart:
    days: tuple[FluidDay, ...]
    top: float  # the tallest day above the axis (water + coffee)
    bottom: float  # the deepest day below it (alcohol, as a positive number)


def fluid_chart(
    water: dict[dt.date, float], coffee: dict[dt.date, float], alcohol: dict[dt.date, float], today: dt.date
) -> FluidChart | None:
    """Roadmap B15: the last 30 days of water as one stack, alcohol below the axis and the net marked.

    Presentation only: the analysis keeps the three series apart. None when there's nothing to draw.
    """
    end = today - dt.timedelta(days=1)
    days = []
    for i in range(WINDOW_DAYS - 1, -1, -1):
        day = end - dt.timedelta(days=i)
        parts = (water.get(day), coffee.get(day), alcohol.get(day))
        present = [v for v in parts if v is not None]
        days.append(FluidDay(day, *parts, sum(present) if present else None))
    if all(d.net is None for d in days):
        return None
    top = max((max(d.water or 0, 0) + max(d.coffee or 0, 0) for d in days), default=0)
    bottom = max((-min(d.alcohol or 0, 0) for d in days), default=0)
    return FluidChart(tuple(days), top or 1.0, bottom)


def coverage(days_with_data: set[dt.date], end: dt.date, days: int = WINDOW_DAYS) -> list[tuple[dt.date, bool]]:
    """``(day, recorded)`` for the ``days`` days ending at ``end``, oldest first (the Overview coverage strip)."""
    start = end - dt.timedelta(days=days - 1)
    return [(start + dt.timedelta(days=i), start + dt.timedelta(days=i) in days_with_data) for i in range(days)]


# How each feature source is labelled wherever a metric appears (wireframe 3b: provenance tags).
PROVENANCE = {
    "healthlog": "Imported",
    "sleep": "Imported",
    "workout": "Imported",
    "mood": "Imported",
    "stress": "Derived",
    "energy": "Derived",
    "tracker": "Logged",
    "rating": "Logged",
    "weather": "Outside",
    "almanac": "Computed",
    "goodday": "Computed",
}
