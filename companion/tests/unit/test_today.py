"""Today page logic: source policy (R16), baselines, sentences with n (R13), association wording (R10)."""

from __future__ import annotations

import datetime as dt
import re

from app.today import SPECS, Baseline, baseline, build_sentences, fmt_hours, pick_source, sentence
from app.upstream import SourceDay

D = dt.date(2026, 10, 16)

FORBIDDEN = re.compile(r"\b(cause[sd]?|because|leads? to|diagnos\w*)\b", re.IGNORECASE)


def test_merged_stream_wins_over_device_sources():
    rows = [SourceDay(D, "Watch", 9000, 900), SourceDay(D, "", 8000, 10), SourceDay(D, "iPhone", 3000, 300)]
    assert pick_source(rows) == {D: 8000}


def test_without_merged_stream_most_samples_wins_and_sources_are_never_summed():
    rows = [SourceDay(D, "Watch", 50, 400), SourceDay(D, "iPhone", 70, 20)]
    assert pick_source(rows) == {D: 50}


def test_tie_on_samples_prefers_the_larger_value():
    assert pick_source([SourceDay(D, "a", 6.0, 1), SourceDay(D, "b", 7.5, 1)]) == {D: 7.5}


def test_baseline_needs_minimum_history_and_excludes_the_day():
    values = {D - dt.timedelta(days=i): float(i) for i in range(1, 7)}
    assert baseline(values, D) is None  # 6 days < 7
    values[D - dt.timedelta(days=7)] = 7.0
    values[D] = 1000.0  # the day itself never enters its own baseline
    b = baseline(values, D)
    assert b == Baseline(mean=4.0, n=7)


def test_baseline_window_is_30_days():
    values = {D - dt.timedelta(days=i): 1.0 for i in range(1, 40)}
    assert baseline(values, D).n == 30


def test_sleep_sentence_below_average():
    s = sentence(SPECS["sleep"], 6 + 40 / 60, Baseline(7.25, 28))
    assert s == "You slept 6 h 40 min last night, 35 min below your 30-day average (7 h 15 min, 28 nights)."


def test_steps_sentence_more_than_average():
    s = sentence(SPECS["steps"], 8412, Baseline(7209, 30))
    assert s == "You walked 8,412 steps yesterday, 1,203 more than your 30-day average (7,209 steps, 30 days)."


def test_about_average_within_five_percent():
    assert "about your 30-day average" in sentence(SPECS["resting_hr"], 54, Baseline(55, 20))


def test_missing_value_and_missing_baseline():
    assert sentence(SPECS["hrv"], None, None) == "No hrv data for yesterday."
    assert sentence(SPECS["stress"], 31, None).endswith("Not enough history for a 30-day baseline yet.")


def test_fmt_hours():
    assert fmt_hours(0.5) == "30 min"
    assert fmt_hours(7.999) == "8 h 00 min"


def test_build_sentences_uses_last_night_for_sleep_and_yesterday_for_the_rest():
    today = dt.date(2026, 10, 17)
    yesterday = today - dt.timedelta(days=1)
    history = {today - dt.timedelta(days=i): 7.0 for i in range(1, 15)}
    series = {"sleep": {**history, today: 6.0}, "steps": {yesterday: 5000.0}}
    lines = build_sentences(series, {yesterday: (12, 88)}, today)
    assert lines[0].startswith("You slept 6 h 00 min last night, 1 h 00 min below")
    assert any(line.startswith("You walked 5,000 steps yesterday.") for line in lines)
    assert lines[-1] == "Your energy reserve ranged from 12 to 88 yesterday."


def test_every_comparison_sentence_carries_n_and_no_causal_wording():
    for spec in SPECS.values():
        for value in (10.0, 100.0, 1000.0):
            s = sentence(spec, value, Baseline(100.0, 21))
            assert not FORBIDDEN.search(s), s
            if "average" in s:
                assert "21 " in s, s


def test_tiles_show_direction_only_when_notably_different():
    from app.today import mood_tile, tile

    usual = Baseline(7200.0, 30)
    up = tile("steps", 8412.0, usual)
    assert (up.value, up.direction, up.change) == ("8,412", "up", "1,212 more than usual")
    assert "30 days" in up.sentence  # the full sentence keeps its n (R13)
    assert tile("steps", 7300.0, usual).direction == "flat"
    assert tile("resting_hr", 52.0, Baseline(56.0, 27)).change == "4 bpm below usual"
    assert tile("sleep", 7 + 59.9 / 60, None).value == "8:00"
    assert tile("hrv", None, None).direction is None
    assert mood_tile([(0.3, ("calm",)), (0.2, ("calm", "content"))]).value == "calm"
