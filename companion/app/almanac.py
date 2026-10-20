"""The almanac: day length, moon phase and public holidays, computed here (M3 part 2).

No request and no package: these are arithmetic on the date (R5). Day length
needs only a latitude (the coarse ``WEATHER_LATITUDE``, never the longitude);
holidays need a country, taken from ``HOLIDAYS_COUNTRY`` or guessed from ``TZ``.
Everything is pure and tested against published dates.

Like the weather, almanac features are outside data: they can go with what
follows them, never the other way round (analysis-engine.md, "Outside data").
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable
from dataclasses import dataclass

# --- day length ----------------------------------------------------------------

# The sun's centre is this far below the horizon at sunrise and sunset (refraction plus the sun's radius).
SUNRISE_ALTITUDE_DEG = -0.833


def solar_declination(day: dt.date) -> float:
    """Radians, from NOAA's Fourier series (good to about 0.04°)."""
    g = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    return (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.00148 * math.sin(3 * g)
    )


def day_length(day: dt.date, latitude: float) -> float:
    """Hours from sunrise to sunset; 0 or 24 in polar night or midnight sun."""
    phi, delta = math.radians(latitude), solar_declination(day)
    cos_h = (math.sin(math.radians(SUNRISE_ALTITUDE_DEG)) - math.sin(phi) * math.sin(delta)) / (
        math.cos(phi) * math.cos(delta)
    )
    return 2 * math.degrees(math.acos(max(-1.0, min(1.0, cos_h)))) / 15


# --- moon -------------------------------------------------------------------------

SYNODIC_MONTH = 29.530588853  # days, new moon to new moon (mean)
NEW_MOON_EPOCH = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.UTC)


def moon_lit(day: dt.date) -> float:
    """Share of the moon lit at noon UTC, 0-100. Mean motion: off by up to about half a day, fine for a daily
    value."""
    noon = dt.datetime.combine(day, dt.time(12), tzinfo=dt.UTC)
    age = ((noon - NEW_MOON_EPOCH).total_seconds() / 86400) % SYNODIC_MONTH
    return 50 * (1 - math.cos(2 * math.pi * age / SYNODIC_MONTH))


# --- holidays ---------------------------------------------------------------------


def easter(year: int) -> dt.date:
    """Western Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, rest = divmod(h + m - 7 * n + 114, 31)
    return dt.date(year, month, rest + 1)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """The n-th given weekday (Monday = 0) of a month; n = -1 is the last."""
    if n > 0:
        first = dt.date(year, month, 1)
        return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


Rule = Callable[[int], dt.date]
MON, THU = 0, 3


def fixed(month: int, day: int) -> Rule:
    return lambda year: dt.date(year, month, day)


def nth(month: int, weekday: int, n: int) -> Rule:
    return lambda year: nth_weekday(year, month, weekday, n)


def after_easter(days: int) -> Rule:
    return lambda year: easter(year) + dt.timedelta(days=days)


def monday_before(month: int, day: int) -> Rule:
    """The last Monday strictly before a date (Canada's Victoria Day: the Monday before May 25)."""
    return lambda year: (
        dt.date(year, month, day) - dt.timedelta(days=(dt.date(year, month, day).weekday() - MON) % 7 or 7)
    )


@dataclass(frozen=True)
class Holiday:
    name: str
    rule: Rule
    moves: bool = False  # a fixed date that falls on a weekend gives a weekday off (the country's rule)


# National public holidays only (regional ones differ too much to guess). Big ones get a run-up window.
COUNTRIES: dict[str, tuple[Holiday, ...]] = {
    "US": (
        Holiday("New Year's Day", fixed(1, 1), moves=True),
        Holiday("Martin Luther King Jr. Day", nth(1, MON, 3)),
        Holiday("Presidents' Day", nth(2, MON, 3)),
        Holiday("Memorial Day", nth(5, MON, -1)),
        Holiday("Juneteenth", fixed(6, 19), moves=True),
        Holiday("Independence Day", fixed(7, 4), moves=True),
        Holiday("Labor Day", nth(9, MON, 1)),
        Holiday("Columbus Day", nth(10, MON, 2)),
        Holiday("Veterans Day", fixed(11, 11), moves=True),
        Holiday("Thanksgiving", nth(11, THU, 4)),
        Holiday("Christmas", fixed(12, 25), moves=True),
    ),
    "CA": (
        Holiday("New Year's Day", fixed(1, 1), moves=True),
        Holiday("Good Friday", after_easter(-2)),
        Holiday("Victoria Day", monday_before(5, 25)),
        Holiday("Canada Day", fixed(7, 1), moves=True),
        Holiday("Labour Day", nth(9, MON, 1)),
        Holiday("Thanksgiving", nth(10, MON, 2)),
        Holiday("Christmas", fixed(12, 25), moves=True),
        Holiday("Boxing Day", fixed(12, 26), moves=True),
    ),
    "GB": (
        Holiday("New Year's Day", fixed(1, 1), moves=True),
        Holiday("Good Friday", after_easter(-2)),
        Holiday("Easter Monday", after_easter(1)),
        Holiday("Early May bank holiday", nth(5, MON, 1)),
        Holiday("Spring bank holiday", nth(5, MON, -1)),
        Holiday("Summer bank holiday", nth(8, MON, -1)),
        Holiday("Christmas", fixed(12, 25), moves=True),
        Holiday("Boxing Day", fixed(12, 26), moves=True),
    ),
    "DE": (
        Holiday("Neujahr", fixed(1, 1)),
        Holiday("Karfreitag", after_easter(-2)),
        Holiday("Ostermontag", after_easter(1)),
        Holiday("Tag der Arbeit", fixed(5, 1)),
        Holiday("Christi Himmelfahrt", after_easter(39)),
        Holiday("Pfingstmontag", after_easter(50)),
        Holiday("Tag der Deutschen Einheit", fixed(10, 3)),
        Holiday("Weihnachten", fixed(12, 25)),
        Holiday("Zweiter Weihnachtsfeiertag", fixed(12, 26)),
    ),
}
SUPPORTED = tuple(COUNTRIES)
# Holidays with a run-up worth looking at: the weeks before them are usually different.
RUNUP_HOLIDAYS = frozenset({"Christmas", "Weihnachten", "Thanksgiving"})
RUNUP_DAYS = 14


def holidays(year: int, country: str) -> dict[dt.date, str]:
    """Public holidays of a year, with the weekday off when a fixed date falls on a weekend (US: the nearest
    weekday; CA and GB: the next free weekday)."""
    out: dict[dt.date, str] = {}
    moving: list[tuple[dt.date, str]] = []
    for h in COUNTRIES[country]:
        day = h.rule(year)
        out[day] = h.name
        if h.moves and day.weekday() >= 5:
            moving.append((day, h.name))
    for day, name in sorted(moving):
        if country == "US":
            off = day - dt.timedelta(days=1) if day.weekday() == 5 else day + dt.timedelta(days=1)
        else:
            off = day + dt.timedelta(days=1)
            while off.weekday() >= 5 or off in out:
                off += dt.timedelta(days=1)
        out.setdefault(off, f"{name} (observed)")
    return out


def runups(years: range, country: str) -> dict[dt.date, str]:
    """The big holidays by date (the actual day, not the observed one)."""
    return {h.rule(year): h.name for year in years for h in COUNTRIES[country] if h.name in RUNUP_HOLIDAYS}


# Time zone -> country, for the default. Zones not listed get no holidays until HOLIDAYS_COUNTRY is set.
_ZONE_PREFIXES = {
    "US": ("US/", "America/Indiana/", "America/Kentucky/", "America/North_Dakota/"),
    "CA": ("Canada/",),
}
_ZONES = {
    "US": {
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "America/Phoenix",
        "America/Anchorage",
        "America/Juneau",
        "America/Sitka",
        "America/Yakutat",
        "America/Nome",
        "America/Metlakatla",
        "America/Adak",
        "America/Boise",
        "America/Detroit",
        "America/Menominee",
        "Pacific/Honolulu",
    },
    "CA": {
        "America/Toronto",
        "America/Vancouver",
        "America/Edmonton",
        "America/Winnipeg",
        "America/Halifax",
        "America/St_Johns",
        "America/Regina",
        "America/Moncton",
        "America/Glace_Bay",
        "America/Goose_Bay",
        "America/Whitehorse",
        "America/Dawson",
        "America/Dawson_Creek",
        "America/Fort_Nelson",
        "America/Creston",
        "America/Iqaluit",
        "America/Rankin_Inlet",
        "America/Resolute",
        "America/Cambridge_Bay",
        "America/Inuvik",
        "America/Swift_Current",
        "America/Atikokan",
        "America/Blanc-Sablon",
    },
    "GB": {"Europe/London"},
    "DE": {"Europe/Berlin", "Europe/Busingen"},
}


def country_for_zone(zone: str) -> str | None:
    for country, zones in _ZONES.items():
        if zone in zones or zone.startswith(_ZONE_PREFIXES.get(country, ("\0",))):
            return country
    return None


# --- daily features -----------------------------------------------------------------


@dataclass(frozen=True)
class AlmanacDef:
    feature: str
    label: str
    unit: str | None
    kind: str
    analyse: bool


DEFS = (
    # Day length moves smoothly with the season, so removing the slow trend (as every test does) leaves nothing
    # of it: shown for context, not tested. A year of data could change that (next-steps §4.5).
    AlmanacDef("almanac.day_length", "Day length (sunrise to sunset)", "h", "continuous", False),
    AlmanacDef("almanac.moon", "Moon (share lit)", "%", "continuous", True),
    AlmanacDef("almanac.holiday", "Public holiday", None, "count", True),
    AlmanacDef("almanac.holiday_runup", "Two weeks before a big holiday", None, "count", True),
)


def almanac_features(
    first: dt.date, last: dt.date, latitude: float | None, country: str | None
) -> dict[str, dict[dt.date, float]]:
    """One value per day from ``first`` to ``last``. No latitude: no day length; no country: no holidays."""
    if last < first:
        return {}
    days = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]
    out: dict[str, dict[dt.date, float]] = {"almanac.moon": {d: round(moon_lit(d), 1) for d in days}}
    if latitude is not None:
        out["almanac.day_length"] = {d: round(day_length(d, latitude), 3) for d in days}
    if country is not None:
        years = range(first.year, last.year + 2)
        off = {d for y in years for d in holidays(y, country)}
        big = runups(years, country)
        before = {h - dt.timedelta(days=k) for h in big for k in range(1, RUNUP_DAYS + 1)}
        out["almanac.holiday"] = {d: float(d in off) for d in days}
        out["almanac.holiday_runup"] = {d: float(d in before) for d in days}
    return out
