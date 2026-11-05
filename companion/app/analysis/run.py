"""DB side of the engine: read ``daily_features``, analyse, replace ``insights``."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .. import features, goodday
from ..auth import now_utc
from ..models import EarlierInsight, FeatureDef, Insight, Setting
from .constants import FDR_Q, MIN_PAIRED_DAYS
from .engine import FeatureMeta, RunStats, analyse
from .history import diff, expired, finding_key
from .sentences import sentence

log = logging.getLogger("companion.analysis")

STATS_KEY = "analysis_last_run"


def load_meta(db: Session) -> dict[str, FeatureMeta]:
    defs = list(db.execute(sa.select(FeatureDef)).scalars())
    parts = goodday.built_from({d.feature: d.family for d in defs})
    return {
        d.feature: FeatureMeta(
            d.label, d.unit, d.kind, d.family, d.analyse, parts if d.feature == goodday.FEATURE else ()
        )
        for d in defs
    }


def _key(i: Insight | EarlierInsight) -> str:
    return finding_key(i.kind, i.horizon, i.feature_a, i.feature_b, i.lag, i.method)


def _keep_history(db: Session, previous: dict[str, Insight], current: set[str], today: dt.date) -> None:
    """Move findings that dropped out to ``earlier_insights``; take back the ones that returned (B17, not analysed)."""
    earlier = {_key(e): e for e in db.execute(sa.select(EarlierInsight)).scalars()}
    change = diff(previous, current, earlier)
    for key in change.back:
        db.delete(earlier.pop(key))
    for key in change.dropped:
        i = previous[key]
        if (old := earlier.pop(key, None)) is not None:
            db.delete(old)
            db.flush()
        db.add(
            EarlierInsight(
                key=key,
                kind=i.kind,
                horizon=i.horizon,
                feature_a=i.feature_a,
                feature_b=i.feature_b,
                lag=i.lag,
                method=i.method,
                effect=i.effect,
                p_adj=i.p_adj,
                n=i.n,
                strength=i.strength,
                sentence=i.sentence,
                details=i.details,
                first_seen=i.first_seen,
                last_held=i.last_seen or i.computed_at.date(),
                dropped_on=today,
            )
        )
    for e in earlier.values():
        if expired(e.dropped_on, today):
            db.delete(e)


@dataclass(frozen=True)
class RunResult:
    insights: int
    features: int


def run(db: Session, today: dt.date) -> RunResult:
    """Analyse the current feature table and replace the stored insights (caller commits)."""
    meta = load_meta(db)
    values = features.all_series(db)
    run_stats = RunStats()
    findings = analyse(values, meta, today, run_stats)
    previous = {_key(i): i for i in db.execute(sa.select(Insight)).scalars()}
    _keep_history(db, previous, {finding_key(f.kind, f.horizon, f.a, f.b, f.lag, f.method) for f in findings}, today)
    db.execute(sa.delete(Insight))
    for f in findings:
        before = previous.get(finding_key(f.kind, f.horizon, f.a, f.b, f.lag, f.method))
        db.add(
            Insight(
                kind=f.kind,
                horizon=f.horizon,
                feature_a=f.a,
                feature_b=f.b,
                lag=f.lag,
                method=f.method,
                effect=f.effect,
                p=f.p,
                p_adj=f.p_adj,
                n=f.n,
                n_a=f.n_a,
                n_b=f.n_b,
                strength=f.strength,
                score=f.score,
                sentence=sentence(f, meta),
                details=f.details,
                first_seen=(before.first_seen if before else None) or today,
                last_seen=today,
            )
        )
    summary = {
        "computed_at": now_utc().isoformat(),
        "features": run_stats.features,
        "eligible": run_stats.eligible,
        "tests": run_stats.tests,
        "reported": run_stats.reported,
        "min_days": MIN_PAIRED_DAYS,
        "fdr_q": FDR_Q,
    }
    setting = db.get(Setting, STATS_KEY)
    if setting is None:
        db.add(Setting(key=STATS_KEY, value=summary))
    else:
        setting.value = summary
    db.flush()
    log.info(
        "analysis: %d insights from %d tests over %d of %d features",
        len(findings),
        run_stats.tests,
        run_stats.eligible,
        run_stats.features,
    )
    return RunResult(len(findings), len(meta))
