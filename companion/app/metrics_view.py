"""The Metrics page: each daily series' recent level against its baseline, and its weekday profile (pure)."""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

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
    "weather": "Outside",
    "almanac": "Computed",
    "goodday": "Computed",
}
