"""The ``companion-jobs`` process: scheduled work, separate from the web process.

M1 runs one job: the nightly read-contract check at 04:10 local time, after
HealthLog's 03:30 analysis and before its 04:30 backup. The analysis jobs
(M2+) join it here.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from . import upstream
from .config import get_settings
from .db import session_scope

log = logging.getLogger("companion.jobs")


def contract_check() -> int:
    """Returns the number of contract problems (logged)."""
    with session_scope() as db:
        problems = upstream.check_upstream(db)
    for problem in problems:
        log.warning("upstream contract: %s", problem)
    log.info("nightly contract check: %d problem(s)", len(problems))
    return len(problems)


def run() -> int:
    settings = get_settings()
    scheduler = BlockingScheduler(timezone=settings.zone)
    scheduler.add_job(contract_check, CronTrigger(hour=4, minute=10, timezone=settings.zone), id="contract_check")
    log.info("jobs scheduler started (TZ=%s)", settings.tz)
    contract_check()
    scheduler.start()
    return 0
