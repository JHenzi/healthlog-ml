"""The Companion's day: local time zone plus a day boundary (R14).

A "day" runs from ``boundary`` local time to ``boundary`` the next calendar
day, so a 01:30 bedtime still belongs to the evening before. Day bounds are
built from local wall-clock times and converted, never by adding 24 h, so DST
days come out as 23 h and 25 h.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo


def _wall_offset(boundary: dt.time) -> dt.timedelta:
    return dt.timedelta(hours=boundary.hour, minutes=boundary.minute)


def local_day(ts: dt.datetime, zone: ZoneInfo, boundary: dt.time) -> dt.date:
    """The Companion day an aware timestamp belongs to."""
    if ts.tzinfo is None:
        raise ValueError("naive datetime; the Companion only handles aware timestamps")
    return (ts.astimezone(zone).replace(tzinfo=None) - _wall_offset(boundary)).date()


def day_bounds(day: dt.date, zone: ZoneInfo, boundary: dt.time) -> tuple[dt.datetime, dt.datetime]:
    """``[start, end)`` of a Companion day as aware datetimes in ``zone``."""
    start = dt.datetime.combine(day, boundary, tzinfo=zone)
    end = dt.datetime.combine(day + dt.timedelta(days=1), boundary, tzinfo=zone)
    return start, end


def current_day(now: dt.datetime, zone: ZoneInfo, boundary: dt.time) -> dt.date:
    return local_day(now, zone, boundary)


def sql_day_expr(column: str) -> str:
    """SQL for the Companion day of a ``timestamptz`` column, mirroring :func:`local_day`.

    Expects bind parameters ``:tz`` (zone name) and ``:boundary`` (an interval
    such as ``'4 hours'``). Wall-clock arithmetic on the local timestamp, so it
    agrees with the Python rule across DST changes.
    """
    return f"(({column} AT TIME ZONE :tz) - CAST(:boundary AS interval))::date"


def boundary_interval(boundary: dt.time) -> str:
    return f"{boundary.hour} hours {boundary.minute} minutes"
