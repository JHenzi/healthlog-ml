"""Findings → plain-language sentences.

Association language only (R10): "tends to", "goes with", "is followed by";
never causal or diagnostic words, which the wording lint in the tests
enforces. Every sentence carries its evidence: the number of days and a
strength word (R13); the exact statistics are on the explain view.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..metrics_view import fmt
from ..today import fmt_hours
from .engine import FeatureMeta, Finding

# Calendar facts as events; each reads after "On days", "The day after" and "When".
ALMANAC_EVENTS = {
    "almanac.holiday": "it was a public holiday",
}
WEEKDAY_NAMES = ("Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays")


def value(v: float, meta: FeatureMeta) -> str:
    if meta.unit == "h":
        return fmt_hours(v)
    return fmt(v, meta.unit)


def name(meta: FeatureMeta) -> str:
    """A feature's label as it reads mid-sentence."""
    return (
        meta.label[0].lower() + meta.label[1:]
        if meta.label[:1].isupper() and not meta.label[1:2].isupper()
        else meta.label
    )


def happening(feature: str, meta: FeatureMeta) -> str:
    """A yes/no feature as an event: 'you logged feeling anxious'."""
    if feature.startswith("mood.label."):
        return f"you logged feeling {feature.removeprefix('mood.label.').replace('_', ' ')}"
    if feature in ALMANAC_EVENTS:
        return ALMANAC_EVENTS[feature]
    if feature.startswith("mood.assoc."):
        return f"you logged a mood about {feature.removeprefix('mood.assoc.').replace('_', ' ')}"
    return f"{name(meta)} was logged"


def _evidence(f: Finding) -> str:
    if f.n_a is not None and f.n_b is not None:
        return f"{f.n_a} vs {f.n_b} days, {f.strength}"
    return f"{f.n} days, {f.strength}"


def association(f: Finding, meta: Mapping[str, FeatureMeta]) -> str:
    a, b = meta[f.a], meta[f.b]
    if f.method == "distributed_lag":
        direction = "higher" if f.effect > 0 else "lower"
        peak = f.details["peak"]
        return (
            f"Higher {name(a)} tends to be followed by {direction} {name(b)} over the next days, "
            f"most around {peak} days later ({_evidence(f)})."
        )
    if f.method == "spearman":
        direction = "higher" if f.effect > 0 else "lower"
        if f.lag == 0:
            return f"Days with higher {name(a)} tend to have {direction} {name(b)} ({_evidence(f)})."
        return f"Higher {name(a)} tends to be followed by {direction} {name(b)} the next day ({_evidence(f)})."
    if f.method == "fisher":
        w, wo = f.details["rate_with"], f.details["rate_without"]
        when = "the next day" if f.lag else "on the same day"
        return (
            f"When {happening(f.a, a)}, {happening(f.b, b)} {when} on {w:.0%} of days, "
            f"against {wo:.0%} otherwise ({_evidence(f)})."
        )
    # Mann-Whitney: one side is a yes/no event.
    higher = "higher" if f.effect > 0 else "lower"
    mw, mwo = f.details["median_with"], f.details["median_without"]
    if f.details.get("flag_side") == "a":  # event on day t, measure on t + lag
        cont = b
        lead = f"On days {happening(f.a, a)}" if f.lag == 0 else f"The day after {happening(f.a, a)}"
        return (
            f"{lead}, {name(cont)} tended to be {higher}: median {value(mw, cont)} vs {value(mwo, cont)} "
            f"({_evidence(f)})."
        )
    cont = a  # measure on day t, event on t + lag
    if f.lag == 0:
        return (
            f"On days {happening(f.b, b)}, {name(cont)} tended to be {higher}: median {value(mw, cont)} vs "
            f"{value(mwo, cont)} ({_evidence(f)})."
        )
    return (
        f"The day before {happening(f.b, b)}, {name(cont)} tended to be {higher}: median {value(mw, cont)} vs "
        f"{value(mwo, cont)} ({_evidence(f)})."
    )


def change(f: Finding, meta: Mapping[str, FeatureMeta]) -> str:
    m = meta[f.a]
    d = f.details
    above = "above" if d["pct"] > 0 else "below"
    return (
        f"{m.label} over the last {d['recent_days']} days averaged {value(d['recent_mean'], m)}, "
        f"{abs(d['pct']):.0f}% {above} the {d['base_days']} days before ({value(d['base_mean'], m)}; "
        f"{_evidence(f)})."
    )


def weekday(f: Finding, meta: Mapping[str, FeatureMeta]) -> str:
    m = meta[f.a]
    means = {int(k): v for k, v in f.details["means"].items()}
    hi, lo = f.details["high"], f.details["low"]
    return (
        f"{m.label} is highest on {WEEKDAY_NAMES[hi]} ({value(means[hi], m)}) and lowest on "
        f"{WEEKDAY_NAMES[lo]} ({value(means[lo], m)}) ({_evidence(f)})."
    )


def sentence(f: Finding, meta: Mapping[str, FeatureMeta]) -> str:
    return {"association": association, "change": change, "weekday": weekday}[f.kind](f, meta)
