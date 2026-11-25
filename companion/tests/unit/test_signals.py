"""Signals, pins and the push: wording (up/down only), gaps, stretches, weekly charts, families and the push cap."""

from __future__ import annotations

import datetime as dt

from app import signals
from app.signals import (
    Compare,
    Def,
    candidates,
    change_text,
    chart,
    evaluate,
    fmt,
    gap_signal,
    normal_scores,
    pick_push,
    pin,
    stretch,
    weekly,
)

TODAY = dt.date(2026, 11, 25)  # a Wednesday
YESTERDAY = TODAY - dt.timedelta(days=1)


def _flat(days: int, value: float, end: dt.date = YESTERDAY, wobble: float = 0.3) -> dict[dt.date, float]:
    """A steady series with a small repeating wobble (so it has a spread), ``days`` long, ending on ``end``."""
    return {end - dt.timedelta(days=k): value + wobble * ((k % 3) - 1) for k in range(days)}


def _compare(recent: float, usual: float, z: float = 5.0) -> Compare:
    return Compare(recent, usual, 1.0, 7, 60, z, YESTERDAY - dt.timedelta(days=6), YESTERDAY)


def test_numbers_read_in_your_units():
    assert fmt(6.5, "h") == "6 h 30 min"
    assert fmt(0.75, "h") == "45 min"
    assert fmt(4419.2, "count") == "4,419"
    assert fmt(15.04, "min") == "15 min"
    assert fmt(48.5, "bpm") == "48.5 bpm"
    assert fmt(330, "min after 18:00") == "23:30"


def test_change_words_are_up_and_down_never_good_or_bad():
    assert change_text(_compare(5.0, 6.0), "h") == "down 1 h 00 min"
    assert change_text(_compare(3000, 4000), "count") == "down 25%"
    assert change_text(_compare(0.5, 0.1), None) == "up 0.4"  # a percent of a small number reads oddly
    assert change_text(_compare(400, 340), "min after 18:00") == "1 h 00 min later"
    for word in ("better", "worse", "good", "bad"):
        assert word not in change_text(_compare(5.0, 6.0), "h")


def test_a_change_must_clear_the_bar_and_the_floor():
    assert _compare(5.0, 6.0).direction == "down"
    assert _compare(5.0, 6.0, z=1.0).direction is None  # not enough evidence
    tiny = Compare(5.9, 6.0, 1.0, 14, 60, 9.0, YESTERDAY, YESTERDAY)
    assert tiny.direction is None  # a tenth of a usual spread is not a change, however sure


def test_normal_scores_keep_order_and_share_ties():
    days = [YESTERDAY - dt.timedelta(days=k) for k in range(4)]
    scores = normal_scores(dict(zip(days, [1.0, 50.0, 50.0, 10_000.0], strict=True)))
    assert scores[days[0]] < scores[days[1]] == scores[days[2]] < scores[days[3]]
    assert abs(scores[days[3]]) < 2  # a huge value is just the top rank


def test_a_gap_is_named_only_for_a_series_that_usually_arrives():
    d = Def("Sleep (total)", "h", "sleep", family="sleep")
    usual = {k: v for k, v in _flat(40, 6.5).items() if k < YESTERDAY - dt.timedelta(days=2)}
    s = gap_signal("sleep.total_h", d, usual, YESTERDAY)
    assert s is not None and s.kind == "gap" and "last 3 nights" in s.text and "30 of the 30" in s.evidence
    sparse = {k: v for i, (k, v) in enumerate(sorted(usual.items())) if i % 2}
    assert gap_signal("sleep.total_h", d, sparse, YESTERDAY) is None  # it never arrived daily
    assert gap_signal("sleep.total_h", d, _flat(40, 6.5), YESTERDAY) is None  # nothing missing


def test_a_two_week_drop_is_a_trend_with_the_stretch_it_came_from():
    d = Def("Sleep (total)", "h", "healthlog", family="sleep")
    values = _flat(90, 7.0)
    for k in range(14):
        values[YESTERDAY - dt.timedelta(days=k)] = 5.0 + 0.3 * ((k % 3) - 1)
    s = evaluate("x", d, values, TODAY)
    assert s is not None and s.kind == "trend" and s.direction == "down"
    assert "down" in s.text and "Your highest 2 weeks on record" in s.text
    assert "14 of 14 days" in s.evidence  # the days behind it (R13)


def test_a_steady_series_says_nothing():
    assert evaluate("x", Def("Steps", "count", "healthlog"), _flat(90, 4000, wobble=500), TODAY) is None


def test_one_signal_per_family_and_weather_left_out():
    drop = _flat(90, 7.0)
    for k in range(14):
        drop[YESTERDAY - dt.timedelta(days=k)] = 4.0 + 0.3 * ((k % 3) - 1)
    defs = {
        "a": Def("A", "h", "healthlog", family="sleep"),
        "b": Def("B", "h", "healthlog", family="sleep"),
        "w": Def("Pressure", "hPa", "weather", family="weather"),
    }
    out = signals.signals({"a": drop, "b": dict(drop), "w": dict(drop)}, defs, TODAY)
    assert [s.family for s in out] == ["sleep"]


def test_sleep_counts_this_morning_once_it_is_in():
    assert signals.end_day("sleep", {TODAY: 6.0}, TODAY) == TODAY
    assert signals.end_day("sleep", {}, TODAY) == YESTERDAY
    assert signals.end_day("healthlog", {TODAY: 1.0}, TODAY) == YESTERDAY  # today isn't over


def test_stretches_and_weeks():
    values = _flat(60, 5.0)
    for k in range(20, 34):
        values[YESTERDAY - dt.timedelta(days=k)] = 9.0
    high = stretch(values, TODAY, highest=True)
    assert high is not None and high.mean == 9.0 and high.last == YESTERDAY - dt.timedelta(days=20)
    weeks = weekly(values, YESTERDAY)
    assert all(w.start.weekday() == 0 and w.days >= signals.WEEK_MIN for w in weeks)
    points = chart(weeks)
    assert points and "|" not in points  # no missing week, one line


def test_a_pin_always_says_how_far_and_whether_it_is_clear():
    values = _flat(90, 7.0, end=TODAY)
    for k in range(7):
        values[TODAY - dt.timedelta(days=k)] = 5.5 + 0.3 * ((k % 3) - 1)
    p = pin("sleep.total_h", Def("Sleep (total)", "h", "sleep", family="sleep"), values, TODAY)
    assert p.direction == "down" and p.headline.startswith("This week 5 h") and ", down " in p.headline
    assert p.clear_word == "a clear change" and "usual 7 h 00 min" in p.usual_text
    steady = pin("x", Def("Steps", "count", "healthlog"), _flat(90, 4000, wobble=600), TODAY)
    assert steady.direction is None and steady.clear_word == "within your usual ups and downs"
    empty = pin("x", Def("New", None, "tracker"), {}, TODAY)
    assert empty.headline == "Too few days for a usual yet" and empty.points == ""


def test_the_push_sends_a_change_once_and_twice_a_week_at_most():
    found = [("pin:sleep:down", "Sleep: down."), ("steps:trend:down", "Steps: down.")]
    body, state = pick_push(found, {}, TODAY)
    assert body == "Sleep: down. And 1 more on the Overview."
    again, state = pick_push(found, state, TODAY + dt.timedelta(days=1))
    assert again is None  # nothing new
    third, state = pick_push([("a:trend:up", "A: up.")], state, TODAY + dt.timedelta(days=2))
    assert third == "A: up."
    capped, state = pick_push([("b:trend:up", "B: up.")], state, TODAY + dt.timedelta(days=3))
    assert capped is None  # two pushes in 7 days already
    later, _ = pick_push(found, state, TODAY + dt.timedelta(days=8))
    assert later is not None  # a week on, a change still holding may be sent again


def test_push_candidates_lead_with_pins():
    values = _flat(90, 7.0, end=TODAY)
    for k in range(7):
        values[TODAY - dt.timedelta(days=k)] = 5.5
    p = pin("sleep.total_h", Def("Sleep (total)", "h", "sleep", family="sleep"), values, TODAY)
    found = candidates(signals.Noticing(pins=[p], signals=[]))
    assert found[0][0] == "pin:sleep.total_h:down" and found[0][1].startswith("Sleep (total): ")
