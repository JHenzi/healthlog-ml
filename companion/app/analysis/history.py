"""Which findings carry over between runs, which dropped out and which came back (roadmap B17, pure).

Presentation only: nothing here feeds the analysis or its FDR family (R8). A finding is "the same" across runs
when its kind, horizon, pair, lag and method match; its numbers may move.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass

KEEP_DAYS = 90  # an earlier discovery is listed this long after it dropped out


def finding_key(kind: str, horizon: str, a: str, b: str | None, lag: int | None, method: str) -> str:
    return "|".join((kind, horizon, a, b or "", "" if lag is None else str(lag), method))


@dataclass(frozen=True)
class Diff:
    dropped: frozenset[str]  # reported last run, not this one
    back: frozenset[str]  # listed as earlier, reported again


def diff(previous: Iterable[str], current: Iterable[str], earlier: Iterable[str]) -> Diff:
    now = frozenset(current)
    return Diff(frozenset(previous) - now, frozenset(earlier) & now)


def expired(dropped_on: dt.date, today: dt.date) -> bool:
    return (today - dropped_on).days > KEEP_DAYS
