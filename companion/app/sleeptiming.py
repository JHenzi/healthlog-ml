"""Sleep timing: when you slept, not just how long (reflection-and-prediction.md §4d). Pure, no DB.

From the sleep sessions HealthLog stores, per wake date:

- ``sleep.bedtime``: start of the main sleep, minutes after 18:00 the evening before (01:30 sorts after 23:30);
- ``sleep.wake_time``: end of the main sleep, minutes after midnight;
- ``sleep.midpoint``: halfway through it, minutes after 18:00;
- ``sleep.midpoint_vs_usual``: the midpoint against your median over the nights before (past nights only);
- ``sleep.timing_spread``: how much the midpoint varied over the last week (standard deviation, minutes).

The main sleep is the night, not a nap: sessions from one source with short gaps between them are one block (a
Watch splits a night where you were up for a while), and the block with the most sleep that ends on a date is that
date's night, if it holds enough sleep to be one. One source per night, the one with the most sleep, as for the
sleep totals (R16). A night without a record has no value (R7): a missing night is not an early or late one.
Wall-clock minutes, so DST nights don't shift every time by an hour (R14).
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from .clock import AFTER_EVENING, AFTER_MIDNIGHT, EVENING, wall_minutes
from .upstream import SleepSession

# What counts as one night (measurement, not a theory of good sleep): sessions this close together are one block,
# and a block needs this much sleep to be the night rather than a nap.
MAIN_SLEEP_GAP = dt.timedelta(minutes=90)
MIN_NIGHT_H = 3.0
# "Your usual": the median midpoint of the nights in the 28 days before, once there are 14 of them.
USUAL_DAYS = 28
USUAL_MIN_NIGHTS = 14
# Spread: the standard deviation of the midpoint over the 7 nights ending on a date, once 5 of them are recorded.
SPREAD_DAYS = 7
SPREAD_MIN_NIGHTS = 5

FAMILY = "sleep_timing"
DEFS = (
    ("sleep.bedtime", "Bedtime", AFTER_EVENING),
    ("sleep.wake_time", "Wake time", AFTER_MIDNIGHT),
    ("sleep.midpoint", "Sleep midpoint", AFTER_EVENING),
    ("sleep.midpoint_vs_usual", "Sleep midpoint vs your usual", "min"),
    ("sleep.timing_spread", "Sleep timing spread (7 nights)", "min"),
)


@dataclass(frozen=True)
class Night:
    wake_date: dt.date
    start: dt.datetime
    end: dt.datetime
    total_h: float
    source: str


def _blocks(sessions: list[SleepSession]) -> list[tuple[dt.datetime, dt.datetime, float]]:
    """One source's sessions, ordered by start, merged where the gap between them is short."""
    out: list[list] = []
    for s in sorted(sessions, key=lambda s: s.start):
        if out and s.start - out[-1][1] <= MAIN_SLEEP_GAP:
            out[-1][1] = max(out[-1][1], s.end)
            out[-1][2] += s.total_h
        else:
            out.append([s.start, s.end, s.total_h])
    return [(a, b, h) for a, b, h in out]


def nights(sessions: Iterable[SleepSession], zone: ZoneInfo) -> dict[dt.date, Night]:
    """The main sleep per wake date (local calendar date of its end)."""
    by_source: dict[str, list[SleepSession]] = {}
    totals: dict[tuple[dt.date, str], float] = {}
    for s in sessions:
        by_source.setdefault(s.source, []).append(s)
        day = s.end.astimezone(zone).date()
        totals[day, s.source] = totals.get((day, s.source), 0.0) + s.total_h
    # One source per wake date: the one with the most sleep that date, as the sleep totals pick it.
    chosen: dict[dt.date, str] = {}
    for (day, source), total in sorted(totals.items()):
        if day not in chosen or total > totals[day, chosen[day]]:
            chosen[day] = source
    out: dict[dt.date, Night] = {}
    for source, items in by_source.items():
        for start, end, total in _blocks(items):
            day = end.astimezone(zone).date()
            if chosen.get(day) != source or total < MIN_NIGHT_H:
                continue
            if day not in out or total > out[day].total_h:
                out[day] = Night(day, start, end, total, source)
    return out


def timing_features(sessions: Iterable[SleepSession], zone: ZoneInfo) -> dict[str, dict[dt.date, float]]:
    found = nights(sessions, zone)
    bedtime: dict[dt.date, float] = {}
    wake: dict[dt.date, float] = {}
    midpoint: dict[dt.date, float] = {}
    for day, n in found.items():
        evening = day - dt.timedelta(days=1)
        bedtime[day] = wall_minutes(n.start, zone, evening, EVENING)
        wake[day] = wall_minutes(n.end, zone, day, dt.time(0, 0))
        midpoint[day] = wall_minutes(n.start + (n.end - n.start) / 2, zone, evening, EVENING)

    vs_usual: dict[dt.date, float] = {}
    spread: dict[dt.date, float] = {}
    for day, mid in midpoint.items():
        before = [midpoint[d] for d in _days_before(day, USUAL_DAYS) if d in midpoint]
        if len(before) >= USUAL_MIN_NIGHTS:
            vs_usual[day] = mid - statistics.median(before)
        week = [midpoint[d] for d in [day, *_days_before(day, SPREAD_DAYS - 1)] if d in midpoint]
        if len(week) >= SPREAD_MIN_NIGHTS:
            spread[day] = statistics.stdev(week)
    return {
        "sleep.bedtime": bedtime,
        "sleep.wake_time": wake,
        "sleep.midpoint": midpoint,
        "sleep.midpoint_vs_usual": vs_usual,
        "sleep.timing_spread": spread,
    }


def _days_before(day: dt.date, n: int) -> list[dt.date]:
    return [day - dt.timedelta(days=i) for i in range(1, n + 1)]
