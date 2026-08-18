"""Frames in, Stan data dicts out. Pure, and tested offline.

Censoring is the load-bearing idea here: a card never started is not a missing
latency but one that exceeded the day, and only the prep layer knows the day's
length — refill to drain — so it owns that translation.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

import polars as pl

from ..grid import COMPLETED, NEVER_APPEARED, NEVER_STARTED


def day_window_minutes(refill_at: time, drain_at: time) -> float:
    """Minutes from the refill to the next drain — the censoring horizon.

    The drain is on the *next* calendar day (04:00 follows 06:00), so the
    window wraps midnight: 06:00 → 04:00 is 22 hours.
    """
    anchor = datetime(2000, 1, 1)
    start = anchor.replace(hour=refill_at.hour, minute=refill_at.minute)
    end = anchor.replace(hour=drain_at.hour, minute=drain_at.minute)
    if end <= start:
        end += timedelta(days=1)
    return (end - start).total_seconds() / 60.0


def adherence_data(grid: pl.DataFrame, activities: list[str]) -> dict[str, Any]:
    """Per-mode trials and completions for the hierarchical model.

    `never_appeared` is excluded from trials: the refill not firing is a system
    fault, not a decision, and counting it as a miss blames the practice for
    the machinery.
    """
    observed = grid.filter(pl.col("outcome") != NEVER_APPEARED)
    n, k = [], []
    for activity in activities:
        mine = observed.filter(pl.col("activity") == activity)
        n.append(mine.height)
        k.append(mine.filter(pl.col("outcome") == COMPLETED).height)
    return {"M": len(activities), "n": n, "k": k}


def survival_data(grid: pl.DataFrame, activity: str, t_max: float) -> dict[str, Any]:
    """One mode's censored time-to-start.

    Started days contribute their observed latency; `never_started` days
    contribute the censoring bound. Latencies at or beyond the bound are
    clamped just inside it — a start recorded after the horizon is a clock
    artefact, not evidence of a longer day.
    """
    mine = grid.filter(
        (pl.col("activity") == activity) & (pl.col("outcome") != NEVER_APPEARED)
    )
    started = mine.filter(pl.col("minutes_to_start").is_not_null())
    t_obs = [min(float(t), t_max - 1.0) for t in started["minutes_to_start"].to_list()]
    censored = mine.filter(pl.col("outcome") == NEVER_STARTED).height
    return {
        "N_obs": len(t_obs),
        "N_cens": censored,
        "t_obs": t_obs,
        "t_max": t_max,
    }


def contrast_data(
    grid: pl.DataFrame, condition_mode: str, arm_completed: bool
) -> dict[str, Any]:
    """Completion of the *other* modes, on days a condition mode was done/missed.

    The generalisation of H3: two of these (arm_completed True/False) feed the
    beta-binomial per arm, and the posterior of the difference is the contrast.
    """
    observed = grid.filter(pl.col("outcome") != NEVER_APPEARED)
    condition = observed.filter(pl.col("activity") == condition_mode)
    completed_days = set(
        condition.filter(pl.col("outcome") == COMPLETED)["day"].to_list()
    )
    observed_days = set(condition["day"].to_list())
    days = completed_days if arm_completed else observed_days - completed_days
    others = observed.filter(
        pl.col("day").is_in(sorted(days)) & (pl.col("activity") != condition_mode)
    )
    return {
        "n": others.height,
        "k": others.filter(pl.col("outcome") == COMPLETED).height,
        "prior_a": 1.0,
        "prior_b": 1.0,
    }


def cascade_data(
    days: list[dict[str, Any]],
    window_days: int,
    y_field: str,
    history_field: str,
) -> dict[str, Any]:
    """Windowed counts against standardised cumulative history.

    The cascade doctrine: stages couple through cumulative intensities over
    long windows, never event lags. Windows are consecutive, oldest first.
    """
    ordered = sorted(days, key=lambda d: d["day"])
    windows: list[dict[str, float]] = []
    cumulative = 0.0
    for start in range(0, len(ordered), window_days):
        chunk = ordered[start : start + window_days]
        windows.append(
            {
                "y": float(sum(d.get(y_field) or 0 for d in chunk)),
                "exposure": float(len(chunk)),
                "history": cumulative,
            }
        )
        cumulative += float(sum(d.get(history_field) or 0 for d in chunk))
    histories = [w["history"] for w in windows]
    mean = sum(histories) / len(histories) if histories else 0.0
    spread = (
        (sum((h - mean) ** 2 for h in histories) / len(histories)) ** 0.5
        if histories
        else 1.0
    ) or 1.0
    return {
        "W": len(windows),
        "y": [int(w["y"]) for w in windows],
        "exposure_days": [w["exposure"] for w in windows],
        "cum_history": [(w["history"] - mean) / spread for w in windows],
    }
