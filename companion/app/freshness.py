"""Is the Companion showing everything there is? (the notice on Overview)

Three states, from two facts: the newest payload HealthLog received (id and time), and the newest one the
Companion's last refresh started from.

- ``current``: the Companion has everything HealthLog received, and HealthLog heard from the phone recently.
  Nothing is shown.
- ``behind``: HealthLog holds payloads the Companion hasn't processed. The 15-minute check
  (``jobs.refresh_if_new``) catches up on its own; Overview offers *Refresh now* to skip the wait.
- ``silent``: nothing has reached HealthLog for ``SILENT_AFTER``. A refresh can't help: the data has to come
  from Health Auto Export on the phone.

``behind`` wins over ``silent``: when there is something to process, processing it is the useful step.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from . import jobs, upstream

# Health Auto Export sends every 2-3 hours when it runs; twice that without a payload means it stopped.
SILENT_AFTER = dt.timedelta(hours=6)

State = Literal["current", "behind", "silent"]


@dataclass(frozen=True)
class Freshness:
    state: State
    last_received: dt.datetime | None  # when HealthLog last received anything (None: never)

    @property
    def show(self) -> bool:
        return self.state != "current"


def classify(newest: tuple[int, dt.datetime] | None, seen: int, now: dt.datetime) -> Freshness:
    """Pure: the state from HealthLog's newest payload ``(id, received_at)``, the refreshed-from id and now."""
    if newest is None:
        return Freshness("silent", None)
    newest_id, received = newest
    if newest_id > seen:
        return Freshness("behind", received)
    if now - received >= SILENT_AFTER:
        return Freshness("silent", received)
    return Freshness("current", received)


def load(db: Session, now: dt.datetime) -> Freshness:
    return classify(upstream.newest_payload(db), jobs.seen_payload(db), now)
