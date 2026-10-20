"""The almanac: day length, moon and holidays against published dates; features per day (R7: every date has a
value, so nothing here is ever missing)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.almanac import (
    RUNUP_DAYS,
    almanac_features,
    country_for_zone,
    day_length,
    easter,
    holidays,
    moon_lit,
    runups,
)

D = dt.date


@pytest.mark.parametrize(
    ("year", "day"), [(2019, D(2019, 4, 21)), (2024, D(2024, 3, 31)), (2025, D(2025, 4, 20)), (2026, D(2026, 4, 5))]
)
def test_easter(year, day):
    assert easter(year) == day


def test_us_holidays_move_off_weekends_to_the_nearest_weekday():
    us = holidays(2026, "US")
    assert us[D(2026, 1, 19)] == "Martin Luther King Jr. Day"
    assert us[D(2026, 5, 25)] == "Memorial Day"
    assert us[D(2026, 11, 26)] == "Thanksgiving"
    assert us[D(2026, 7, 4)] == "Independence Day"  # a Saturday
    assert us[D(2026, 7, 3)] == "Independence Day (observed)"
    assert us[D(2026, 12, 25)] == "Christmas"
    assert holidays(2027, "US")[D(2027, 12, 24)] == "Christmas (observed)"  # Christmas 2027 is a Saturday
    assert holidays(2028, "US")[D(2027, 12, 31)] == "New Year's Day (observed)"


def test_gb_ca_de_holidays():
    gb = holidays(2027, "GB")  # Christmas on a Saturday, Boxing Day on a Sunday
    assert gb[D(2027, 12, 27)] == "Christmas (observed)" and gb[D(2027, 12, 28)] == "Boxing Day (observed)"
    gb26 = holidays(2026, "GB")
    assert gb26[D(2026, 4, 3)] == "Good Friday" and gb26[D(2026, 4, 6)] == "Easter Monday"
    assert gb26[D(2026, 5, 4)] == "Early May bank holiday" and gb26[D(2026, 8, 31)] == "Summer bank holiday"
    assert holidays(2026, "CA")[D(2026, 5, 18)] == "Victoria Day"  # May 25 is a Monday: the one before
    assert holidays(2027, "CA")[D(2027, 5, 24)] == "Victoria Day"
    assert holidays(2026, "CA")[D(2026, 10, 12)] == "Thanksgiving"
    de = holidays(2026, "DE")
    assert de[D(2026, 5, 14)] == "Christi Himmelfahrt" and de[D(2026, 5, 25)] == "Pfingstmontag"
    assert D(2026, 10, 4) not in de  # Germany doesn't move holidays off a weekend


def test_runups_are_the_big_holidays_only():
    assert runups(range(2026, 2027), "US") == {D(2026, 11, 26): "Thanksgiving", D(2026, 12, 25): "Christmas"}
    assert runups(range(2026, 2027), "DE") == {D(2026, 12, 25): "Weihnachten"}


def test_day_length():
    # New York (40.7° N): about 9 h 15 min at the winter solstice, 15 h 05 min at the summer one.
    assert day_length(D(2026, 12, 21), 40.7) == pytest.approx(9 + 15 / 60, abs=5 / 60)
    assert day_length(D(2026, 6, 21), 40.7) == pytest.approx(15 + 5 / 60, abs=5 / 60)
    assert day_length(D(2026, 3, 20), 0.0) == pytest.approx(12.1, abs=0.05)
    assert day_length(D(2026, 12, 21), 70.0) == 0.0
    assert day_length(D(2026, 6, 21), 70.0) == 24.0
    assert day_length(D(2026, 12, 21), -40.7) == pytest.approx(day_length(D(2026, 6, 21), 40.7), abs=0.1)


def test_moon():
    assert moon_lit(D(2024, 1, 25)) > 97  # full moon 2024-01-25 17:54 UTC
    assert moon_lit(D(2024, 1, 11)) < 3  # new moon 2024-01-11 11:57 UTC
    assert moon_lit(D(2025, 1, 13)) > 95
    assert 30 < moon_lit(D(2024, 1, 18)) < 70  # first quarter 2024-01-18


def test_country_from_time_zone():
    assert country_for_zone("America/New_York") == "US"
    assert country_for_zone("America/Indiana/Indianapolis") == "US"
    assert country_for_zone("America/Toronto") == "CA"
    assert country_for_zone("Europe/London") == "GB"
    assert country_for_zone("Europe/Berlin") == "DE"
    assert country_for_zone("Asia/Tokyo") is None
    assert country_for_zone("America/Mexico_City") is None


def test_features_cover_every_day_and_only_what_is_set():
    first, last = D(2026, 12, 1), D(2026, 12, 31)
    moon_only = almanac_features(first, last, None, None)
    assert set(moon_only) == {"almanac.moon"} and len(moon_only["almanac.moon"]) == 31
    full = almanac_features(first, last, 40.7, "US")
    assert set(full) == {"almanac.moon", "almanac.day_length", "almanac.holiday", "almanac.holiday_runup"}
    assert full["almanac.holiday"][D(2026, 12, 25)] == 1.0 and full["almanac.holiday"][D(2026, 12, 24)] == 0.0
    runup = [d for d, v in full["almanac.holiday_runup"].items() if v]
    assert runup == [D(2026, 12, 25) - dt.timedelta(days=k) for k in range(RUNUP_DAYS, 0, -1)]
    assert almanac_features(last, first, 40.7, "US") == {}
