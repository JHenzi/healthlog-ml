"""The day rating: the Companion's own measure of how a day was, asked every evening and again the next morning.

Two built-in 1–10 ratings, always there (they can't be removed, archived or renamed):

- **Evening** (``day_rating``): "How was today?", logged on the day itself.
- **Next morning** (``day_rating_lookback``): "Looking back, how was yesterday?", logged the next day and stored
  on the day it is about.

Both are measurements of the day, not a theory of what makes a good one (R17), so the engine tests them against
everything like any other series. The two and their difference (``rating.shift``, next morning minus evening)
are one family: linked by definition, never tested against each other. They are the anchor the learned good-day
weights will be fitted to (M7). Missing is not zero (R7): a day without a rating has none. Pure, apart from the
two DB helpers.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .models import Tracker
from .trackers import DEFAULT_SCALE, Obs

EVENING_KEY = "day_rating"
LOOKBACK_KEY = "day_rating_lookback"
KEYS = (EVENING_KEY, LOOKBACK_KEY)
NAMES = {EVENING_KEY: "How was today?", LOOKBACK_KEY: "Looking back, how was yesterday?"}
SOURCE = FAMILY = "rating"
EVENING, LOOKBACK, SHIFT = "rating.evening", "rating.lookback", "rating.shift"
DEFS = (
    (EVENING, "Day rating (evening)"),
    (LOOKBACK, "Day rating (next morning)"),
    (SHIFT, "Day rating: change by the next morning"),
)


def _latest(obs: Iterable[Obs]) -> dict[dt.date, float]:
    """One value a day: the latest entry (the pages keep one, the API may log more)."""
    out: dict[dt.date, tuple[dt.datetime, float]] = {}
    for o in obs:
        if o.tag is None and o.value_num is not None and (o.day not in out or o.observed_at >= out[o.day][0]):
            out[o.day] = (o.observed_at, o.value_num)
    return {day: v for day, (_, v) in out.items()}


def daily(obs_by_key: Mapping[str, Iterable[Obs]], last_day: dt.date) -> dict[str, dict[dt.date, float]]:
    """The three daily features from the two ratings' entries, complete days only (``<= last_day``)."""
    evening = {d: v for d, v in _latest(obs_by_key.get(EVENING_KEY, ())).items() if d <= last_day}
    lookback = {d: v for d, v in _latest(obs_by_key.get(LOOKBACK_KEY, ())).items() if d <= last_day}
    return {
        EVENING: evening,
        LOOKBACK: lookback,
        SHIFT: {d: lookback[d] - evening[d] for d in evening.keys() & lookback.keys()},
    }


def is_built_in(key: str) -> bool:
    return key in KEYS


# --- the two trackers -----------------------------------------------------------


def _new(key: str) -> Tracker:
    return Tracker(
        key=key,
        name=NAMES[key],
        type="scale",
        scale_min=DEFAULT_SCALE[0],
        scale_max=DEFAULT_SCALE[1],
        options=[],
        tags=[],
        in_review=True,
        pinned=False,
        always_logged=False,
        archived=False,
    )


def trackers(db: Session) -> dict[str, Tracker]:
    """Both ratings, for showing them: the stored row, or an unsaved stand-in until the first entry."""
    rows = {t.key: t for t in db.execute(sa.select(Tracker).where(Tracker.key.in_(KEYS))).scalars()}
    return {key: rows.get(key) or _new(key) for key in KEYS}


def ensure(db: Session, key: str) -> Tracker:
    """The rating's tracker, created on its first entry."""
    tracker = db.execute(sa.select(Tracker).where(Tracker.key == key)).scalar_one_or_none()
    if tracker is None:
        tracker = _new(key)
        db.add(tracker)
        db.flush()
    return tracker
