"""DB side of the engine: read ``daily_features``, analyse, replace ``insights``."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .. import features, goodday
from ..auth import now_utc
from ..models import FeatureDef, Insight, Setting
from .constants import FDR_Q, MIN_PAIRED_DAYS
from .engine import FeatureMeta, RunStats, analyse
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
    db.execute(sa.delete(Insight))
    for f in findings:
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
