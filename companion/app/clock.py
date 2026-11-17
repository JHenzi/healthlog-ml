"""Clock-time series: values that are a time of day, stored as minutes after a fixed origin.

A clock time has no natural zero, so a percent change means nothing ("bedtime 15% later" depends on where the
scale starts). Such series are compared by their shift in minutes instead, and shown as a clock time (7:42).
The origin is part of the unit: minutes after midnight for times in the day, minutes after 18:00 for bedtimes, so
01:30 sorts after 23:30 instead of before it.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

AFTER_MIDNIGHT = "min after midnight"
AFTER_EVENING = "min after 18:00"

# unit -> origin in minutes after midnight
CLOCK_UNITS = {AFTER_MIDNIGHT: 0, AFTER_EVENING: 18 * 60}
EVENING = dt.time(18, 0)


def is_clock(unit: str | None) -> bool:
    return unit in CLOCK_UNITS


def clock_text(minutes: float, unit: str) -> str:
    """'7:42' for a value on a clock scale (24-hour, wraps past midnight)."""
    total = round(minutes + CLOCK_UNITS[unit]) % (24 * 60)
    h, m = divmod(total, 60)
    return f"{h}:{m:02d}"


def shift_text(minutes: float) -> str:
    """'35 min later' / '1 h 10 min earlier' for a shift on a clock scale."""
    m = round(abs(minutes))
    h, rest = divmod(m, 60)
    size = f"{h} h {rest:02d} min" if h else f"{m} min"
    return f"{size} {'later' if minutes > 0 else 'earlier' if minutes < 0 else 'apart'}"


def wall_minutes(ts: dt.datetime, zone: ZoneInfo, origin_day: dt.date, origin: dt.time) -> float:
    """Wall-clock minutes from ``origin`` on ``origin_day`` to ``ts`` in ``zone``.

    Measured on the local wall clock, not elapsed time, so a DST night doesn't move every wake time by an hour.
    """
    if ts.tzinfo is None:
        raise ValueError("naive datetime; the Companion only handles aware timestamps")
    local = ts.astimezone(zone).replace(tzinfo=None)
    return (local - dt.datetime.combine(origin_day, origin)).total_seconds() / 60  # noqa: DTZ001 - wall clock on purpose
