"""Outside data (M3): the collector file's strict schema, daily weather features on Companion days, the Today
note. Synthetic values only (R4)."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app.outside import (
    HEADER,
    OutsideDataError,
    WeatherHour,
    parse_weather_csv,
    weather_features,
    weather_note,
)

NY = ZoneInfo("America/New_York")
FOUR = dt.time(4, 0)


def _csv(rows: list[list[str]]) -> str:
    return "\n".join([",".join(HEADER), *(",".join(r) for r in rows)]) + "\n"


def _row(stamp: str, temp: str = "12.5", pressure: str = "1013.2") -> list[str]:
    values = {"temperature_c": temp, "pressure_hpa": pressure}
    return [stamp, *(values.get(c, "") for c in HEADER[1:])]


def test_a_valid_file_parses_with_missing_values_as_none():
    hours = parse_weather_csv(_csv([_row("2026-10-01T00:00Z"), _row("2026-10-01T01:00Z", temp="")]))
    assert hours[0].time == dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    assert hours[0].values["temperature_c"] == 12.5 and hours[1].values["temperature_c"] is None
    assert hours[0].values["pm25"] is None


@pytest.mark.parametrize(
    "text",
    [
        "time_utc,temperature_c\n2026-10-01T00:00Z,12\n",  # wrong columns
        _csv([_row("2026-10-01T00:00Z"), _row("2026-10-01T00:00Z")]),  # repeated hour
        _csv([_row("2026-10-01T00:30Z")]),  # not on the hour
        _csv([_row("2026-10-01 00:00")]),  # not UTC ISO
        _csv([_row("2026-10-01T00:00Z", temp="hot")]),
        _csv([_row("2026-10-01T00:00Z", temp="nan")]),
        _csv([_row("2026-10-01T00:00Z", pressure="2000")]),  # out of range
        _csv([_row("2026-10-01T00:00Z")[:-1]]),  # short line
    ],
)
def test_any_bad_line_rejects_the_whole_file(text):
    with pytest.raises(OutsideDataError):
        parse_weather_csv(text)


def _hours(start: dt.datetime, n: int, **columns) -> list[WeatherHour]:
    """n hourly rows from start; each column is a function of the hour index."""
    return [WeatherHour(start + dt.timedelta(hours=i), {c: f(i) for c, f in columns.items()}) for i in range(n)]


def test_daily_features_follow_the_companion_day_and_need_most_hours():
    # 2026-10-10 04:00 New York (EDT) = 08:00 UTC; three full days of hours from there.
    start = dt.datetime(2026, 10, 10, 8, tzinfo=dt.UTC)
    hours = _hours(
        start,
        72,
        temperature_c=lambda i: 10.0 + (i % 24) / 2,
        pressure_hpa=lambda i: 1010.0 + (i // 24) * 4,
        precipitation_mm=lambda i: 0.5 if i < 4 else 0.0,
    )
    now = start + dt.timedelta(hours=80)
    f = weather_features(hours, NY, FOUR, now)
    d1, d2, d3 = dt.date(2026, 10, 10), dt.date(2026, 10, 11), dt.date(2026, 10, 12)
    assert f["weather.temp_mean"] == {d1: 15.75, d2: 15.75, d3: 15.75}
    assert f["weather.temp_range"][d1] == 11.5
    assert f["weather.precipitation"] == {d1: 2.0, d2: 0.0, d3: 0.0}
    assert f["weather.pressure_change"] == {d2: 4.0, d3: 4.0}  # the first day has nothing to compare with
    assert "weather.pm25_mean" not in f  # no air-quality hours at all
    partial = weather_features(hours[:30], NY, FOUR, now)
    assert set(partial["weather.temp_mean"]) == {d1}  # 6 hours of day two are too few


def test_a_day_still_running_has_no_weather_features():
    start = dt.datetime(2026, 10, 10, 8, tzinfo=dt.UTC)
    hours = _hours(start, 24, temperature_c=lambda i: 10.0)
    assert weather_features(hours, NY, FOUR, start + dt.timedelta(hours=23)) == {}


def test_dst_days_count_their_own_hours():
    # The clocks go back at 02:00 on Nov 1, so with a 04:00 boundary the Companion day Oct 31 is 25 h:
    # 04:00 EDT (08:00 UTC) to 04:00 EST (09:00 UTC the next day).
    start = dt.datetime(2026, 10, 31, 8, tzinfo=dt.UTC)
    hours = _hours(start, 25, precipitation_mm=lambda i: 1.0)
    f = weather_features(hours, NY, FOUR, start + dt.timedelta(hours=30))
    assert f["weather.precipitation"] == {dt.date(2026, 10, 31): 25.0}


def test_weather_note_names_big_pressure_and_temperature_changes_only():
    start = dt.datetime(2026, 10, 10, 0, tzinfo=dt.UTC)
    falling = _hours(start, 49, pressure_hpa=lambda i: 1020.0 - 0.4 * i, temperature_c=lambda i: 15.0)
    now = start + dt.timedelta(hours=48, minutes=20)
    assert weather_note(falling, now) == "Air pressure fell 10 hPa over the last 24 hours."
    steady = _hours(start, 49, pressure_hpa=lambda i: 1015.0, temperature_c=lambda i: 15.0)
    assert weather_note(steady, now) is None
    colder = _hours(start, 49, pressure_hpa=lambda i: 1015.0, temperature_c=lambda i: 20.0 if i <= 24 else 10.0)
    assert weather_note(colder, now) == "The last 24 hours were 10 °C colder than the day before."
    assert weather_note(falling, now + dt.timedelta(days=3)) is None  # stale: the collector stopped
