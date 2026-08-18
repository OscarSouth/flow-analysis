"""Tiered events, bucketed into flow days.

Trello records that the practice ran. It cannot record whether anything came of
it — and the gap between those two is where `adherence without production`
hides, which reads as total success on the board. This is the module that makes
the gap measurable, by counting only rows of one tier per day.

Layer B: `rows` is always passed in. The store is the caller's business, which
is what lets every function here run against fabricated rows without touching
`data/` — and what will let a Dagster asset feed it from the IO manager.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

import polars as pl

from ..tiers import TIER_PRODUCTION, TIER_RECEPTION, row_tier
from ..util import parse_iso
from .calendar import flow_day

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..config import Config


def _by_day(
    cfg: Config, tier: str, signals: Sequence[dict[str, Any]]
) -> dict[str, int]:
    """Bucket one tier's events into flow days.

    Uses the same 04:00 boundary as the practice, so a post written at 01:00
    counts toward the day it belonged to — matching how the board behaves.
    """
    counts: Counter[str] = Counter()
    for row in signals:
        if row_tier(row) != tier:
            continue
        # Counter and window rows carry no event time; they are levels, not
        # occurrences, and belong to the snapshot surfaces rather than here.
        created = row.get("created_at")
        if not created:
            continue
        day = flow_day(parse_iso(created), cfg.timezone, cfg.drain_at)
        counts[day.isoformat()] += 1
    return dict(counts)


def production_from_signals(signals: pl.DataFrame) -> dict[str, int]:
    """Production-tier events per flow day, from a staged signals frame.

    The frame's `flow_day` was computed at staging by the same `flow_day`
    function used everywhere else, so this is the one boundary implementation
    seen through a second door — not a second implementation.
    """
    if signals.is_empty():
        return {}
    counted = (
        signals.filter(
            (pl.col("tier") == TIER_PRODUCTION) & pl.col("flow_day").is_not_null()
        )
        .group_by(pl.col("flow_day").alias("day"))
        .agg(n=pl.len())
    )
    return {row["day"]: row["n"] for row in counted.to_dicts()}


def production_by_day(cfg: Config, signals: Sequence[dict[str, Any]]) -> dict[str, int]:
    """What you put into the world, per flow day.

    Filters to the production tier. This is the guard that keeps
    `adherence_without_production` and `aberration` honest once reception rows
    share the same file — without it, someone else starring the repo would read
    as your own output.
    """
    return _by_day(cfg, TIER_PRODUCTION, signals)


def reception_by_day(cfg: Config, signals: Sequence[dict[str, Any]]) -> dict[str, int]:
    """What came back, per flow day.

    Deliberately never correlated against adherence at short lags: reception
    answers to promotion and to work shipped long ago, not to whether you did
    Absorb on Tuesday. It is reported as level and cumulative total.
    """
    return _by_day(cfg, TIER_RECEPTION, signals)
