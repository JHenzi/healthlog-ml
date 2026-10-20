"""Tracker types: validation per type and daily features with the reviewed-day rule (R7)."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app.trackers import (
    Obs,
    TrackerInputError,
    TrackerSpec,
    check_time,
    daily_features,
    minutes_of_day,
    parse_tag,
    parse_tags,
    parse_value,
    slugify,
    tag_slug,
    validate_definition,
)

NY = ZoneInfo("America/New_York")
FOUR = dt.time(4, 0)
D1, D2, D3 = dt.date(2026, 10, 14), dt.date(2026, 10, 15), dt.date(2026, 10, 16)

COFFEE = TrackerSpec("coffee", "Coffee", "count", "cups")
PRODUCTIVITY = TrackerSpec("productivity", "Productivity", "scale", scale_min=1, scale_max=5)
ALCOHOL = TrackerSpec("alcohol", "Alcohol", "check")
LUNCH = TrackerSpec("lunch", "Lunch", "choice", options=("home", "takeout", "skipped"))
ANGER = TrackerSpec("anger", "Anger", "moment")
SOCIAL = TrackerSpec("social_media", "First social media", "time")


@pytest.mark.parametrize(
    ("spec", "raw", "expected"),
    [
        (COFFEE, None, (1.0, None)),
        (COFFEE, "3", (3.0, None)),
        (PRODUCTIVITY, 4, (4.0, None)),
        (ALCOHOL, None, (1.0, None)),
        (ALCOHOL, "no", (0.0, None)),
        (LUNCH, "Takeout", (None, "takeout")),
        (ANGER, None, (None, None)),
        (ANGER, "2", (2.0, None)),
        (SOCIAL, None, (None, None)),
        (TrackerSpec("caffeine", "Caffeine", "quantity", "mg"), "95.5", (95.5, None)),
    ],
)
def test_valid_values(spec, raw, expected):
    assert parse_value(spec, raw) == expected


@pytest.mark.parametrize(
    ("spec", "raw"),
    [
        (COFFEE, "-1"),
        (COFFEE, "1.5"),
        (COFFEE, True),
        (PRODUCTIVITY, 6),
        (PRODUCTIVITY, None),
        (ALCOHOL, "maybe"),
        (LUNCH, "pizza"),
        (ANGER, 4),
        (TrackerSpec("spend", "Spend", "quantity", "$"), "-3"),
        (TrackerSpec("x", "X", "duration"), "abc"),
    ],
)
def test_invalid_values_are_rejected_not_guessed(spec, raw):
    with pytest.raises(TrackerInputError):
        parse_value(spec, raw)


def test_definitions_are_validated():
    with pytest.raises(TrackerInputError):
        validate_definition(TrackerSpec("Coffee!", "Coffee", "count"))
    with pytest.raises(TrackerInputError):
        validate_definition(TrackerSpec("p", "P", "scale", scale_min=5, scale_max=1))
    with pytest.raises(TrackerInputError):
        validate_definition(TrackerSpec("c", "C", "choice", options=("only",)))
    validate_definition(LUNCH)


def test_slugify():
    assert slugify("First social media!") == "first_social_media"
    assert slugify("3 coffees") == "t_3_coffees"
    assert slugify("!!!") == "tracker"


def test_future_times_are_rejected():
    now = dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.UTC)
    check_time(now + dt.timedelta(minutes=4), now)
    with pytest.raises(TrackerInputError):
        check_time(now + dt.timedelta(minutes=10), now)


def test_minutes_of_day_rolls_past_the_boundary():
    assert minutes_of_day(dt.datetime(2026, 10, 16, 7, 10, tzinfo=NY), NY, FOUR) == 430
    assert minutes_of_day(dt.datetime(2026, 10, 17, 0, 30, tzinfo=NY), NY, FOUR) == 1470  # later than 23:30


def _obs(day: dt.date, hour: int, value: float | None = None, text: str | None = None) -> Obs:
    return Obs(dt.datetime.combine(day, dt.time(hour), tzinfo=NY), day, value, text)


def test_count_is_zero_only_on_reviewed_days():
    f = daily_features(COFFEE, [_obs(D1, 8, 1), _obs(D1, 14, 2)], {D2}, D3, NY, FOUR)
    assert f.values["tracker.coffee.total"] == {D1: 3.0, D2: 0.0}  # D3 not reviewed: unknown, not 0
    assert f.values["tracker.coffee.first_time"] == {D1: 480.0}
    assert f.values["tracker.coffee.last_time"] == {D1: 840.0}


def test_always_logged_tracker_fills_every_day_since_its_first_entry():
    spec = TrackerSpec("coffee", "Coffee", "count", always_logged=True)
    f = daily_features(spec, [_obs(D1, 8, 1)], set(), D3, NY, FOUR)
    assert f.values["tracker.coffee.total"] == {D1: 1.0, D2: 0.0, D3: 0.0}


def test_zero_fill_never_reaches_beyond_the_last_complete_day():
    spec = TrackerSpec("coffee", "Coffee", "count", always_logged=True)
    f = daily_features(spec, [_obs(D1, 8, 1)], {D3}, D2, NY, FOUR)
    assert D3 not in f.values["tracker.coffee.total"]


def test_scale_is_never_zero_filled():
    f = daily_features(PRODUCTIVITY, [_obs(D1, 20, 4), _obs(D1, 21, 2)], {D2}, D3, NY, FOUR)
    assert f.values["tracker.productivity.mean"] == {D1: 3.0}
    assert f.values["tracker.productivity.max"] == {D1: 4.0}


def test_choice_and_moment_features():
    lunch = daily_features(LUNCH, [_obs(D1, 12, text="takeout")], {D2}, D3, NY, FOUR)
    assert lunch.values["tracker.lunch.takeout"] == {D1: 1.0, D2: 0.0}
    assert lunch.values["tracker.lunch.home"] == {D1: 0.0, D2: 0.0}
    anger = daily_features(ANGER, [_obs(D1, 9, 2), _obs(D1, 17)], {D2}, D3, NY, FOUR)
    assert anger.values["tracker.anger.count"] == {D1: 2.0, D2: 0.0}
    assert anger.values["tracker.anger.max_intensity"] == {D1: 2.0}


def test_time_tracker_gives_first_time():
    f = daily_features(SOCIAL, [_obs(D1, 7), _obs(D1, 21)], set(), D3, NY, FOUR)
    assert f.values == {"tracker.social_media.first_time": {D1: 420.0}}


WORK = TrackerSpec("work_day", "Work day", "scale", scale_min=1, scale_max=10, tags=("Meeting heavy", "in-fighting"))
DAY_TAGS = TrackerSpec("day_tags", "Day tags", "tags", tags=("travel", "sick"))


def _tag(day: dt.date, tag: str) -> Obs:
    return Obs(dt.datetime.combine(day, dt.time(18), tzinfo=NY), day, None, None, tag)


def test_tags_parse_and_slug():
    assert parse_tags("in-fighting, Meeting  heavy,, meeting heavy ,") == ["in-fighting", "Meeting heavy"]
    assert tag_slug("Meeting heavy") == "meeting_heavy" and tag_slug("in-fighting") == "in_fighting"
    assert parse_tag(WORK, "meeting HEAVY") == "meeting_heavy"
    with pytest.raises(TrackerInputError):
        parse_tag(WORK, "travel")  # only the tracker's own tags


def test_tag_definitions_are_validated():
    validate_definition(DAY_TAGS)
    for bad in (
        TrackerSpec("t", "T", "check", tags=("Late", "late")),  # same slug twice
        TrackerSpec("t", "T", "check", tags=("!!",)),
        TrackerSpec("t", "T", "check", tags=("x" * 41,)),
    ):
        with pytest.raises(TrackerInputError):
            validate_definition(bad)
    with pytest.raises(TrackerInputError):
        parse_value(DAY_TAGS, "1")  # nothing to log but tags


def test_tag_is_one_when_picked_zero_when_used_or_reviewed_unknown_otherwise():
    obs = [_obs(D1, 9, 7), _tag(D1, "meeting_heavy"), _obs(D2, 9, 4)]
    f = daily_features(WORK, obs, {D3}, D3, NY, FOUR)
    assert f.values["tracker.work_day.tag.meeting_heavy"] == {D1: 1.0, D2: 0.0, D3: 0.0}
    assert f.values["tracker.work_day.tag.in_fighting"] == {D1: 0.0, D2: 0.0, D3: 0.0}
    assert f.values["tracker.work_day.mean"] == {D1: 7.0, D2: 4.0}  # tag entries never enter the value
    assert f.labels["tracker.work_day.tag.meeting_heavy"] == ("Work day: Meeting heavy", None, "count")


def test_tags_only_tracker_has_only_tag_features():
    f = daily_features(DAY_TAGS, [_tag(D1, "travel")], set(), D3, NY, FOUR)
    assert f.values == {"tracker.day_tags.tag.travel": {D1: 1.0}, "tracker.day_tags.tag.sick": {D1: 0.0}}


def test_a_removed_tag_keeps_its_history_up_to_its_last_use():
    obs = [_tag(D1, "late_night"), _obs(D1, 9, 7), _obs(D2, 9, 4), _obs(D3, 9, 5)]
    f = daily_features(WORK, obs, {D2, D3}, D3, NY, FOUR)  # "late_night" is no longer on WORK's list
    assert f.values["tracker.work_day.tag.late_night"] == {D1: 1.0}  # not 0 after it stopped being offered
    assert f.labels["tracker.work_day.tag.late_night"] == ("Work day: late night (removed)", None, "count")
    obs = [_tag(D1, "late_night"), _obs(D2, 9, 4), _tag(D3, "late_night")]
    f = daily_features(WORK, obs, set(), D3, NY, FOUR)
    assert f.values["tracker.work_day.tag.late_night"] == {D1: 1.0, D2: 0.0, D3: 1.0}


def test_an_archived_tracker_keeps_its_history_but_is_not_zero_filled_after_its_last_entry():
    archived = TrackerSpec("coffee", "Coffee", "count", always_logged=True, archived=True)
    f = daily_features(archived, [_obs(D1, 8, 1)], {D2, D3}, D3, NY, FOUR)
    assert f.values["tracker.coffee.total"] == {D1: 1.0}
    reviewed_only = TrackerSpec("coffee", "Coffee", "count", archived=True)
    f = daily_features(reviewed_only, [_obs(D2, 8, 2)], {D1, D3}, D3, NY, FOUR)
    assert f.values["tracker.coffee.total"] == {D1: 0.0, D2: 2.0}
    assert daily_features(reviewed_only, [], {D1}, D3, NY, FOUR).values == {}
