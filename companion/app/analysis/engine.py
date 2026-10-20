"""Daily feature frame → findings. Pure: no DB, no clock (``today`` is passed in).

Three horizons, one Benjamini-Hochberg family (R8):

- **day**: relationships between features of different families, same day
  (lag 0) and next day in both directions (lag 1). Outside data (weather, almanac) is
  only ever the earlier side: never an outcome, and never tested for its own
  changes or weekday rhythm. Continuous pairs use
  Spearman on residuals; a yes/no feature (a count that is 0 on some observed
  days and >0 on others, e.g. "felt anxious") uses Mann-Whitney + Cliff's
  delta, or Fisher's exact test when both sides are yes/no.
- **week / month**: the last 7 (28) days against the 28 (56) before, as a
  mean shift with autocorrelation-aware sample sizes.
- **weekday rhythm**: Kruskal-Wallis across weekdays on the de-trended series.

A finding is reported only if its adjusted p clears the FDR target **and** its
effect clears a floor, so a tiny effect on lots of data stays quiet. For each
pair of features only the strongest relationship is kept.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats

from . import constants as C
from .pure import (
    acf,
    as_daily,
    benjamini_hochberg,
    cliffs_delta,
    delta_interval,
    distributed_lag,
    effective_n,
    kruskal_weekday,
    lag1_autocorr,
    mann_whitney_eff,
    mean_shift,
    partial_spearman,
    phi_interval,
    residualize,
    rho_interval,
    shift_days,
    spearman_eff,
    strength,
)


@dataclass(frozen=True)
class FeatureMeta:
    label: str
    unit: str | None = None
    kind: str = "continuous"  # continuous | count
    family: str = "other"
    analyse: bool = True


@dataclass(frozen=True)
class Finding:
    kind: str  # association | change | weekday
    horizon: str  # day | week | month
    a: str
    b: str | None
    lag: int | None
    method: str
    effect: float
    p: float
    n: int
    n_a: int | None = None
    n_b: int | None = None
    p_adj: float = 1.0
    strength: str = ""
    score: float = 0.0
    details: dict = field(default_factory=dict)


@dataclass
class _Prepared:
    raw: pd.Series
    resid: pd.Series
    acf: np.ndarray  # residual autocorrelations, lags 1..NEFF_MAX_LAG
    flag: pd.Series | None  # yes/no view (1.0 / 0.0) for yes/no features
    acf_flag: np.ndarray


def _prepare(values: Mapping[dt.date, float], meta: FeatureMeta) -> _Prepared | None:
    raw = as_daily(dict(values)).dropna()
    if len(raw) < C.MIN_PAIRED_DAYS or raw.nunique() < 2:
        return None
    flag = None
    acf_flag = np.zeros(C.NEFF_MAX_LAG)
    if meta.kind == "count":
        yes = (raw > 0).astype("float64")
        if yes.sum() >= C.MIN_GROUP_DAYS and (1 - yes).sum() >= C.MIN_GROUP_DAYS:
            flag, acf_flag = yes, acf(yes)
    resid = residualize(raw)
    if flag is None and (len(resid) < C.MIN_PAIRED_DAYS or resid.nunique() < 3):
        return None
    return _Prepared(raw, resid, acf(resid), flag, acf_flag)


def _aligned(x: pd.Series, y: pd.Series) -> pd.DataFrame:
    return pd.concat([x, y], axis=1, join="inner").dropna()


def _group_test(flag: pd.Series, acf_flag: np.ndarray, cont: _Prepared, cont_raw: pd.Series) -> tuple | None:
    """Continuous residuals split by a yes/no flag (already lag-shifted onto the same days)."""
    both = _aligned(flag, cont.resid)
    if both.empty:
        return None
    yes = both.iloc[:, 0] > 0
    with_, without = both.iloc[:, 1][yes].to_numpy(), both.iloc[:, 1][~yes].to_numpy()
    if len(with_) < C.MIN_GROUP_DAYS or len(without) < C.MIN_GROUP_DAYS:
        return None
    result = mann_whitney_eff(with_, without, cont.acf, acf_flag)
    if result is None:
        return None
    raw = cont_raw.reindex(both.index)
    medians = {"with": float(raw[yes].median()), "without": float(raw[~yes].median())}
    return result, medians


def _exogenous(meta: FeatureMeta) -> bool:
    return meta.family in C.EXOGENOUS_FAMILIES


def _associations(prepared: dict[str, _Prepared], meta: Mapping[str, FeatureMeta]) -> list[Finding]:
    out: list[Finding] = []
    for a, b in combinations(sorted(prepared), 2):
        if meta[a].family == meta[b].family or (_exogenous(meta[a]) and _exogenous(meta[b])):
            continue
        if _exogenous(meta[b]):
            a, b = b, a  # outside data reads as the first side ("on warmer days, ...")
        for x, y, lag in ((a, b, 0), (a, b, 1), (b, a, 1)):
            if lag and _exogenous(meta[y]):
                continue  # nothing you do today goes with tomorrow's weather
            finding = _pair(x, y, lag, prepared[x], prepared[y])
            if finding is not None:
                out.append(finding)
    return out


def _pair(x: str, y: str, lag: int, px: _Prepared, py: _Prepared) -> Finding | None:
    """x on day t against y on day t + lag."""
    if px.flag is not None and py.flag is not None:
        both = _aligned(shift_days(px.flag, lag), py.flag)
        if len(both) < C.MIN_PAIRED_DAYS:
            return None
        table = pd.crosstab(both.iloc[:, 0] > 0, both.iloc[:, 1] > 0).reindex(
            index=[True, False], columns=[True, False], fill_value=0
        )
        (tt, tf), (ft, ff) = table.to_numpy()
        if min(tt + tf, ft + ff) < C.MIN_GROUP_DAYS:
            return None
        _, p = stats.fisher_exact([[tt, tf], [ft, ff]])
        denom = math.sqrt((tt + tf) * (ft + ff) * (tt + ft) * (tf + ff)) or 1.0
        phi = (tt * ff - tf * ft) / denom
        rate_with, rate_without = tt / (tt + tf), ft / (ft + ff)
        return Finding(
            "association",
            "day",
            x,
            y,
            lag,
            "fisher",
            float(phi),
            float(p),
            len(both),
            int(tt + tf),
            int(ft + ff),
            details={
                "rate_with": rate_with,
                "rate_without": rate_without,
                "ci": _rounded(phi_interval(phi, len(both))),
            },
        )
    if px.flag is not None:
        res = _group_test(shift_days(px.flag, lag), px.acf_flag, py, py.raw)
        if res is None:
            return None
        g, medians = res
        return Finding(
            "association",
            "day",
            x,
            y,
            lag,
            "mann_whitney",
            g.delta,
            g.p,
            g.n_with + g.n_without,
            g.n_with,
            g.n_without,
            details={
                "median_with": medians["with"],
                "median_without": medians["without"],
                "flag_side": "a",
                "n_eff": round(g.n_eff, 1),
                "ci": _rounded(delta_interval(g.delta, g.n_with, g.n_without, g.n_eff)),
            },
        )
    if py.flag is not None:
        # Continuous x (shifted by lag) split by whether y happened on the later day.
        shifted = _Prepared(shift_days(px.raw, lag), shift_days(px.resid, lag), px.acf, None, px.acf_flag)
        res = _group_test(py.flag, py.acf_flag, shifted, shifted.raw)
        if res is None:
            return None
        g, medians = res
        return Finding(
            "association",
            "day",
            x,
            y,
            lag,
            "mann_whitney",
            g.delta,
            g.p,
            g.n_with + g.n_without,
            g.n_with,
            g.n_without,
            details={
                "median_with": medians["with"],
                "median_without": medians["without"],
                "flag_side": "b",
                "n_eff": round(g.n_eff, 1),
                "ci": _rounded(delta_interval(g.delta, g.n_with, g.n_without, g.n_eff)),
            },
        )
    corr = spearman_eff(shift_days(px.resid, lag), py.resid, px.acf, py.acf)
    if corr is None or corr.n < C.MIN_PAIRED_DAYS:
        return None
    return Finding(
        "association",
        "day",
        x,
        y,
        lag,
        "spearman",
        corr.rho,
        corr.p,
        corr.n,
        details={"n_eff": round(corr.n_eff, 1), "ci": _rounded(rho_interval(corr.rho, corr.n_eff))},
    )


def _rounded(interval: tuple[float, float]) -> list[float]:
    return [round(interval[0], 3), round(interval[1], 3)]


def _is_exposure(feature: str, meta: FeatureMeta) -> bool:
    return feature in C.DLM_EXPOSURES or meta.family.startswith(C.DLM_EXPOSURE_FAMILY_PREFIXES)


def _lag_curves(prepared: Mapping[str, _Prepared], meta: Mapping[str, FeatureMeta]) -> list[Finding]:
    """Exposure → outcome over days 0..DLM_MAX_LAG: one smooth curve and one test per pair (R8)."""
    out: list[Finding] = []
    for x in sorted(prepared):
        if not _is_exposure(x, meta[x]):
            continue
        for y in sorted(prepared):
            if y == x or meta[y].family == meta[x].family or _exogenous(meta[y]):
                continue
            px, py = prepared[x], prepared[y]
            res = distributed_lag(px.raw, py.raw, C.DLM_MAX_LAG, C.DLM_DEGREE, C.DLM_MIN_DAYS)
            if res is None:
                continue
            out.append(
                Finding(
                    "association",
                    "days",
                    x,
                    y,
                    res.peak,
                    "distributed_lag",
                    res.r,
                    res.p,
                    res.n,
                    details={"curve": res.curve, "peak": res.peak, "n_eff": round(res.n_eff, 1)},
                )
            )
    return out


def _changes(prepared_raw: Mapping[str, pd.Series], today: dt.date) -> list[Finding]:
    out: list[Finding] = []
    end = pd.Timestamp(today - dt.timedelta(days=1))  # today is still running
    for feature, raw in prepared_raw.items():
        for horizon, (recent_days, base_days) in C.CHANGE_HORIZONS.items():
            recent = raw[(raw.index > end - pd.Timedelta(days=recent_days)) & (raw.index <= end)]
            base_end = end - pd.Timedelta(days=recent_days)
            base = raw[(raw.index > base_end - pd.Timedelta(days=base_days)) & (raw.index <= base_end)]
            if len(recent) < C.CHANGE_MIN_FRACTION * recent_days or len(base) < C.CHANGE_MIN_FRACTION * base_days:
                continue
            if recent.nunique() < 2 and base.nunique() < 2:
                continue
            # Mean shift with autocorrelation-aware sizes: a plain rank test on consecutive days
            # flagged ~30% of pure noise as a change (see tests/stats).
            shift = mean_shift(recent.to_numpy(), base.to_numpy(), lag1_autocorr(raw))
            p = shift.p
            base_mean = float(base.mean())
            pct = (float(recent.mean()) - base_mean) / abs(base_mean) * 100 if base_mean else 0.0
            lo, hi = shift.interval()
            pct_ci = [round(lo / abs(base_mean) * 100, 1), round(hi / abs(base_mean) * 100, 1)] if base_mean else None
            out.append(
                Finding(
                    "change",
                    horizon,
                    feature,
                    None,
                    None,
                    "mean_shift",
                    cliffs_delta(recent.to_numpy(), base.to_numpy()),
                    p,
                    len(recent) + len(base),
                    len(recent),
                    len(base),
                    details={
                        "recent_mean": float(recent.mean()),
                        "base_mean": base_mean,
                        "pct": pct,
                        "recent_days": recent_days,
                        "base_days": base_days,
                        "pct_ci": pct_ci,
                    },
                )
            )
    return out


def _weekdays(prepared_raw: Mapping[str, pd.Series]) -> list[Finding]:
    out: list[Finding] = []
    for feature, raw in prepared_raw.items():
        res = kruskal_weekday(raw, C.WEEKDAY_MIN_PER_DAY)
        if res is None:
            continue
        eta2, p, means, n = res
        hi, lo = max(means, key=means.get), min(means, key=means.get)
        out.append(
            Finding(
                "weekday",
                "week",
                feature,
                None,
                None,
                "kruskal",
                eta2,
                p,
                n,
                details={"means": {str(k): v for k, v in means.items()}, "high": hi, "low": lo},
            )
        )
    return out


def _view(name: str, p: _Prepared, as_flag: bool) -> pd.Series:
    return p.flag if as_flag and p.flag is not None else p.resid


def _adjusted(f: Finding, prepared: Mapping[str, _Prepared], meta: Mapping[str, FeatureMeta]) -> dict | None:
    """Re-read a reported relationship allowing for everyday drivers (ADJUST_FOR): does it hold, or do they explain it?

    The same residuals the finding came from (a yes/no side as 0/1), with each driver on the later day and, for
    a next-day finding, on the earlier day too. Partial Spearman on the overlapping days, with a likely range on
    the effective n less the covariates.
    """
    if f.kind != "association" or f.method in ("fisher", "distributed_lag") or f.b is None:
        return None
    families = {meta[f.a].family, meta[f.b].family}
    drivers = [c for c in C.ADJUST_FOR if c in prepared and c not in (f.a, f.b) and meta[c].family not in families]
    if not drivers:
        return None
    side = f.details.get("flag_side")
    x = shift_days(_view(f.a, prepared[f.a], side == "a"), f.lag or 0)
    y = _view(f.b, prepared[f.b], side == "b")
    columns = {"x": x, "y": y}
    for c in drivers:
        columns[c] = prepared[c].resid
        if f.lag:
            columns[f"{c}@before"] = shift_days(prepared[c].resid, f.lag)
    frame = pd.concat(columns, axis=1, join="inner").dropna()
    covariates = [k for k in columns if k not in ("x", "y")]
    if len(frame) < C.MIN_PAIRED_DAYS:
        return None
    res = partial_spearman(frame, "x", "y", covariates)
    if res is None:
        return None
    n_eff = effective_n(res.n, acf(res.resid_x), acf(res.resid_y)) - len(covariates)
    lo, hi = rho_interval(res.rho, max(n_eff, 3.0))
    same_sign = res.rho * res.rho_raw > 0
    if same_sign and (lo > 0 or hi < 0):
        verdict = "holds"
    elif same_sign and abs(res.rho) >= C.ADJUST_EXPLAINED_SHARE * abs(res.rho_raw):
        verdict = "weaker"
    else:
        verdict = "explained"
    return {
        "for": drivers,
        "rho": round(res.rho, 3),
        "unadjusted": round(res.rho_raw, 3),
        "n": res.n,
        "ci": _rounded((lo, hi)),
        "verdict": verdict,
    }


def _passes_floor(f: Finding) -> bool:
    if f.method == "distributed_lag":
        return abs(f.effect) >= C.RHO_FLOOR and f.details["peak"] >= C.DLM_MIN_PEAK
    if f.kind == "association":
        return abs(f.effect) >= (C.RHO_FLOOR if f.method in ("spearman", "fisher") else C.CLIFF_FLOOR)
    if f.kind == "change":
        return abs(f.details["pct"]) >= C.CHANGE_PCT_FLOOR and abs(f.effect) >= C.CHANGE_CLIFF_FLOOR
    return f.effect >= C.WEEKDAY_ETA2_FLOOR


def _strength(f: Finding) -> str:
    if f.kind == "weekday":
        return "strong" if f.effect >= 0.14 else "moderate" if f.effect >= 0.06 else "weak"
    return strength(f.effect)


@dataclass
class RunStats:
    """What a run looked at, so an empty result can say why (risks.md G2)."""

    features: int = 0
    eligible: int = 0
    tests: int = 0
    reported: int = 0


def analyse(
    values: Mapping[str, Mapping[dt.date, float]],
    meta: Mapping[str, FeatureMeta],
    today: dt.date,
    run_stats: RunStats | None = None,
) -> list[Finding]:
    """All findings of one run, ranked (most notable first)."""
    prepared: dict[str, _Prepared] = {}
    for feature, series in values.items():
        m = meta.get(feature)
        if m is None or not m.analyse:
            continue
        p = _prepare(series, m)
        if p is not None:
            prepared[feature] = p
    raw = {f: p.raw for f, p in prepared.items() if not _exogenous(meta[f])}

    candidates = _associations(prepared, meta) + _lag_curves(prepared, meta) + _changes(raw, today) + _weekdays(raw)
    adjusted = benjamini_hochberg([f.p for f in candidates])  # one family for everything (R8)
    reported: list[Finding] = []
    for f, p_adj in zip(candidates, adjusted, strict=True):
        f = replace(f, p_adj=p_adj)
        if p_adj <= C.FDR_Q and _passes_floor(f):
            score = abs(f.effect) * -math.log10(max(p_adj, 1e-12))
            reported.append(replace(f, strength=_strength(f), score=score))

    # One relationship per pair of features: the strongest lag/direction.
    best: dict[tuple, Finding] = {}
    for f in reported:
        key = (f.kind, f.horizon, *sorted((f.a, f.b or "")))
        if key not in best or f.score > best[key].score:
            best[key] = f
    ranked = sorted(best.values(), key=lambda f: f.score, reverse=True)
    ranked = [
        replace(f, details={**f.details, "adjusted": adj}) if (adj := _adjusted(f, prepared, meta)) else f
        for f in ranked
    ]
    if run_stats is not None:
        run_stats.features, run_stats.eligible = len(values), len(prepared)
        run_stats.tests, run_stats.reported = len(candidates), len(ranked)
    return ranked


def null_false_discovery(findings: list[Finding], planted: set[tuple[str, str]]) -> float:
    """Share of reported associations that are not a planted pair (for the stats suite)."""
    assoc = [f for f in findings if f.kind == "association"]
    if not assoc:
        return 0.0
    false = [f for f in assoc if tuple(sorted((f.a, f.b))) not in planted]
    return len(false) / len(assoc)
