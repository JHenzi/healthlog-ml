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
        return Card(
            _side(i.feature_a, defs, "up", tags),
            _side(i.feature_b, defs, "up" if same else "down", tags),
            "together" if same else "opposite",
            bool(i.lag),
            dots,
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
