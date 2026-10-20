"""Statistics for the insight engine. DB-free and deterministic; tested against seeded synthetic data.

Three ideas carry the honesty of the engine:

- **Residuals, not raw values.** Each series loses its weekday profile and a
  slow (28-day centred) trend before it's related to anything, so "both are
  higher on weekends" or "both drifted up this month" never look like a link
  (risks.md C3).
- **Effective sample size.** Daily health data is autocorrelated; treating 90
  days as 90 independent points overstates significance. Correlation and
  rank tests use Bartlett's effective n from both series' autocorrelations
  over the first ten lags; window comparisons use the AR(1) variance
  inflation of a mean (C4).
- **One multiple-testing family.** Every p-value of a run goes through one
  Benjamini-Hochberg pass (C1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from .constants import INTERVAL_LEVEL, NEFF_MAX_LAG, STRENGTH_BANDS, TREND_MIN_PERIODS, TREND_WINDOW_DAYS


def as_daily(values: dict) -> pd.Series:
    """``{date: value}`` → a float Series on a DatetimeIndex (gaps stay gaps)."""
    if not values:
        return pd.Series(dtype="float64")
    s = pd.Series(values, dtype="float64")
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def residualize(s: pd.Series) -> pd.Series:
    """Remove the weekday profile, then a centred rolling-mean trend. Same index as the input's observed days."""
    s = s.dropna()
    if len(s) < TREND_MIN_PERIODS:
        return pd.Series(dtype="float64")
    weekday_mean = s.groupby(s.index.dayofweek).transform("mean")
    deweek = s - weekday_mean + s.mean()
    full = deweek.reindex(pd.date_range(deweek.index.min(), deweek.index.max(), freq="D"))
    trend = full.rolling(TREND_WINDOW_DAYS, center=True, min_periods=TREND_MIN_PERIODS).mean()
    return (deweek - trend.reindex(deweek.index)).dropna()


def autocorr(s: pd.Series, lag: int) -> float:
    """Correlation of days ``lag`` apart (pairs only where both days exist); 0 with too few pairs."""
    if s.empty:
        return 0.0
    nxt = s.shift(-lag, freq="D")
    pairs = pd.concat([s, nxt], axis=1, join="inner").dropna()
    if len(pairs) < 10 or pairs.iloc[:, 0].std() == 0 or pairs.iloc[:, 1].std() == 0:
        return 0.0
    return float(np.corrcoef(pairs.iloc[:, 0], pairs.iloc[:, 1])[0, 1])


def lag1_autocorr(s: pd.Series) -> float:
    return autocorr(s, 1)


def acf(s: pd.Series, max_lag: int = NEFF_MAX_LAG) -> np.ndarray:
    """Autocorrelations at lags 1..max_lag."""
    return np.array([autocorr(s, k) for k in range(1, max_lag + 1)])


def effective_n(n: int, acf_a: np.ndarray, acf_b: np.ndarray) -> float:
    """Bartlett: n / (1 + 2 Σ_k ρa(k) ρb(k)), clipped to [3, n]."""
    inflation = 1 + 2 * float(np.dot(acf_a, acf_b))
    return float(min(max(n / max(inflation, 1e-6), 3.0), n))


@dataclass(frozen=True)
class MeanShift:
    diff: float  # recent mean minus base mean
    se: float
    df: float
    p: float

    def interval(self, level: float = INTERVAL_LEVEL) -> tuple[float, float]:
        half = float(stats.t.isf((1 - level) / 2, self.df)) * self.se
        return self.diff - half, self.diff + half


def mean_shift_test(recent: np.ndarray, base: np.ndarray, r1: float) -> float:
    """Two-sided p for a difference in means between two windows of an AR(1)-like series."""
    return mean_shift(recent, base, r1).p


def mean_shift(recent: np.ndarray, base: np.ndarray, r1: float) -> MeanShift:
    """Difference in means between two windows of an AR(1)-like series, with its standard error and p.

    Each window's n is shrunk by the variance inflation of the mean of m
    autocorrelated days, then a Welch-style t test runs on the effective sizes.
    """
    r = min(max(r1, 0.0), 0.95)

    def n_eff(m: int) -> float:
        if r == 0 or m < 2:
            return float(m)
        inflation = (1 + r) / (1 - r) - 2 * r * (1 - r**m) / (m * (1 - r) ** 2)
        return m / max(inflation, 1.0)

    ne_r, ne_b = n_eff(len(recent)), n_eff(len(base))
    var_r, var_b = float(np.var(recent, ddof=1)), float(np.var(base, ddof=1))
    se = math.sqrt(var_r / ne_r + var_b / ne_b)
    diff = float(np.mean(recent)) - float(np.mean(base))
    df = max(ne_r + ne_b - 2, 2)
    if se == 0:
        return MeanShift(diff, 0.0, df, 1.0 if diff == 0 else 0.0)
    return MeanShift(diff, se, df, float(2 * stats.t.sf(abs(diff / se), df=df)))


def shift_days(s: pd.Series, days: int) -> pd.Series:
    """Re-index so the value of day t sits on day t + days (exposure today, outcome ``days`` later)."""
    return s.shift(days, freq="D") if days else s


@dataclass(frozen=True)
class CorrResult:
    rho: float
    p: float
    n: int
    n_eff: float


def spearman_eff(x: pd.Series, y: pd.Series, acf_x: np.ndarray, acf_y: np.ndarray) -> CorrResult | None:
    """Spearman correlation of aligned days with an autocorrelation-corrected p-value."""
    both = pd.concat([x, y], axis=1, join="inner").dropna()
    n = len(both)
    if n < 4 or both.iloc[:, 0].nunique() < 3 or both.iloc[:, 1].nunique() < 3:
        return None
    rho = float(stats.spearmanr(both.iloc[:, 0], both.iloc[:, 1]).statistic)
    if math.isnan(rho):
        return None
    n_eff = effective_n(n, acf_x, acf_y)
    if abs(rho) >= 1.0:
        return CorrResult(rho, 0.0, n, n_eff)
    t = rho * math.sqrt((n_eff - 2) / (1 - rho * rho))
    p = float(2 * stats.t.sf(abs(t), df=max(n_eff - 2, 1)))
    return CorrResult(rho, p, n, n_eff)


def cliffs_delta(a: np.ndarray, b: np.ndarray) -> float:
    """P(a > b) − P(a < b): the rank-based effect size for two groups, in [-1, 1]."""
    if len(a) == 0 or len(b) == 0:
        return 0.0
    diff = np.subtract.outer(a, b)
    return float((np.sign(diff)).mean())


@dataclass(frozen=True)
class GroupResult:
    delta: float  # Cliff's delta, "with" minus "without"
    p: float
    n_with: int
    n_without: int
    n_eff: float


def mann_whitney_eff(
    with_: np.ndarray, without: np.ndarray, acf_resid: np.ndarray, acf_flag: np.ndarray
) -> GroupResult | None:
    """Mann-Whitney U (normal approximation, tie-corrected) with the z scaled by sqrt(n_eff / n)."""
    n1, n2 = len(with_), len(without)
    if n1 < 2 or n2 < 2:
        return None
    result = stats.mannwhitneyu(with_, without, alternative="two-sided", method="asymptotic")
    p_raw = float(result.pvalue)
    n = n1 + n2
    n_eff = effective_n(n, acf_resid, acf_flag)
    scale = math.sqrt(n_eff / n)
    z = stats.norm.isf(p_raw / 2) if p_raw > 0 else 40.0
    p = float(2 * stats.norm.sf(abs(z) * scale))
    return GroupResult(cliffs_delta(with_, without), p, n1, n2, n_eff)


# Likely ranges ("evidence intervals", design 1b/1c). Each uses the same effective sample size as its test, so
# a range is as wide as day-to-day carry-over makes it; tests/stats checks their coverage.


def _z(level: float) -> float:
    return float(stats.norm.isf((1 - level) / 2))


def rho_interval(rho: float, n_eff: float, level: float = INTERVAL_LEVEL) -> tuple[float, float]:
    """Spearman's rho: Fisher z with Fieller's variance 1.06 / (n − 3), on the effective n."""
    if n_eff <= 4:
        return -1.0, 1.0
    z = math.atanh(min(max(rho, -0.9999), 0.9999))
    half = _z(level) * math.sqrt(1.06 / (n_eff - 3))
    return math.tanh(z - half), math.tanh(z + half)


def phi_interval(phi: float, n: int, level: float = INTERVAL_LEVEL) -> tuple[float, float]:
    """The phi coefficient of a 2×2 table, through Fisher z (it is a Pearson r on 0/1 data)."""
    if n <= 4:
        return -1.0, 1.0
    z = math.atanh(min(max(phi, -0.9999), 0.9999))
    half = _z(level) / math.sqrt(n - 3)
    return math.tanh(z - half), math.tanh(z + half)


def delta_interval(
    delta: float, n_with: int, n_without: int, n_eff: float, level: float = INTERVAL_LEVEL
) -> tuple[float, float]:
    """Cliff's delta via its AUC (P(with > without)): Hanley-McNeil variance, widened by n / n_eff."""
    auc = min(max((delta + 1) / 2, 1e-6), 1 - 1e-6)
    q1, q2 = auc / (2 - auc), 2 * auc * auc / (1 + auc)
    var = (auc * (1 - auc) + (n_with - 1) * (q1 - auc * auc) + (n_without - 1) * (q2 - auc * auc)) / (
        n_with * n_without
    )
    var *= (n_with + n_without) / max(n_eff, 1.0)
    half = _z(level) * math.sqrt(max(var, 0.0))
    lo, hi = max(auc - half, 0.0), min(auc + half, 1.0)
    return 2 * lo - 1, 2 * hi - 1


@dataclass(frozen=True)
class LagCurve:
    r: float  # signed strength: sqrt of the variance share the curve explains, with the sign of its total
    p: float
    n: int
    n_eff: float
    curve: list[float]  # standardised effect at lags 0..max_lag
    peak: int  # lag of the largest |effect|


def distributed_lag(x: pd.Series, y: pd.Series, max_lag: int, degree: int, min_days: int) -> LagCurve | None:
    """y(t) on x(t), x(t−1) … x(t−max_lag), the lag weights constrained to a polynomial of ``degree`` (Almon).

    Takes the observed values, not the residuals: the weekday profile and a straight-line trend are fitted
    inside the regression, because the 28-day rolling detrend the other tests use leaves shared structure that
    a regression on eight lags picks up (8.5% false positives on independent days, see tests/stats). Errors get
    an AR(1) model (Cochrane-Orcutt), and the F test for the whole curve (degree + 1 numerator df, one test for
    a week of lags) is shrunk to the effective n of the filtered exposure and residuals.
    """
    columns = {"y": y} | {k: shift_days(x, k) for k in range(max_lag + 1)}
    frame = pd.concat(columns, axis=1, join="inner").dropna()
    n = len(frame)
    if n < min_days or frame["y"].std() == 0 or frame[0].std() == 0:
        return None
    days = (frame.index - frame.index[0]).days.to_numpy().astype(float)
    weekday = frame.index.dayofweek.to_numpy()
    nuisance = np.column_stack(
        [np.ones(n), days / max(days.max(), 1.0)] + [(weekday == d).astype(float) for d in range(1, 7)]
    )
    basis = np.vander(np.arange(max_lag + 1) / max_lag, degree + 1, increasing=True)
    curve_cols = frame[list(range(max_lag + 1))].to_numpy() @ basis
    design = np.column_stack([nuisance, curve_cols])
    target = frame["y"].to_numpy()

    coef, *_ = np.linalg.lstsq(design, target, rcond=None)
    resid = target - design @ coef
    r1 = float(np.clip(np.corrcoef(resid[:-1], resid[1:])[0, 1], -0.95, 0.95)) if resid.std() > 0 else 0.0
    xs, ys = design[1:] - r1 * design[:-1], target[1:] - r1 * target[:-1]
    m, q = nuisance.shape[1], degree + 1
    full, *_ = np.linalg.lstsq(xs, ys, rcond=None)
    rest, *_ = np.linalg.lstsq(xs[:, :m], ys, rcond=None)
    left = ys - xs @ full
    rss1, rss0 = float(np.sum(left**2)), float(np.sum((ys - xs[:, :m] @ rest) ** 2))
    if rss1 <= 0 or rss0 <= 0:
        return None
    index = frame.index[1:]
    # Effective n of the fitted curve's predictor (the exposure as the curve weighs it, smoother than any one
    # lag) against y without the curve: with every pair tried (R17), a single lag column was too optimistic.
    fitted_x = xs[:, m:] @ full[m:]
    base = ys - xs[:, :m] @ rest
    n_eff = effective_n(len(ys), acf(pd.Series(fitted_x, index)), acf(pd.Series(base, index)))
    df2 = len(ys) - xs.shape[1] - 1
    f = ((rss0 - rss1) / q) / (rss1 / df2) * (n_eff / len(ys))
    p = float(stats.f.sf(f, q, max(n_eff - xs.shape[1] - 1, 2.0)))

    weights = basis @ full[m:]  # y units per x unit, by lag
    curve = weights * float(frame[0].std()) / float(frame["y"].std())
    # The curve's share of what's left, adjusted for its q fitted weights on the effective n: with every pair
    # tried (R17), the raw share's chance inflation (~q / n) let noise through the effect floor.
    raw_share = max(1 - rss1 / rss0, 0.0)
    share = max(raw_share - q * (1 - raw_share) / max(n_eff - xs.shape[1] - 1, 2.0), 0.0)
    r = math.copysign(math.sqrt(share), float(np.sum(weights)) or 1.0)
    return LagCurve(r, p, n, n_eff, [round(float(c), 3) for c in curve], int(np.argmax(np.abs(curve))))


@dataclass(frozen=True)
class PartialResult:
    rho: float  # rank correlation of x and y after both lose what the covariates explain
    rho_raw: float  # the same days without the covariates
    n: int
    resid_x: pd.Series
    resid_y: pd.Series


def partial_spearman(frame: pd.DataFrame, x: str, y: str, covariates: list[str]) -> PartialResult | None:
    """Partial Spearman: rank every column, regress x and y ranks on the covariate ranks, correlate what is left."""
    frame = frame.dropna()
    if len(frame) < 4 or frame[x].nunique() < 2 or frame[y].nunique() < 2:
        return None
    ranks = frame.rank()
    design = np.column_stack([np.ones(len(ranks)), ranks[covariates].to_numpy()])

    def left(col: str) -> np.ndarray:
        target = ranks[col].to_numpy()
        coef, *_ = np.linalg.lstsq(design, target, rcond=None)
        return target - design @ coef

    rx, ry = left(x), left(y)
    if rx.std() == 0 or ry.std() == 0:
        return None
    rho = float(np.corrcoef(rx, ry)[0, 1])
    rho_raw = float(np.corrcoef(ranks[x], ranks[y])[0, 1])
    return PartialResult(rho, rho_raw, len(frame), pd.Series(rx, frame.index), pd.Series(ry, frame.index))


def benjamini_hochberg(pvalues: list[float]) -> list[float]:
    """Adjusted p-values (step-up), same order as the input."""
    m = len(pvalues)
    if m == 0:
        return []
    order = np.argsort(pvalues)
    ranked = np.array(pvalues, dtype="float64")[order] * m / np.arange(1, m + 1)
    adjusted = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.minimum(adjusted, 1.0)
    return out.tolist()


def strength(effect: float) -> str:
    size = abs(effect)
    return next(label for floor, label in STRENGTH_BANDS if size >= floor)


def kruskal_weekday(s: pd.Series, min_per_day: int) -> tuple[float, float, dict[int, float], int] | None:
    """Kruskal-Wallis across weekdays on the de-trended series → ``(eta², p, weekday means, n)``."""
    s = s.dropna()
    if len(s) < 7 * min_per_day:
        return None
    full = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"))
    trend = full.rolling(TREND_WINDOW_DAYS, center=True, min_periods=TREND_MIN_PERIODS).mean().reindex(s.index)
    detrended = (s - trend + s.mean()).dropna()
    groups = [g.to_numpy() for _, g in detrended.groupby(detrended.index.dayofweek)]
    if len(groups) < 7 or min(len(g) for g in groups) < min_per_day:
        return None
    if all(np.ptp(g) == 0 for g in groups) and len({float(g[0]) for g in groups}) == 1:
        return None
    h, p = stats.kruskal(*groups)
    n = sum(len(g) for g in groups)
    eta2 = max((h - 7 + 1) / (n - 7), 0.0)
    means = {int(k): float(v) for k, v in s.groupby(s.index.dayofweek).mean().items()}
    return float(eta2), float(p), means, n
