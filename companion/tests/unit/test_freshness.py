"""The Overview notice: is the Companion behind HealthLog, or is Health Auto Export silent?"""

from __future__ import annotations

import datetime as dt

from app.freshness import SILENT_AFTER, classify

NOW = dt.datetime(2026, 10, 10, 15, 0, tzinfo=dt.UTC)


def test_caught_up_and_recent_shows_nothing():
    f = classify((42, NOW - dt.timedelta(hours=2)), seen=42, now=NOW)
    assert f.state == "current" and not f.show


def test_unprocessed_payloads_mean_behind_and_offer_a_refresh():
    assert classify((43, NOW - dt.timedelta(minutes=5)), seen=42, now=NOW).state == "behind"


def test_behind_wins_over_silent_because_a_refresh_helps():
    assert classify((43, NOW - 2 * SILENT_AFTER), seen=42, now=NOW).state == "behind"


def test_a_quiet_phone_is_silent_and_a_refresh_cannot_help():
    f = classify((42, NOW - SILENT_AFTER), seen=42, now=NOW)
    assert f.state == "silent" and f.show and f.last_received == NOW - SILENT_AFTER
    assert classify((42, NOW - SILENT_AFTER + dt.timedelta(minutes=1)), seen=42, now=NOW).state == "current"


def test_nothing_ever_received_is_silent():
    f = classify(None, seen=0, now=NOW)
    assert f.state == "silent" and f.last_received is None
