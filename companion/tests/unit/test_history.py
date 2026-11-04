"""Earlier discoveries (roadmap B17): which findings dropped out and which came back, pure."""

from __future__ import annotations

import datetime as dt

from app.analysis.history import KEEP_DAYS, diff, expired, finding_key


def test_the_same_finding_keeps_its_key_whatever_its_numbers():
    a = finding_key("association", "day", "sleep.total_h", "hl.step_count", 1, "spearman")
    assert a == finding_key("association", "day", "sleep.total_h", "hl.step_count", 1, "spearman")
    assert a != finding_key("association", "day", "sleep.total_h", "hl.step_count", 0, "spearman")
    assert a != finding_key("association", "day", "sleep.total_h", "hl.step_count", None, "distributed_lag")
    assert finding_key("weekday", "day", "x", None, None, "kruskal") == "weekday|day|x|||kruskal"


def test_diff_finds_what_dropped_and_what_came_back():
    d = diff(previous={"a", "b"}, current={"b", "c"}, earlier={"c", "z"})
    assert d.dropped == {"a"} and d.back == {"c"}


def test_an_earlier_discovery_is_kept_for_a_while():
    today = dt.date(2026, 11, 4)
    assert not expired(today - dt.timedelta(days=KEEP_DAYS), today)
    assert expired(today - dt.timedelta(days=KEEP_DAYS + 1), today)
