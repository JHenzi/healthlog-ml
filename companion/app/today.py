"""The Today page: yesterday's (and last night's) values as sentences against personal baselines.

Pure functions (no DB) so the wording, the baseline rule and the source
policy are unit-tested directly; ``load_today`` does the reads through the
read contract. Sentences state association-free facts with their *n* (R10, R13).
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.orm import Session

from . import highlights, outside, upstream
from .models import StateOfMindEntry
from .timeutil import day_bounds
from .upstream import SourceDay

BASELINE_DAYS = 30
# Fewer days than this in the window and we say there's no baseline yet (risks.md G2).
MIN_BASELINE_DAYS = 7
# Within this fraction of the baseline counts as "about your average".
ABOUT_FRACTION = 0.05


def pick_source(rows: Iterable[SourceDay]) -> dict[dt.date, float]:
    """One value per day under the source policy (R16): never sum across sources.

    HealthLog's merged stream (empty source) wins when present; otherwise the
    source with the most samples that day (ties: the larger value, so a partial
    capture never beats a complete one).
    """
    by_day: dict[dt.date, list[SourceDay]] = {}
    for row in rows:
        by_day.setdefault(row.day, []).append(row)
    chosen: dict[dt.date, float] = {}
    for day, candidates in by_day.items():
        merged = [c for c in candidates if c.source == ""]
        best = merged[0] if merged else max(candidates, key=lambda c: (c.n, c.value))
        chosen[day] = best.value
    return chosen


@dataclass(frozen=True)
class Baseline:
    mean: float
    n: int


def baseline(values: dict[dt.date, float], day: dt.date, window: int = BASELINE_DAYS) -> Baseline | None:
    """Mean over the ``window`` days before ``day`` (``day`` itself excluded)."""
    first = day - dt.timedelta(days=window)
    history = [v for d, v in values.items() if first <= d < day]
    if len(history) < MIN_BASELINE_DAYS:
        return None
    return Baseline(statistics.fmean(history), len(history))


# --- formatting ------------------------------------------------------------


def fmt_hours(hours: float) -> str:
    total = round(hours * 60)
    h, m = divmod(total, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def fmt_minutes_delta(hours: float) -> str:
    return fmt_hours(abs(hours))


def fmt_clock(hours: float) -> str:
    h, m = divmod(round(hours * 60), 60)
    return f"{h}:{m:02d}"


def fmt_int(value: float) -> str:
    return f"{round(value):,}"


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str  # sentence subject, e.g. "Overnight HRV"
    fmt: Callable[[float], str]
    fmt_delta: Callable[[float], str]
    more: str  # word for a positive difference
    less: str
    when: str  # "last night" / "yesterday"
    window_noun: str = "days"


SPECS: dict[str, MetricSpec] = {
    "sleep": MetricSpec("sleep", "You slept", fmt_hours, fmt_minutes_delta, "above", "below", "last night", "nights"),
    "hrv": MetricSpec(
        "hrv",
        "HRV averaged",
        lambda v: f"{round(v)} ms",
        lambda d: f"{round(abs(d))} ms",
        "above",
        "below",
        "yesterday",
    ),
    "resting_hr": MetricSpec(
        "resting_hr",
        "Resting heart rate was",
        lambda v: f"{round(v)} bpm",
        lambda d: f"{round(abs(d))} bpm",
        "above",
        "below",
        "yesterday",
    ),
    "steps": MetricSpec(
        "steps", "You walked", lambda v: f"{fmt_int(v)} steps", fmt_int, "more than", "fewer than", "yesterday"
    ),
    "stress": MetricSpec(
        "stress",
        "Average stress was",
        lambda v: f"{round(v)}",
        lambda d: f"{round(abs(d))}",
        "above",
        "below",
        "yesterday",
    ),
}


def sentence(spec: MetricSpec, value: float | None, base: Baseline | None) -> str:
    """One Today sentence. Always carries the baseline's *n* when it compares (R13)."""
    if value is None:
        return f"No {spec.key.replace('_', ' ')} data for {spec.when}."
    head = f"{spec.label} {spec.fmt(value)} {spec.when}"
    if base is None:
        return f"{head}. Not enough history for a {BASELINE_DAYS}-day baseline yet."
    avg = f"{BASELINE_DAYS}-day average ({spec.fmt(base.mean)}, {base.n} {spec.window_noun})"
    diff = value - base.mean
    if base.mean and abs(diff) <= ABOUT_FRACTION * abs(base.mean):
        return f"{head}, about your {avg}."
    direction = spec.more if diff > 0 else spec.less
    return f"{head}, {spec.fmt_delta(diff)} {direction} your {avg}."


def energy_sentence(today: tuple[int, int] | None) -> str:
    if today is None:
        return "No energy reserve data for yesterday."
    low, high = today
    return f"Your energy reserve ranged from {low} to {high} yesterday."


def mood_sentence(entries: list[tuple[float | None, tuple[str, ...]]]) -> str:
    """Yesterday's State of Mind entries: ``(valence, labels)`` each. Valence is Apple's -1 to +1 scale."""
    if not entries:
        return "No mood logged yesterday."
    count = len(entries)
    noun = "entry" if count == 1 else "entries"
    valences = [v for v, _ in entries if v is not None]
    parts = [f"You logged {count} mood {noun} yesterday"]
    if valences:
        parts.append(f"average valence {statistics.fmean(valences):+.2f} on a -1 to +1 scale")
    labels: dict[str, int] = {}
    for _, labs in entries:
        for lab in labs:
            labels[lab] = labels.get(lab, 0) + 1
    if labels:
        top = sorted(labels.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        parts.append("most often " + ", ".join(f"{k.replace('_', ' ')} ({n})" for k, n in top))
    return ", ".join(parts) + "."


# --- tiles: the same numbers, for a glance ------------------------------------

# Per metric: tile label, icon (web/templates/_icons.html), the big value and its unit, and the change.
TILE_FORMAT: dict[str, tuple[str, str, Callable[[float], tuple[str, str]], Callable[[float], str]]] = {
    "sleep": ("Sleep", "moon", lambda v: (fmt_clock(v), "h"), lambda d: fmt_hours(abs(d))),
    "hrv": ("HRV", "wave", lambda v: (f"{round(v)}", "ms"), lambda d: f"{round(abs(d))} ms"),
    "resting_hr": ("Resting heart rate", "heart", lambda v: (f"{round(v)}", "bpm"), lambda d: f"{round(abs(d))} bpm"),
    "steps": ("Steps", "steps", lambda v: (fmt_int(v), ""), fmt_int),
    "stress": ("Stress", "gauge", lambda v: (f"{round(v)}", ""), lambda d: f"{round(abs(d))}"),
}


@dataclass(frozen=True)
class Tile:
    """One value at a glance. ``direction`` is up, down or flat against the usual; None without a baseline.
    The arrow says which way, never whether that's good. ``sentence`` is the full statement, with its n (R13)."""

    key: str
    label: str
    icon: str
    value: str
    unit: str
    when: str
    change: str | None  # e.g. "1,203 more than usual", "about usual"
    direction: str | None
    sentence: str


def tile(key: str, value: float | None, base: Baseline | None) -> Tile:
    spec = SPECS[key]
    label, icon, big, delta = TILE_FORMAT[key]
    said = sentence(spec, value, base)
    if value is None:
        return Tile(key, label, icon, "–", "", spec.when, "no data", None, said)
    shown, unit = big(value)
    if base is None:
        return Tile(key, label, icon, shown, unit, spec.when, "building your usual", None, said)
    diff = value - base.mean
    if base.mean and abs(diff) <= ABOUT_FRACTION * abs(base.mean):
        return Tile(key, label, icon, shown, unit, spec.when, "about usual", "flat", said)
    more = "more than" if key == "steps" else "above"
    less = "fewer than" if key == "steps" else "below"
    change = f"{delta(diff)} {more if diff > 0 else less} usual"
    return Tile(key, label, icon, shown, unit, spec.when, change, "up" if diff > 0 else "down", said)


def energy_tile(today: tuple[int, int] | None) -> Tile:
    said = energy_sentence(today)
    if today is None:
        return Tile("energy", "Energy reserve", "battery", "–", "", "yesterday", "no data", None, said)
    return Tile(
        "energy", "Energy reserve", "battery", f"{today[0]}–{today[1]}", "", "yesterday", "low to high", None, said
    )


def mood_tile(entries: list[tuple[float | None, tuple[str, ...]]]) -> Tile:
    said = mood_sentence(entries)
    if not entries:
        return Tile("mood", "Mood", "smile", "–", "", "yesterday", "nothing logged", None, said)
    labels: dict[str, int] = {}
    for _, labs in entries:
        for lab in labs:
            labels[lab] = labels.get(lab, 0) + 1
    valences = [v for v, _ in entries if v is not None]
    if labels:
        shown = sorted(labels.items(), key=lambda kv: (-kv[1], kv[0]))[0][0].replace("_", " ")
    else:
        shown = f"{statistics.fmean(valences):+.2f}" if valences else "logged"
    n = len(entries)
    return Tile("mood", "Mood", "smile", shown, "", "yesterday", f"{n} {'entry' if n == 1 else 'entries'}", None, said)


# --- assembly --------------------------------------------------------------


@dataclass(frozen=True)
class TodayView:
    day: dt.date  # the current Companion day
    sentences: list[str]
    problems: list[str]
    tiles: tuple[Tile, ...] = ()
    notes: tuple[str, ...] = ()  # worth noting: a weather change, streaks, records


def build_sentences(
    series: dict[str, dict[dt.date, float]],
    energy: dict[dt.date, tuple[int, int]],
    today: dt.date,
) -> list[str]:
    """Sentences for the Today page. Sleep is last night's (wake date = today); the rest is yesterday's."""
    yesterday = today - dt.timedelta(days=1)
    out = []
    for key, spec in SPECS.items():
        values = series.get(key, {})
        day = today if spec.when == "last night" else yesterday
        out.append(sentence(spec, values.get(day), baseline(values, day)))
    out.append(energy_sentence(energy.get(yesterday)))
    return out


def build_tiles(
    series: dict[str, dict[dt.date, float]],
    energy: dict[dt.date, tuple[int, int]],
    moods: list[tuple[float | None, tuple[str, ...]]],
    today: dt.date,
) -> tuple[Tile, ...]:
    """The Overview tiles: the same values as the sentences, in the same order."""
    yesterday = today - dt.timedelta(days=1)
    out = []
    for key, spec in SPECS.items():
        values = series.get(key, {})
        day = today if spec.when == "last night" else yesterday
        out.append(tile(key, values.get(day), baseline(values, day)))
    out.append(energy_tile(energy.get(yesterday)))
    out.append(mood_tile(moods))
    return tuple(out)


# HealthLog metric names (upstream registry keys) and their daily aggregation.
_METRICS = {
    "hrv": ("heart_rate_variability", "avg"),
    "resting_hr": ("resting_heart_rate", "avg"),
    "steps": ("step_count", "sum"),
}


def _safe(db: Session, problems: list[str], label: str, read: Callable[[], object], empty: object) -> object:
    """Run one read in a savepoint; a broken contract table degrades that line, not the page."""
    try:
        with db.begin_nested():
            return read()
    except Exception as exc:  # noqa: BLE001 - surfaced on the page and in the log
        problems.append(f"{label}: read failed ({type(exc).__name__})")
        return empty


def load_today(db: Session, zone: ZoneInfo, boundary: dt.time, today: dt.date) -> TodayView:
    problems = [str(p) for p in upstream.check_upstream(db)]
    first = today - dt.timedelta(days=BASELINE_DAYS + 1)
    yesterday = today - dt.timedelta(days=1)
    series: dict[str, dict[dt.date, float]] = {}
    for key, (metric, agg) in _METRICS.items():
        rows = _safe(
            db,
            problems,
            key,
            lambda m=metric, a=agg: upstream.metric_by_source(db, m, a, zone, boundary, first, yesterday),
            [],
        )
        series[key] = pick_source(rows)
    series["sleep"] = pick_source(
        _safe(db, problems, "sleep", lambda: upstream.sleep_by_source(db, zone, first, today), [])
    )
    series["stress"] = pick_source(
        _safe(db, problems, "stress", lambda: upstream.stress_daily(db, zone, boundary, first, yesterday), [])
    )
    energy = _safe(
        db,
        problems,
        "energy reserve",
        lambda: upstream.energy_reserve_daily(db, zone, boundary, yesterday, yesterday),
        {},
    )
    lines = build_sentences(series, energy, today)
    start, end = day_bounds(yesterday, zone, boundary)
    moods = db.execute(
        sa.select(StateOfMindEntry.valence, StateOfMindEntry.labels).where(
            StateOfMindEntry.start_time >= start, StateOfMindEntry.start_time < end
        )
    ).all()
    mood_entries = [(v, tuple(labels or ())) for v, labels in moods]
    lines.append(mood_sentence(mood_entries))
    now = dt.datetime.now(dt.UTC)
    note = _safe(
        db,
        problems,
        "weather",
        lambda: outside.weather_note(outside.stored_hours(db, now - dt.timedelta(hours=60)), now),
        None,
    )
    notes = [note] if note else []
    notes += [n.text for n in _safe(db, problems, "highlights", lambda: highlights.load_highlights(db, today), [])]
    return TodayView(today, lines, problems, build_tiles(series, energy, mood_entries, today), tuple(notes))
