"""At-a-glance forms of a finding or a day's value: an icon, a direction and a strength, read from across the room.

The sentence stays the source of truth (R10, R13); these only add what the eye can pick up first. An arrow is a
direction, never a judgement: whether "up" is good is for the person to decide.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .models import FeatureDef, Insight
from .trackers import tag_slug

# Feature prefix → icon name (see web/templates/_icons.html). First match wins.
ICONS = (
    ("goodday.", "smile"),
    ("rating.", "smile"),
    ("sleep.", "moon"),
    ("hl.step_count", "steps"),
    ("hl.heart_rate_variability", "wave"),
    ("stress.", "gauge"),
    ("energy.", "battery"),
    ("mood.", "smile"),
    ("tracker.day_tags.", "tag"),
    ("tracker.", "pencil"),
    ("workout.", "steps"),
)
FAMILY_ICONS = {"activity": "steps", "vital": "heart", "sleep": "moon", "mood": "smile"}
STRENGTH_DOTS = {"weak": 1, "moderate": 2, "strong": 3}
TAG_COLOURS = 8  # day tags take colours tc-0 … tc-7 in list order, the same on every page (style.css)
DAY_TAG_PREFIX = "tracker.day_tags.tag."
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")  # Python weekday() order


def icon_for(feature: str, family: str | None = None) -> str:
    for prefix, name in ICONS:
        if feature.startswith(prefix):
            return name
    return FAMILY_ICONS.get(family or "", "dot")


@dataclass(frozen=True)
class Side:
    label: str
    icon: str
    arrow: str | None  # "up" | "down" | None
    colour: int | None = None  # a day tag's colour index, shown as its chip


@dataclass(frozen=True)
class Card:
    a: Side
    b: Side | None
    link: str  # "together", "opposite", "lately", or the weekday high and low
    next_day: bool
    dots: int
    days_later: int = 0  # a link spread over days, peaking this many days later


@dataclass(frozen=True)
class Range:
    """A finding's likely range drawn on a 0–200 axis: the span, the estimate and where "no effect" sits."""

    lo_x: float
    hi_x: float
    est_x: float
    zero_x: float
    text: str  # the same range in words, for the caption and screen readers
    clear: bool  # the whole range is on one side of "no effect"


AXIS = (6.0, 194.0)


def _x(v: float, lo: float, hi: float) -> float:
    return round(AXIS[0] + (min(max(v, lo), hi) - lo) / (hi - lo) * (AXIS[1] - AXIS[0]), 1)


def _signed(v: float, fmt: str) -> str:
    return ("+" if v > 0 else "−" if v < 0 else "") + format(abs(v), fmt)


def likely_range(i: Insight) -> Range | None:
    """The 95% likely range of an association's strength (−1…+1) or of a change (in %), if the run stored one."""
    details = i.details or {}
    if i.kind == "association" and details.get("ci"):
        lo, hi = details["ci"]
        est, scale, words = i.effect, (-1.0, 1.0), "{} to {} (0 is no link)"
        text = words.format(_signed(lo, ".2f"), _signed(hi, ".2f"))
    elif i.kind == "change" and details.get("pct_ci"):
        lo, hi = details["pct_ci"]
        est = details.get("pct", 0.0)
        bound = max(abs(lo), abs(hi), abs(est), 10.0) * 1.15
        scale = (-bound, bound)
        text = f"{_signed(lo, '.0f')}% to {_signed(hi, '.0f')}% (0 is no change)"
    else:
        return None
    return Range(_x(lo, *scale), _x(hi, *scale), _x(est, *scale), _x(0.0, *scale), text, lo > 0 or hi < 0)


# Insights stored before the engine recorded labels name only these two drivers.
DRIVER_WORDS = {"sleep.total_h": "sleep", "hl.step_count": "steps"}
VERDICTS = {
    "holds": "still holds allowing for {}",
    "weaker": "weaker once {} is allowed for",
    "explained": "largely accounted for by {}",
}


@dataclass(frozen=True)
class Adjusted:
    verdict: str  # holds | weaker | explained
    text: str  # "still holds allowing for sleep and steps"
    range: Range


def adjusted(i: Insight) -> Adjusted | None:
    """The adjusted re-check of a relationship, if the run made one: the verdict in words and the adjusted range."""
    adj = (i.details or {}).get("adjusted")
    if not adj or adj.get("verdict") not in VERDICTS:
        return None
    labels = adj.get("labels") or [DRIVER_WORDS.get(d, d) for d in adj["for"]]
    words = [w[0].lower() + w[1:] if w[:1].isupper() and not w[1:2].isupper() else w for w in labels]
    drivers = ", ".join(words[:-1]) + f" and {words[-1]}" if len(words) > 1 else words[0]
    text = VERDICTS[adj["verdict"]].format(drivers)
    if adj["verdict"] == "weaker" and len(words) > 1:
        text = text.replace(" is allowed", " are allowed")
    lo, hi = adj["ci"]
    span = Range(
        _x(lo, -1.0, 1.0),
        _x(hi, -1.0, 1.0),
        _x(adj["rho"], -1.0, 1.0),
        _x(0.0, -1.0, 1.0),
        f"{_signed(lo, '.2f')} to {_signed(hi, '.2f')} (0 is no link)",
        lo > 0 or hi < 0,
    )
    return Adjusted(adj["verdict"], text, span)


@dataclass(frozen=True)
class LagBar:
    lag: int
    x: float
    y: float
    height: float
    up: bool
    peak: bool


def lag_bars(i: Insight) -> list[LagBar]:
    """A spread-over-days link's curve as bars on a 0–200 × 0–60 canvas, zero line at 30."""
    curve = (i.details or {}).get("curve")
    if not curve:
        return []
    top = max(max(abs(c) for c in curve), 1e-9)
    width = 200 / len(curve)
    peak = int((i.details or {}).get("peak", 0))
    out = []
    for k, c in enumerate(curve):
        h = round(abs(c) / top * 26, 1)
        out.append(
            LagBar(k, round(k * width + width * 0.2, 1), round(30 - h if c >= 0 else 30, 1), h, c >= 0, k == peak)
        )
    return out


def tag_colours(tags: Sequence[str]) -> dict[str, tuple[str, int]]:
    """Day tag slug → (its text, its colour index): by position in the list, so a tag keeps its colour."""
    return {tag_slug(t): (t, k % TAG_COLOURS) for k, t in enumerate(tags)}


def _side(feature: str, defs: Mapping[str, FeatureDef], arrow: str | None, tags: Mapping[str, tuple[str, int]]) -> Side:
    if feature.startswith(DAY_TAG_PREFIX) and (tag := tags.get(feature.removeprefix(DAY_TAG_PREFIX))):
        return Side(tag[0], "tag", arrow, tag[1])
    d = defs.get(feature)
    return Side(d.label if d else feature, icon_for(feature, d.family if d else None), arrow)


def card(i: Insight, defs: Mapping[str, FeatureDef], tags: Mapping[str, tuple[str, int]] | None = None) -> Card:
    """An association reads as "A ▲ B ▲" (or ▼ when they move apart); a change as "A ▲ lately"."""
    tags = tags or {}
    dots = STRENGTH_DOTS.get(i.strength, 1)
    if i.kind == "association" and i.feature_b:
        same = i.effect >= 0
        spread = i.method == "distributed_lag"
        return Card(
            _side(i.feature_a, defs, "up", tags),
            _side(i.feature_b, defs, "up" if same else "down", tags),
            "together" if same else "opposite",
            bool(i.lag) and not spread,
            dots,
            int(i.lag or 0) if spread else 0,
        )
    details = i.details or {}
    if i.kind == "change":
        up = details.get("pct", i.effect) >= 0
        return Card(_side(i.feature_a, defs, "up" if up else "down", tags), None, "lately", False, dots)
    if "high" in details and "low" in details:
        link = f"highest {WEEKDAYS[int(details['high'])]}, lowest {WEEKDAYS[int(details['low'])]}"
    else:
        link = "by weekday"
    return Card(_side(i.feature_a, defs, None, tags), None, link, False, dots)
