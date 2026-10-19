"""At-a-glance forms of a finding or a day's value: an icon, a direction and a strength, read from across the room.

The sentence stays the source of truth (R10, R13); these only add what the eye can pick up first. An arrow is a
direction, never a judgement: whether "up" is good is for the person to decide.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .models import FeatureDef, Insight

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


@dataclass(frozen=True)
class Card:
    a: Side
    b: Side | None
    link: str  # "together", "opposite", "lately", or the weekday high and low
    next_day: bool
    dots: int


def _side(feature: str, defs: Mapping[str, FeatureDef], arrow: str | None) -> Side:
    d = defs.get(feature)
    return Side(d.label if d else feature, icon_for(feature, d.family if d else None), arrow)


def card(i: Insight, defs: Mapping[str, FeatureDef]) -> Card:
    """An association reads as "A ▲ B ▲" (or ▼ when they move apart); a change as "A ▲ lately"."""
    dots = STRENGTH_DOTS.get(i.strength, 1)
    if i.kind == "association" and i.feature_b:
        same = i.effect >= 0
        return Card(
            _side(i.feature_a, defs, "up"),
            _side(i.feature_b, defs, "up" if same else "down"),
            "together" if same else "opposite",
            bool(i.lag),
            dots,
        )
    details = i.details or {}
    if i.kind == "change":
        up = details.get("pct", i.effect) >= 0
        return Card(_side(i.feature_a, defs, "up" if up else "down"), None, "lately", False, dots)
    if "high" in details and "low" in details:
        link = f"highest {WEEKDAYS[int(details['high'])]}, lowest {WEEKDAYS[int(details['low'])]}"
    else:
        link = "by weekday"
    return Card(_side(i.feature_a, defs, None), None, link, False, dots)
