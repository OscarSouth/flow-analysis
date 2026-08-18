"""Draws in, posterior rows out. Pure numpy, tested offline with fixed draws."""

from __future__ import annotations

from typing import Any

import numpy as np

# Central 90% by default: the repo reports honest width, not significance.
CI_LOW = 5.0
CI_HIGH = 95.0


def summarise_draws(draws: np.ndarray) -> dict[str, float]:
    """Mean, median and central credible interval of one quantity's draws."""
    flat = np.asarray(draws, dtype=float).ravel()
    return {
        "mean": float(np.mean(flat)),
        "median": float(np.median(flat)),
        "ci_low": float(np.percentile(flat, CI_LOW)),
        "ci_high": float(np.percentile(flat, CI_HIGH)),
    }


def prob_threshold(draws: np.ndarray, threshold: float) -> float:
    """P(quantity > threshold) — the decision form the criteria use."""
    flat = np.asarray(draws, dtype=float).ravel()
    return float(np.mean(flat > threshold))


def prob_greatest(
    draws_by_name: dict[str, np.ndarray], margin: float = 1.0
) -> dict[str, float]:
    """P(each named quantity exceeds every other by `margin`), per draw.

    `margin=1.2` asks for a 20% lead over the runner-up — the pre-registered
    effect-size bars, restated as posterior probabilities.
    """
    names = sorted(draws_by_name)
    stacked = np.vstack(
        [np.asarray(draws_by_name[n], dtype=float).ravel() for n in names]
    )
    out: dict[str, float] = {}
    for index, name in enumerate(names):
        others = np.delete(stacked, index, axis=0)
        out[name] = float(np.mean(stacked[index] > margin * others.max(axis=0)))
    return out


def as_row(
    measure: str,
    day: str,
    summary: dict[str, float],
    fit_diagnostics: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    """One (:Fct:Posterior) row: the summary plus the diagnostics that gate it."""
    return {
        "measure": measure,
        "day": day,
        "model": model,
        **summary,
        **fit_diagnostics,
    }
