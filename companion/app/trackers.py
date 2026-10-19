"""Tracker types (design §2.1): validation, and the daily features each type produces. Pure.

The set of types is code; trackers themselves are data. Each type decides how
a raw value is checked and stored (``value_num`` / ``value_text``) and which
daily features it yields. Features follow "missing is not zero" (R7): a count
or yes/no tracker is 0 only on a reviewed day, or every day for an "always
logged" tracker; scale, quantity and time trackers are never zero-filled.
"""

from __future__ import annotations

import datetime as dt
import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

TYPES = ("count", "scale", "check", "quantity", "duration", "time", "choice", "moment", "tags")
TYPE_LABELS = {
    "count": "Count",
    "scale": "Rating 1–10",
    "check": "Yes / no",
    "quantity": "Amount",
    "duration": "Minutes",
    "time": "Time of day",
    "choice": "Pick one",
    "moment": "Moment",
    "tags": "Tags only",
}
# One line each for the "What are you tracking?" choice on the New metric form, in display order;
# the first COMMON_TYPES are shown, the rest sit under "More kinds".
TYPE_HINTS = {
    "scale": "How good, bad or intense something was",
    "count": "How many: cups, drinks, cigarettes",
    "check": "Did it happen today",
    "moment": "Log each time it happens: a headache, an argument",
    "tags": "Pick what applied today: meeting heavy, travel",
    "quantity": "A number with a unit: mg, km, $",
    "duration": "How long, in minutes",
    "choice": "One of a few options: home, takeout, skipped",
    "time": "When it first happened: first coffee, bedtime",
}
COMMON_TYPES = 5
DEFAULT_SCALE = (1.0, 10.0)  # one scale for every rating: nothing to set up, and ratings compare
MAX_TAGS = 24
MAX_TAG_LENGTH = 40
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MAX_FUTURE = dt.timedelta(minutes=5)  # risks.md B8: device clocks may be slightly ahead, not more
MOMENT_MAX_INTENSITY = 3


class TrackerInputError(ValueError):
    """A value the tracker's type doesn't accept. The message is shown to the user."""


@dataclass(frozen=True)
class TrackerSpec:
    """The parts of a tracker the pure code needs (mirrors the model)."""

    key: str
    name: str
    type: str
    unit: str | None = None
    scale_min: float | None = None
    scale_max: float | None = None
    options: tuple[str, ...] = ()
    always_logged: bool = False
    tags: tuple[str, ...] = ()  # display text; entries and features use tag_slug()


def slugify(name: str) -> str:
    """A tracker key from its name: 'First social media!' → 'first_social_media'."""
    key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not key or not key[0].isalpha():
        key = f"t_{key}" if key else "tracker"
    return key[:64]


def tag_slug(tag: str) -> str:
    """'Meeting heavy' → 'meeting_heavy' (the stored value and the feature suffix)."""
    return re.sub(r"[^a-z0-9]+", "_", tag.lower()).strip("_")[:MAX_TAG_LENGTH]


def parse_tags(raw: str) -> list[str]:
    """'in-fighting, Meeting heavy,' → ['in-fighting', 'Meeting heavy'] (display text, deduplicated by slug)."""
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        tag = " ".join(part.split())
        if tag and tag_slug(tag) not in seen:
            seen.add(tag_slug(tag))
            out.append(tag)
    return out


def validate_definition(spec: TrackerSpec) -> None:
    if not KEY_RE.match(spec.key):
        raise TrackerInputError("the key must start with a letter and use only a-z, 0-9 and _ (max 64)")
    if spec.type not in TYPES:
        raise TrackerInputError(f"unknown type {spec.type!r}")
    if not spec.name.strip():
        raise TrackerInputError("a tracker needs a name")
    if spec.type == "scale":
        if spec.scale_min is None or spec.scale_max is None or spec.scale_min >= spec.scale_max:
            raise TrackerInputError("a scale needs a minimum below its maximum")
    if spec.type == "choice":
        if len(spec.options) < 2:
            raise TrackerInputError("a choice needs at least two options")
        if any(not KEY_RE.match(o) for o in spec.options) or len(set(spec.options)) != len(spec.options):
            raise TrackerInputError("options must be distinct, lowercase words (a-z, 0-9, _)")
    if spec.type == "tags" and not spec.tags:
        raise TrackerInputError("add at least one tag, separated by commas")
    if len(spec.tags) > MAX_TAGS:
        raise TrackerInputError(f"at most {MAX_TAGS} tags")
    slugs = [tag_slug(t) for t in spec.tags]
    if any(not s or len(t) > MAX_TAG_LENGTH for s, t in zip(slugs, spec.tags, strict=True)):
        raise TrackerInputError(f"a tag needs a letter or digit and at most {MAX_TAG_LENGTH} characters")
    if len(set(slugs)) != len(slugs):
        raise TrackerInputError("two tags are the same")


def _number(raw: object) -> float:
    if isinstance(raw, bool):
        raise TrackerInputError("expected a number")
    if isinstance(raw, int | float):
        return float(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            return float(raw.strip())
        except ValueError:
            pass
    raise TrackerInputError("expected a number")


def parse_value(spec: TrackerSpec, raw: object) -> tuple[float | None, str | None]:
    """Check a raw value against the tracker's type → ``(value_num, value_text)``.

    ``None`` means "the type's default": 1 for a count, yes for a check, no
    intensity for a moment, "at that time" for a time tracker.
    """
    t = spec.type
    if t == "count":
        v = 1.0 if raw is None or raw == "" else _number(raw)
        if v < 0 or v != int(v):
            raise TrackerInputError("a count is a whole number, 0 or more")
        return v, None
    if t == "scale":
        v = _number(raw)
        if not (spec.scale_min <= v <= spec.scale_max):
            raise TrackerInputError(f"pick a value from {spec.scale_min:g} to {spec.scale_max:g}")
        return v, None
    if t == "check":
        if raw is None or raw == "":
            return 1.0, None
        if isinstance(raw, bool):
            return float(raw), None
        text = str(raw).strip().lower()
        if text in ("1", "yes", "y", "true", "on"):
            return 1.0, None
        if text in ("0", "no", "n", "false", "off"):
            return 0.0, None
        raise TrackerInputError("answer yes or no")
    if t in ("quantity", "duration"):
        v = _number(raw)
        if v < 0:
            raise TrackerInputError("the amount can't be negative")
        return v, None
    if t == "time":
        return None, None  # the observation's time is the value
    if t == "choice":
        text = str(raw).strip().lower() if raw is not None else ""
        if text not in spec.options:
            raise TrackerInputError(f"pick one of: {', '.join(spec.options)}")
        return None, text
    if t == "moment":
        if raw is None or raw == "":
            return None, None
        v = _number(raw)
        if v != int(v) or not 1 <= v <= MOMENT_MAX_INTENSITY:
            raise TrackerInputError(f"intensity is 1 to {MOMENT_MAX_INTENSITY}")
        return v, None
    if t == "tags":
        raise TrackerInputError("pick a tag")
    raise TrackerInputError(f"unknown type {t!r}")


def parse_tag(spec: TrackerSpec, raw: str) -> str:
    """A tag picked for an entry → its slug; only the tracker's own tags are accepted."""
    slug = tag_slug(raw or "")
    if slug not in {tag_slug(t) for t in spec.tags}:
        raise TrackerInputError(f"{spec.name} has no tag {raw!r}")
    return slug


def check_time(observed_at: dt.datetime, now: dt.datetime) -> None:
    if observed_at.tzinfo is None:
        raise TrackerInputError("the time needs a UTC offset")
    if observed_at > now + MAX_FUTURE:
        raise TrackerInputError("that time is in the future")


def minutes_of_day(ts: dt.datetime, zone: ZoneInfo, boundary: dt.time) -> float:
    """Clock time as minutes after local midnight, rolled past the day boundary: 00:30 → 1470, not 30."""
    local = ts.astimezone(zone)
    m = local.hour * 60 + local.minute + local.second / 60
    return m + 1440 if m < boundary.hour * 60 + boundary.minute else m


# --- daily features --------------------------------------------------------


@dataclass(frozen=True)
class Obs:
    observed_at: dt.datetime
    day: dt.date
    value_num: float | None
    value_text: str | None
    tag: str | None = None  # a tag entry carries no value


@dataclass
class TrackerFeatures:
    values: dict[str, dict[dt.date, float]] = field(default_factory=dict)
    labels: dict[str, tuple[str, str | None, str]] = field(default_factory=dict)  # feature → (label, unit, kind)

    def put(self, feature: str, day: dt.date, value: float) -> None:
        self.values.setdefault(feature, {})[day] = value


def observed_days(spec: TrackerSpec, logged: set[dt.date], reviewed: set[dt.date], last_day: dt.date) -> set[dt.date]:
    """Days on which an absence of entries means zero (R7)."""
    if spec.always_logged and logged:
        first = min(logged)
        return {first + dt.timedelta(days=i) for i in range((last_day - first).days + 1)}
    return logged | reviewed


def daily_features(
    spec: TrackerSpec,
    obs: Iterable[Obs],
    reviewed: set[dt.date],
    last_day: dt.date,
    zone: ZoneInfo,
    boundary: dt.time,
) -> TrackerFeatures:
    """Features of one tracker. ``last_day`` is the last complete day (zero-fill never reaches today)."""
    out = TrackerFeatures()
    by_day: dict[dt.date, list[Obs]] = {}
    tags_by_day: dict[dt.date, set[str]] = {}
    for o in obs:
        if o.tag is None:
            by_day.setdefault(o.day, []).append(o)
        else:
            tags_by_day.setdefault(o.day, set()).add(o.tag)
    base = f"tracker.{spec.key}"
    name, unit = spec.name, spec.unit
    zero_days = {d for d in observed_days(spec, set(by_day), reviewed, last_day) if d <= last_day}

    def label(feature: str, text: str, unit_: str | None, kind: str) -> None:
        out.labels[feature] = (text, unit_, kind)

    t = spec.type
    if t in ("count", "quantity", "duration"):
        f = f"{base}.total"
        label(f, name, unit or ("min" if t == "duration" else None), "count" if t == "count" else "continuous")
        for d in zero_days | set(by_day):
            out.put(f, d, sum(o.value_num or 0.0 for o in by_day.get(d, [])))
    elif t == "check":
        f = f"{base}.any"
        label(f, name, None, "count")
        for d in zero_days | set(by_day):
            out.put(f, d, float(any((o.value_num or 0) > 0 for o in by_day.get(d, []))))
    elif t == "scale":
        for suffix, text, agg in (("mean", name, statistics.fmean), ("max", f"{name} (highest)", max)):
            f = f"{base}.{suffix}"
            label(f, text, unit, "continuous")
            for d, items in by_day.items():
                vals = [o.value_num for o in items if o.value_num is not None]
                if vals:
                    out.put(f, d, float(agg(vals)))
    elif t == "choice":
        for option in spec.options:
            f = f"{base}.{option}"
            label(f, f"{name}: {option.replace('_', ' ')}", None, "count")
            for d in zero_days | set(by_day):
                out.put(f, d, float(sum(o.value_text == option for o in by_day.get(d, []))))
    elif t == "moment":
        f = f"{base}.count"
        label(f, name, None, "count")
        for d in zero_days | set(by_day):
            out.put(f, d, float(len(by_day.get(d, []))))
        f_int = f"{base}.max_intensity"
        label(f_int, f"{name} (strongest)", None, "continuous")
        for d, items in by_day.items():
            vals = [o.value_num for o in items if o.value_num is not None]
            if vals:
                out.put(f_int, d, max(vals))

    if spec.tags:
        # A tag is 1 on a day it was picked and 0 on a day the tracker was otherwise used or the
        # day was reviewed (you saw the tag and didn't pick it); unknown everywhere else (R7).
        used = set(by_day) | set(tags_by_day)
        tag_days = {d for d in observed_days(spec, used, reviewed, last_day) if d <= last_day} | set(tags_by_day)
        for tag in spec.tags:
            slug = tag_slug(tag)
            f = f"{base}.tag.{slug}"
            label(f, f"{name}: {tag}", None, "count")
            for d in tag_days:
                out.put(f, d, float(slug in tags_by_day.get(d, set())))

    if t in ("time",) or (t in ("count", "moment") and by_day):
        # Clock-time features: first (and for counts, last) time of the day.
        first_f = f"{base}.first_time"
        label(first_f, f"{name} (first time)", "min after midnight", "continuous")
        for d, items in by_day.items():
            mins = [minutes_of_day(o.observed_at, zone, boundary) for o in items]
            out.put(first_f, d, min(mins))
        if t == "count":
            last_f = f"{base}.last_time"
            label(last_f, f"{name} (last time)", "min after midnight", "continuous")
            for d, items in by_day.items():
                out.put(last_f, d, max(minutes_of_day(o.observed_at, zone, boundary) for o in items))
    return out
