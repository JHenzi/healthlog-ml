"""The day rating: one value a day per rating, the change between them, complete days only (R7, R17)."""

from __future__ import annotations

import datetime as dt

from app import dayrating
from app.dayrating import EVENING, EVENING_KEY, LOOKBACK, LOOKBACK_KEY, SHIFT
from app.trackers import Obs

D1, D2, D3 = dt.date(2026, 10, 18), dt.date(2026, 10, 19), dt.date(2026, 10, 20)


def _at(day: dt.date, hour: int) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour), dt.UTC)


def test_the_latest_entry_of_a_day_counts_and_the_change_needs_both():
    obs = {
        EVENING_KEY: [
            Obs(_at(D1, 21), D1, 4.0, None),
            Obs(_at(D1, 22), D1, 6.0, None),
            Obs(_at(D2, 21), D2, 8.0, None),
        ],
        LOOKBACK_KEY: [Obs(_at(D1, 12), D1, 7.0, None)],
    }
    out = dayrating.daily(obs, last_day=D2)
    assert out[EVENING] == {D1: 6.0, D2: 8.0}
    assert out[LOOKBACK] == {D1: 7.0}
    assert out[SHIFT] == {D1: 1.0}  # no look back on D2 yet: no change, never 0


def test_only_complete_days_and_no_ratings_means_no_values():
    obs = {EVENING_KEY: [Obs(_at(D3, 21), D3, 5.0, None)]}
    assert dayrating.daily(obs, last_day=D2) == {EVENING: {}, LOOKBACK: {}, SHIFT: {}}
    assert dayrating.daily({}, last_day=D2) == {EVENING: {}, LOOKBACK: {}, SHIFT: {}}
