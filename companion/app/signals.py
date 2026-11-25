"""Signals: what is changing in your own series, right now and over weeks (roadmap B20; reflection §4e).

Three questions, each answered against your own history only:

- **Now**: are the last few days (``NOW_DAYS``) away from your usual?
- **Trend**: are the last two weeks (``TREND_DAYS``) away from your usual? This is "am I slipping, or climbing?",
  and it names the highest or lowest two-week stretch on record for context ("was 7.0 h Nov 2–15, now 5.6 h").
- **Gap**: has a series that arrives almost every day stopped arriving (the Watch off, a sync stalled)?

Words are **up** and **down**, never better or worse (owner's decision, 2026-11-25): which way is good is yours to
judge, and the engine holds no theory of it (R17). Every series is checked the same way; the only choices are
about measurement quality (R17 allows them): minimum days, an effect floor, and a bar that accounts for
day-to-day carry-over, so a run of ordinary autocorrelated days isn't called a change. The bar's false-alarm rate
is checked on pure noise in ``tests/stats/test_signals_validation.py`` (R8).

Weather and the almanac are left out of the Overview's signals: they describe the place, not you. That is a
presentation choice, not an analysis one; the engine still tests them against everything.

Pure, apart from the ``load_*`` functions and the pin setting at the bottom.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .auth import now_utc
from .clock import clock_text, is_clock, shift_text
from .models import DailyFeature, FeatureDef, Setting

NOW_DAYS = 3  # "right now": the last few complete days
TREND_DAYS = 14  # "lately": the last two weeks
TREND_MIN = 10
WEEK_DAYS = 7  # the pins' "this week"
WEEK_MIN = 4
BASELINE_DAYS = 60  # your usual: the days before the window, up to this many
BASELINE_MIN = 21  # fewer than this and there's no usual yet
Z_BAR = 3.5  # the bar across every series at once, after allowing for carry-over between days (see the module doc)
Z_PIN = 2.0  # the bar for a series you pinned: a handful you chose to watch, not a search across everything
FLOOR = 0.5  # and the shift must be at least half a usual day-to-day spread
NOW_Z = 3.0  # … and the carry-over-adjusted score at least this far out
RANGE_Q = 0.05  # "right now" is every one of the last days below your 5th or above your 95th percentile
GAP_DAYS = 3  # a series missing this many days in a row …
GAP_COVERAGE = 0.9  # … after arriving on at least 90% of the 30 days before
MAX_SIGNALS = 4
LONG_WEEKS = 26  # the pins' and the Trends page's weekly chart
EXCLUDED_SOURCES = ("weather", "almanac")  # about the place, not you (presentation only)
PINS_KEY = "pins"
DEFAULT_PINS = ("sleep.total_h", "hl.apple_exercise_time", "hl.step_count", "hl.resting_heart_rate")
MAX_PINS = 8


@dataclass(frozen=True)
class Def:
    label: str
    unit: str | None
    source: str
    kind: str = "continuous"
    family: str = "other"


@dataclass(frozen=True)
class Compare:
    """A window of recent days against your usual: the measurement behind every signal and pin."""

    recent: float  # mean of the window
    usual: float  # mean of the baseline
    spread: float  # the baseline's day-to-day standard deviation
    n_recent: int
    n_usual: int
    z: float  # the shift in standard errors, allowing for carry-over between days
    first: dt.date  # first day of the window
    last: dt.date  # last day of the window
    bar: float = Z_BAR
    beyond: bool | None = None  # "right now": set when the rule is "every day outside your range", not the z bar

    @property
    def shift(self) -> float:
        return self.recent - self.usual

    @property
    def clear(self) -> bool:
        if self.beyond is not None:
            return self.beyond
        return abs(self.z) >= self.bar and abs(self.shift) >= FLOOR * self.spread

    @property
    def direction(self) -> str | None:
        if not self.clear:
            return None
        return "up" if self.shift > 0 else "down"


@dataclass(frozen=True)
class Stretch:
    """The highest or lowest run of ``TREND_DAYS`` on record (by its mean)."""

    mean: float
    first: dt.date
    last: dt.date


@dataclass(frozen=True)
class Signal:
    kind: str  # now | trend | gap
    feature: str
    family: str
    direction: str | None  # up | down; None for a gap
    text: str
    evidence: str  # the days behind it (R13)
    strength: float  # for ordering: |z|, or the coverage for a gap

    @property
    def key(self) -> str:
        """Stable across days while the signal holds: notifications use it so one change is sent once."""
        return f"{self.feature}:{self.kind}:{self.direction or 'gap'}"


# --- measurement --------------------------------------------------------------------------------------------


def lag1(values: Mapping[dt.date, float]) -> float:
    """Day-to-day carry-over: the correlation between consecutive recorded days, clipped to [0, 0.9].

    A short series underestimates it (by about (1 + 3r) / n), so that much is added back (Kendall's correction).
    """
    pairs = [(v, values[d + dt.timedelta(days=1)]) for d, v in values.items() if d + dt.timedelta(days=1) in values]
    if len(pairs) < 10:
        return 0.0
    a, b = zip(*pairs, strict=True)
    if statistics.pstdev(a) == 0 or statistics.pstdev(b) == 0:
        return 0.0
    r = statistics.correlation(a, b)
    r += (1 + 3 * max(r, 0.0)) / len(pairs)
    return min(max(r, 0.0), 0.9)


def effective(n: int, r: float) -> float:
    """How many independent days ``n`` carried-over days are worth: exact for an AR(1) mean, so it holds at n = 3."""
    if r <= 0:
        return float(n)
    weight = n + 2 * sum((n - k) * r**k for k in range(1, n))
    return n * n / weight


def normal_scores(values: Mapping[dt.date, float]) -> dict[dt.date, float]:
    """Each value as its rank among all of them, on a normal scale: a long tail (steps) can't fake a change."""
    ordered = sorted(values, key=lambda d: values[d])
    n = len(ordered)
    dist = statistics.NormalDist()
    out: dict[dt.date, float] = {}
    i = 0
    while i < n:  # ties share their average rank
        j = i
        while j + 1 < n and values[ordered[j + 1]] == values[ordered[i]]:
            j += 1
        score = dist.inv_cdf(((i + j) / 2 + 0.625) / (n + 0.25))  # Blom's plotting position
        for k in range(i, j + 1):
            out[ordered[k]] = score
        i = j + 1
    return out


def _days(end: dt.date, count: int) -> list[dt.date]:
    return [end - dt.timedelta(days=k) for k in range(count)]


def compare(
    values: Mapping[dt.date, float], end: dt.date, window: int, min_days: int, bar: float = Z_BAR
) -> Compare | None:
    """The ``window`` days ending on ``end`` against up to ``BASELINE_DAYS`` before them."""
    recent = [values[d] for d in _days(end, window) if d in values]
    if len(recent) < min_days:
        return None
    first = end - dt.timedelta(days=window - 1)
    base = {d: values[d] for d in _days(first - dt.timedelta(days=1), BASELINE_DAYS) if d in values}
    if len(base) < BASELINE_MIN:
        return None
    spread = statistics.stdev(base.values())
    if spread == 0:
        return None
    # The test runs on rank-normal scores of window and baseline together; what's shown stays in your units.
    win = {d: values[d] for d in _days(end, window) if d in values}
    scores = normal_scores({**base, **win})
    s_base = [scores[d] for d in base]
    s_win = [scores[d] for d in win]
    s_spread = statistics.stdev(s_base) or 1.0
    r = lag1({d: scores[d] for d in base})
    se = s_spread * math.sqrt(1 / effective(len(s_win), r) + 1 / effective(len(s_base), r))
    z = (statistics.fmean(s_win) - statistics.fmean(s_base)) / se
    usual = statistics.fmean(base.values())
    return Compare(statistics.fmean(recent), usual, spread, len(recent), len(base), z, first, end, bar)


def outside_range(values: Mapping[dt.date, float], end: dt.date) -> Compare | None:
    """The last ``NOW_DAYS`` days, every one of them recorded and beyond your range, all on the same side.

    A run of days each outside what you usually see (reflection §4e, "out of your range"). Three days alone
    can't carry a strong average-based test, but all three past your 5th or 95th percentile is rare on noise, and
    the score that allows for carry-over must agree, or a slow drift would pass for a sudden change.
    """
    c = compare(values, end, NOW_DAYS, NOW_DAYS)
    if c is None:
        return None
    base = sorted(values[d] for d in _days(c.first - dt.timedelta(days=1), BASELINE_DAYS) if d in values)
    k = max(int(len(base) * RANGE_Q), 1)
    low, high = base[k - 1], base[-k]
    recent = [values[d] for d in _days(end, NOW_DAYS)]
    beyond = all(v < low for v in recent) or all(v > high for v in recent)
    # Carried-over days drift outside the range together, so the carry-over-adjusted score must agree too.
    return dataclasses.replace(c, beyond=beyond and c.shift != 0 and abs(c.z) >= NOW_Z)


def stretch(values: Mapping[dt.date, float], before: dt.date, highest: bool) -> Stretch | None:
    """The highest (or lowest) two-week stretch that ended before ``before``, from windows with enough days."""
    if not values:
        return None
    best: Stretch | None = None
    day = min(values) + dt.timedelta(days=TREND_DAYS - 1)
    while day < before:
        vals = [values[d] for d in _days(day, TREND_DAYS) if d in values]
        if len(vals) >= TREND_MIN:
            m = statistics.fmean(vals)
            if best is None or (m > best.mean if highest else m < best.mean):
                best = Stretch(m, day - dt.timedelta(days=TREND_DAYS - 1), day)
        day += dt.timedelta(days=1)
    return best


def end_day(source: str, values: Mapping[dt.date, float], today: dt.date) -> dt.date:
    """The last complete day: sleep is keyed by the morning you woke, so today's night counts once it's in."""
    if source == "sleep" and today in values:
        return today
    return today - dt.timedelta(days=1)


# --- wording ------------------------------------------------------------------------------------------------


def fmt(value: float, unit: str | None) -> str:
    if is_clock(unit):
        return clock_text(value, unit)
    if unit == "h":
        h, m = divmod(round(value * 60), 60)
        return f"{h} h {m:02d} min" if h else f"{m} min"
    if unit == "count":
        unit = None
    number = f"{round(value):,}" if abs(value) >= 100 else f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{number} {unit}" if unit else number


def change_text(c: Compare, unit: str | None) -> str:
    """'up 1 h 05 min' / 'down 18%' / '1 h 10 min later': the size of a shift, no judgement."""
    if is_clock(unit):
        return shift_text(c.shift)
    word = "up" if c.shift > 0 else "down"
    if unit == "h" or abs(c.usual) < 10:  # a percent of a small count or a score reads oddly
        return f"{word} {fmt(abs(c.shift), unit)}"
    return f"{word} {abs(c.shift) / c.usual * 100:.0f}%"


def _span(first: dt.date, last: dt.date) -> str:
    if first.month == last.month:
        return f"{first.strftime('%b %-d')}–{last.day}"
    return f"{first.strftime('%b %-d')}–{last.strftime('%b %-d')}"


def _per(source: str) -> str:
    return "night" if source == "sleep" else "day"


def now_signal(feature: str, d: Def, c: Compare) -> Signal:
    span = f"the last {NOW_DAYS} {_per(d.source)}s"
    text = f"{d.label}: {fmt(c.recent, d.unit)} on average over {span}, {change_text(c, d.unit)} on your usual."
    per = _per(d.source)
    usual = fmt(c.usual, d.unit)
    evidence = f"{c.n_recent} of {NOW_DAYS} {per}s against your usual of {usual} ({c.n_usual} days before)."
    return Signal("now", feature, d.family, c.direction, text, evidence, abs(c.z))


def trend_signal(feature: str, d: Def, c: Compare, values: Mapping[dt.date, float], now: Compare | None) -> Signal:
    change = change_text(c, d.unit)
    text = f"{d.label}: {fmt(c.recent, d.unit)} on average over the last 2 weeks, {change} on your usual."
    extra = []
    # Context only, no new test: the stretch on record furthest the other way ("was higher, now lower").
    other = stretch(values, c.first, highest=c.shift < 0)
    if other is not None and (other.mean - c.recent) * (1 if c.shift < 0 else -1) > 0:
        word = "highest" if c.shift < 0 else "lowest"
        extra.append(f"Your {word} 2 weeks on record: {fmt(other.mean, d.unit)} ({_span(other.first, other.last)}).")
    if now is not None and now.direction == c.direction:
        extra.append(f"The last {NOW_DAYS} {_per(d.source)}s: {fmt(now.recent, d.unit)}.")
    if extra:
        text = f"{text} {' '.join(extra)}"
    evidence = (
        f"{c.n_recent} of {TREND_DAYS} days ({_span(c.first, c.last)}) against your usual of "
        f"{fmt(c.usual, d.unit)} ({c.n_usual} days before)."
    )
    return Signal("trend", feature, d.family, c.direction, text, evidence, abs(c.z))


def gap_signal(feature: str, d: Def, values: Mapping[dt.date, float], end: dt.date) -> Signal | None:
    """Nothing for ``GAP_DAYS`` days in a row, from a series that arrives almost every day."""
    if any(day in values for day in _days(end, GAP_DAYS)):
        return None
    before = _days(end - dt.timedelta(days=GAP_DAYS), 30)
    seen = sum(1 for day in before if day in values)
    if seen < GAP_COVERAGE * 30:
        return None
    per = _per(d.source)
    text = f"No {d.label.lower()} for the last {GAP_DAYS} {per}s: the Watch off, or a sync that stopped?"
    evidence = f"It arrived on {seen} of the 30 {per}s before."
    return Signal("gap", feature, d.family, None, text, evidence, seen / 30)


# --- the Overview's list --------------------------------------------------------------------------------


def evaluate(feature: str, d: Def, values: Mapping[dt.date, float], today: dt.date) -> Signal | None:
    """One signal for a series at most: a trend (with the last few days folded in), else a now, else a gap."""
    end = end_day(d.source, values, today)
    gap = gap_signal(feature, d, values, end)
    if gap is not None:
        return gap
    now = outside_range(values, end)
    trend = compare(values, end, TREND_DAYS, TREND_MIN)
    if trend is not None and trend.clear:
        return trend_signal(feature, d, trend, values, now)
    if now is not None and now.clear:
        return now_signal(feature, d, now)
    return None


def signals(
    series: Mapping[str, Mapping[dt.date, float]], defs: Mapping[str, Def], today: dt.date, limit: int = MAX_SIGNALS
) -> list[Signal]:
    """The strongest signal per family (sleep total and deep sleep tell one story), strongest first."""
    best: dict[str, Signal] = {}
    for feature, values in series.items():
        d = defs.get(feature)
        if d is None or d.source in EXCLUDED_SOURCES:
            continue
        s = evaluate(feature, d, values, today)
        if s is None:
            continue
        held = best.get(s.family)
        if held is None or (s.kind != "gap", s.strength) > (held.kind != "gap", held.strength):
            best[s.family] = s
    order = {"trend": 0, "now": 1, "gap": 2}
    return sorted(best.values(), key=lambda s: (order[s.kind], -s.strength, s.feature))[:limit]


# --- pins and the long view ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Week:
    start: dt.date  # Monday
    mean: float
    days: int


def weekly(values: Mapping[dt.date, float], end: dt.date, weeks: int = LONG_WEEKS) -> list[Week]:
    """Weekly means (Monday to Sunday) for the last ``weeks`` weeks, weeks with fewer than 4 days left out."""
    monday = end - dt.timedelta(days=end.weekday())
    out = []
    for k in range(weeks - 1, -1, -1):
        start = monday - dt.timedelta(weeks=k)
        vals = [values[d] for i in range(7) if (d := start + dt.timedelta(days=i)) in values and d <= end]
        if len(vals) >= WEEK_MIN:
            out.append(Week(start, statistics.fmean(vals), len(vals)))
    return out


def chart(weeks: Sequence[Week], width: int = 240, height: int = 48) -> str:
    """SVG polyline points for the weekly means (a missing week leaves a gap)."""
    if len(weeks) < 2:
        return ""
    lo = min(w.mean for w in weeks)
    hi = max(w.mean for w in weeks)
    span = (hi - lo) or 1.0
    first = weeks[0].start
    count = (weeks[-1].start - first).days // 7
    segments: list[list[str]] = [[]]
    prev: dt.date | None = None
    for w in weeks:
        if prev is not None and (w.start - prev).days > 7:
            segments.append([])
        i = (w.start - first).days // 7
        x = i * (width - 4) / max(count, 1) + 2
        y = height - 2 - (w.mean - lo) / span * (height - 4)
        segments[-1].append(f"{x:.1f},{y:.1f}")
        prev = w.start
    return "|".join(" ".join(seg) for seg in segments if len(seg) > 0)


@dataclass(frozen=True)
class Pin:
    feature: str
    label: str
    unit: str | None
    family: str
    latest: float | None
    latest_day: dt.date | None
    week: Compare | None  # the last 7 days against your usual
    trend: Compare | None  # the last 14 days against your usual
    high: Stretch | None
    low: Stretch | None
    weeks: list[Week] = field(default_factory=list)
    points: str = ""
    signal: Signal | None = None

    @property
    def direction(self) -> str | None:
        """The arrow on the pin: the two-week trend when it clears the bar, else this week's."""
        for c in (self.trend, self.week):
            if c is not None and c.direction:
                return c.direction
        return None

    @property
    def headline(self) -> str:
        """This week against your usual. The size is always shown; whether it's clear is ``clear_word``."""
        if self.week is None:
            return "Too few days for a usual yet"
        if abs(self.week.shift) < 0.05 * abs(self.week.spread):
            return f"This week {fmt(self.week.recent, self.unit)}, the same as your usual"
        return f"This week {fmt(self.week.recent, self.unit)}, {change_text(self.week, self.unit)} on your usual"

    @property
    def clear_word(self) -> str:
        if self.week is None:
            return ""
        return "a clear change" if self.week.direction else "within your usual ups and downs"

    @property
    def trend_line(self) -> str | None:
        """The last two weeks, when they clear the pin's bar: the 'am I slipping or climbing' line."""
        t = self.trend
        if t is None or t.direction is None:
            return None
        return f"Last 2 weeks {fmt(t.recent, self.unit)}, {change_text(t, self.unit)} on your usual"

    @property
    def usual_text(self) -> str:
        return f"usual {fmt(self.week.usual, self.unit)} ({self.week.n_usual} days)" if self.week else ""


def pin(feature: str, d: Def, values: Mapping[dt.date, float], today: dt.date) -> Pin:
    end = end_day(d.source, values, today)
    past = {k: v for k, v in values.items() if k <= end}
    latest_day = max(past) if past else None
    weeks = weekly(past, end)
    return Pin(
        feature=feature,
        label=d.label,
        unit=d.unit,
        family=d.family,
        latest=past[latest_day] if latest_day else None,
        latest_day=latest_day,
        week=compare(past, end, WEEK_DAYS, WEEK_MIN, Z_PIN),
        trend=compare(past, end, TREND_DAYS, TREND_MIN, Z_PIN),
        high=stretch(past, end + dt.timedelta(days=1), highest=True),
        low=stretch(past, end + dt.timedelta(days=1), highest=False),
        weeks=weeks,
        points=chart(weeks),
        signal=evaluate(feature, d, values, today),
    )


@dataclass(frozen=True)
class Row:
    """One series on the Trends page: the last 4 weeks against the usual before them."""

    feature: str
    label: str
    unit: str | None
    source: str
    month: Compare | None
    pinned: bool

    @property
    def direction(self) -> str | None:
        return self.month.direction if self.month else None


def rows(
    series: Mapping[str, Mapping[dt.date, float]], defs: Mapping[str, Def], today: dt.date, pinned: Iterable[str]
) -> list[Row]:
    """Every series you could pin, clear changes first (largest first), then the rest by name."""
    pinned = set(pinned)
    out = []
    for feature, d in defs.items():
        values = series.get(feature, {})
        if not values:
            continue
        month = compare(values, end_day(d.source, values, today), 28, 20, Z_PIN if feature in pinned else Z_BAR)
        out.append(Row(feature, d.label, d.unit, d.source, month, feature in pinned))
    return sorted(out, key=lambda r: (r.direction is None, -abs(r.month.z) if r.month else 0, r.label.lower()))


# --- DB side ------------------------------------------------------------------------------------------------


def load_defs(db: Session) -> dict[str, Def]:
    return {
        r.feature: Def(r.label, r.unit, r.source, r.kind, r.family)
        for r in db.execute(sa.select(FeatureDef)).scalars()
        if r.source not in EXCLUDED_SOURCES
    }


def load_series(db: Session, features: Iterable[str], today: dt.date) -> dict[str, dict[dt.date, float]]:
    features = list(features)
    series: dict[str, dict[dt.date, float]] = {}
    if not features:
        return series
    rows_ = db.execute(
        sa.select(DailyFeature.feature, DailyFeature.day, DailyFeature.value).where(
            DailyFeature.feature.in_(features), DailyFeature.day <= today
        )
    )
    for r in rows_:
        series.setdefault(r.feature, {})[r.day] = r.value
    return series


def load_pins(db: Session, defs: Mapping[str, Def] | None = None) -> list[str]:
    """Your pinned series; until you pin anything, sleep, exercise, steps and resting heart rate (a preset)."""
    row = db.get(Setting, PINS_KEY)
    chosen = list(row.value.get("features", [])) if row else list(DEFAULT_PINS)
    if defs is not None:
        chosen = [f for f in chosen if f in defs]
    return chosen[:MAX_PINS]


def save_pins(db: Session, features: Sequence[str]) -> None:
    value = {"features": list(dict.fromkeys(features))[:MAX_PINS]}
    row = db.get(Setting, PINS_KEY)
    if row is None:
        db.add(Setting(key=PINS_KEY, value=value))
    else:
        row.value = value
        row.updated_at = now_utc()


def toggle_pin(db: Session, feature: str) -> bool:
    """Pin or unpin a series. Returns whether it's pinned now."""
    pins = load_pins(db)
    if feature in pins:
        pins.remove(feature)
        on = False
    else:
        pins.append(feature)
        on = True
    save_pins(db, pins)
    return on


@dataclass(frozen=True)
class Noticing:
    pins: list[Pin]
    signals: list[Signal]


def load_noticing(db: Session, today: dt.date) -> Noticing:
    """The Overview's card: your pins, and the signals that clear the bar across everything else."""
    defs = load_defs(db)
    series = load_series(db, defs, today)
    pinned = load_pins(db, defs)
    pins = [pin(f, defs[f], series.get(f, {}), today) for f in pinned]
    # A pinned series already shows on its pin; the list is for what you didn't think to watch.
    rest = {f: v for f, v in series.items() if f not in pinned}
    return Noticing(pins=pins, signals=signals(rest, defs, today))


def load_trends(db: Session, today: dt.date) -> tuple[list[Pin], list[Row]]:
    defs = load_defs(db)
    series = load_series(db, defs, today)
    pinned = load_pins(db, defs)
    return [pin(f, defs[f], series.get(f, {}), today) for f in pinned], rows(series, defs, today, pinned)


# --- the push (reminders kind "signals") ------------------------------------------------------------------

NOTIFIED_KEY = "signals_notified"
PUSH_REPEAT_DAYS = 7  # one change is sent once a week at most
PUSH_PER_WEEK = 2  # and no more than this many pushes in any 7 days


def candidates(n: Noticing) -> list[tuple[str, str]]:
    """(key, sentence) for each pinned series with a clear change, then each signal; keys stay put while it holds."""
    out = []
    for p in n.pins:
        if p.direction:
            line = p.trend_line or p.headline
            out.append((f"pin:{p.feature}:{p.direction}", f"{p.label}: {line}."))
        elif p.signal is not None and p.signal.kind == "gap":
            out.append((p.signal.key, p.signal.text))
    out.extend((s.key, s.text) for s in n.signals)
    return out


def pick_push(found: Sequence[tuple[str, str]], state: Mapping, today: dt.date) -> tuple[str | None, dict]:
    """The push body for today (or None) and the state to store: what was sent, and when."""
    sent = {k: dt.date.fromisoformat(v) for k, v in state.get("keys", {}).items()}
    pushes = [dt.date.fromisoformat(d) for d in state.get("pushes", [])]
    week_ago = today - dt.timedelta(days=PUSH_REPEAT_DAYS)
    sent = {k: d for k, d in sent.items() if d > week_ago}
    pushes = [d for d in pushes if d > week_ago]
    new = [(k, text) for k, text in found if k not in sent]
    body = None
    if new and len(pushes) < PUSH_PER_WEEK:
        body = new[0][1] if len(new) == 1 else f"{new[0][1]} And {len(new) - 1} more on the Overview."
        for k, _ in new:
            sent[k] = today
        pushes.append(today)
    return body, {"keys": {k: d.isoformat() for k, d in sent.items()}, "pushes": [d.isoformat() for d in pushes]}


def push_body(db: Session, today: dt.date) -> str | None:
    """Today's "worth noticing" push, or None when nothing new clears the bar (the caller sends and commits)."""
    row = db.get(Setting, NOTIFIED_KEY)
    body, state = pick_push(candidates(load_noticing(db, today)), row.value if row else {}, today)
    if row is None:
        db.add(Setting(key=NOTIFIED_KEY, value=state))
    else:
        row.value = state
        row.updated_at = now_utc()
    return body
