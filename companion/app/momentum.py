"""Momentum: encouraging notes about workouts and activity for the Overview (roadmap B18).

The owner asked for encouragement around trends and streaks: when you're moving more, say so. The notes are
facts about your own series, compared only with your own history; no goals are assumed (R17), and every note
names the days behind it (R13). A drop isn't a Momentum note: it already shows on the "Compared with your usual"
tiles, and this card is for what is going well. A missed day is mentioned once, gently, as a restart.

- **Workout run**: days in a row with a workout, through today (or through yesterday while today has none yet).
- **Workout week**: workout days in the last 7, against the 7 before, or the most in any 7 days so far.
- **Above your usual**: a key activity series above its own 30-day median several complete days in a row.
- **Week on week**: a key activity series' 7-day average up clearly on the 7 days before.

Days before the first workout on record are unknown, not zero (R7); after it, a day without a workout is a day
without one, because Health Auto Export sends every workout. Pure, apart from ``load_momentum``.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Mapping

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .models import DailyFeature

WORKOUT = "workout.minutes"
# Activity series worth cheering on: label and the word after a day's value. Ordered by priority.
ACTIVITY = {
    "hl.apple_exercise_time": ("exercise", "min"),
    "hl.step_count": ("steps", "steps"),
    "hl.active_energy": ("active energy", "kcal"),
    "hl.apple_stand_hour": ("stand hours", "hours"),
}
RUN_MIN_DAYS = 2  # workout days in a row worth a note
ABOVE_MIN_DAYS = 3  # complete days in a row above your usual
USUAL_DAYS = 30  # the window the usual (median) is taken over
USUAL_MIN_DAYS = 14  # fewer days than this and there's no usual yet
WEEK = 7
WEEK_MIN_DAYS = 5  # days with data in each week for a week-on-week comparison
RISE = 1.15  # a week counts as up when its average is at least 15% above the week before
RESTART_WITHIN = 6  # mention a missed day only this long after the last workout
MAX_NOTES = 4


def fmt(value: float, unit: str | None) -> str:
    """Whole numbers read better in encouragement: 29 min, 4,330 steps."""
    number = f"{round(value):,}"
    return f"{number} {unit}" if unit else number


def _on(day: dt.date, today: dt.date) -> str:
    if day == today:
        return "today"
    return "yesterday" if day == today - dt.timedelta(days=1) else day.strftime("%A")


def workout_notes(minutes: Mapping[dt.date, float], today: dt.date) -> list[str]:
    """The workout run, the week's count and, after a gap, a nudge to restart."""
    done = {d for d, v in minutes.items() if v > 0 and d <= today}
    if not done:
        return []
    first = min(done)
    notes: list[str] = []
    end = today if today in done else today - dt.timedelta(days=1)
    run = 0
    while end - dt.timedelta(days=run) in done:
        run += 1
    if run >= RUN_MIN_DAYS:
        notes.append(f"{run} workout days in a row, through {_on(end, today)}. Keep it going.")
    else:
        last = max(done)
        gap = (today - last).days
        if 2 <= gap <= RESTART_WITHIN:
            notes.append(f"Your last workout was {_on(last, today)}. One today starts a new run.")

    def count(last_day: dt.date) -> int:
        return sum(1 for k in range(WEEK) if last_day - dt.timedelta(days=k) in done)

    this_week = count(today)
    if this_week >= 2:
        recorded = (today - first).days + 1
        windows = [count(first + dt.timedelta(days=k)) for k in range(WEEK - 1, recorded - 1)]
        before = count(today - dt.timedelta(days=WEEK))
        since = first.strftime("%b %-d")
        if recorded >= 2 * WEEK and windows and this_week > max(windows):
            notes.append(f"{this_week} workout days in the last 7, your most in any 7 days since {since}.")
        elif recorded >= 2 * WEEK and this_week > before:
            notes.append(f"{this_week} workout days in the last 7, up from {before} the 7 days before.")
        elif recorded < 2 * WEEK:
            notes.append(f"{this_week} workout days since you started recording workouts on {since}.")
    return notes


def above_usual(label: str, unit: str | None, values: Mapping[dt.date, float], yesterday: dt.date) -> str | None:
    """A run of complete days, ending yesterday, above the median of the 30 days before the run."""
    run = 0
    while True:
        day = yesterday - dt.timedelta(days=run)
        if day not in values:
            break
        window = [values[d] for k in range(1, USUAL_DAYS + 1) if (d := day - dt.timedelta(days=k)) in values]
        if len(window) < USUAL_MIN_DAYS or values[day] <= statistics.median(window):
            break
        run += 1
    if run < ABOVE_MIN_DAYS:
        return None
    start = yesterday - dt.timedelta(days=run - 1)
    window = [values[d] for k in range(1, USUAL_DAYS + 1) if (d := start - dt.timedelta(days=k)) in values]
    usual = fmt(statistics.median(window), unit)
    return f"{label.capitalize()} above your usual ({usual}) {run} days in a row, through yesterday."


def week_on_week(label: str, unit: str | None, values: Mapping[dt.date, float], yesterday: dt.date) -> str | None:
    """The last 7 complete days' average against the 7 before, when it's clearly up."""

    def week(last: dt.date) -> list[float]:
        return [values[d] for k in range(WEEK) if (d := last - dt.timedelta(days=k)) in values]

    now, before = week(yesterday), week(yesterday - dt.timedelta(days=WEEK))
    if len(now) < WEEK_MIN_DAYS or len(before) < WEEK_MIN_DAYS:
        return None
    a, b = statistics.mean(now), statistics.mean(before)
    if b <= 0 or a < b * RISE:
        return None
    return f"{label.capitalize()}: {fmt(a, unit)} a day over the last 7 days, up from {fmt(b, unit)} the 7 days before."


def momentum(series: Mapping[str, Mapping[dt.date, float]], today: dt.date) -> list[str]:
    """Notes for the Momentum card: workouts first, then one note per activity series, at most ``MAX_NOTES``."""
    notes = workout_notes(series.get(WORKOUT, {}), today)
    yesterday = today - dt.timedelta(days=1)
    for feature, (label, unit) in ACTIVITY.items():
        values = series.get(feature, {})
        note = above_usual(label, unit, values, yesterday) or week_on_week(label, unit, values, yesterday)
        if note:
            notes.append(note)
    return notes[:MAX_NOTES]


def load_momentum(db: Session, today: dt.date) -> list[str]:
    features = [WORKOUT, *ACTIVITY]
    since = today - dt.timedelta(days=120)
    series: dict[str, dict[dt.date, float]] = {}
    rows = db.execute(
        sa.select(DailyFeature.feature, DailyFeature.day, DailyFeature.value).where(
            DailyFeature.feature.in_(features), DailyFeature.day <= today, DailyFeature.day >= since
        )
    )
    for r in rows:
        series.setdefault(r.feature, {})[r.day] = r.value
    return momentum(series, today)
