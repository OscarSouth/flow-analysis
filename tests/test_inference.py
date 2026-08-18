"""The inference layer's pure parts — prep, summarise, verdict gating.

Everything here runs offline: the frames are constructed, the draws are fixed
arrays. The sampler itself is exercised by `tests/test_stan_integration.py`.
"""

from __future__ import annotations

from datetime import time

import numpy as np
import polars as pl

from flow_analysis.assets.posteriors import _verdict
from flow_analysis.metrics.inference import (
    adherence_data,
    cascade_data,
    contrast_data,
    day_window_minutes,
    prob_greatest,
    prob_threshold,
    summarise_draws,
)

GRID_SCHEMA = {
    "day": pl.Utf8,
    "activity": pl.Utf8,
    "outcome": pl.Utf8,
    "minutes_to_start": pl.Float64,
}


def _grid(rows: list[tuple[str, str, str, float | None]]) -> pl.DataFrame:
    return pl.DataFrame(
        [dict(zip(GRID_SCHEMA, row, strict=True)) for row in rows],
        schema=GRID_SCHEMA,
    )


def test_the_day_window_wraps_midnight():
    """06:00 refill to 04:00 drain is 22 hours, not minus two."""
    assert day_window_minutes(time(6, 0), time(4, 0)) == 1320.0


def test_adherence_counts_exclude_never_appeared():
    """The refill not firing is a system fault, not a missed day."""
    grid = _grid(
        [
            ("2026-08-16", "Write", "completed", 10.0),
            ("2026-08-17", "Write", "never_appeared", None),
            ("2026-08-18", "Write", "never_started", None),
        ]
    )
    data = adherence_data(grid, ["Write"])
    assert data == {"M": 1, "n": [2], "k": [1]}


def test_survival_censors_the_never_started():
    """A card never started is a latency that exceeded the day, not a gap."""
    grid = _grid(
        [
            ("2026-08-16", "Train", "completed", 300.0),
            ("2026-08-17", "Train", "never_started", None),
            ("2026-08-18", "Train", "never_appeared", None),
        ]
    )
    from flow_analysis.metrics.inference import survival_data

    data = survival_data(grid, "Train", t_max=1320.0)
    assert data["N_obs"] == 1
    assert data["N_cens"] == 1  # never_appeared excluded entirely
    assert data["t_obs"] == [300.0]


def test_survival_clamps_latencies_at_the_horizon():
    """A start recorded past the drain is a clock artefact, not a longer day."""
    from flow_analysis.metrics.inference import survival_data

    grid = _grid([("2026-08-16", "Train", "completed", 5000.0)])
    data = survival_data(grid, "Train", t_max=1320.0)
    assert data["t_obs"] == [1319.0]


def test_contrast_arms_split_on_the_condition_mode():
    grid = _grid(
        [
            ("2026-08-16", "Write", "completed", 1.0),
            ("2026-08-16", "Train", "completed", 1.0),
            ("2026-08-16", "Absorb", "never_started", None),
            ("2026-08-17", "Write", "never_started", None),
            ("2026-08-17", "Train", "never_started", None),
        ]
    )
    done = contrast_data(grid, "Write", arm_completed=True)
    missed = contrast_data(grid, "Write", arm_completed=False)
    assert (done["n"], done["k"]) == (2, 1)  # Train + Absorb on the done day
    assert (missed["n"], missed["k"]) == (1, 0)  # Train on the missed day


def test_cascade_windows_carry_cumulative_history():
    """Window w's history is everything BEFORE it — never its own events."""
    days = [
        {"day": f"2026-08-{d:02d}", "production": 1, "completed": 2}
        for d in range(1, 9)
    ]
    data = cascade_data(
        days, window_days=4, y_field="production", history_field="completed"
    )
    assert data["W"] == 2
    assert data["y"] == [4, 4]
    # first window has zero history; second has the first's 8 completions —
    # standardised, so equal magnitudes, opposite signs
    assert data["cum_history"][0] == -data["cum_history"][1]


def test_summaries_are_plain_quantiles():
    draws = np.linspace(0.0, 1.0, 10001)
    summary = summarise_draws(draws)
    assert abs(summary["mean"] - 0.5) < 1e-9
    assert abs(summary["ci_low"] - 0.05) < 1e-3
    assert abs(summary["ci_high"] - 0.95) < 1e-3


def test_prob_greatest_demands_the_margin():
    """A 20% lead bar means a 10% leader scores zero, not 'nearly'."""
    draws = {
        "Train": np.full(1000, 0.55),
        "Write": np.full(1000, 0.50),
    }
    lead = prob_greatest(draws, margin=1.2)
    assert lead["Train"] == 0.0  # 0.55 < 1.2 * 0.50
    assert prob_greatest(draws, margin=1.0)["Train"] == 1.0


def test_prob_threshold_is_the_decision_form():
    draws = np.array([0.05, 0.15, 0.25, 0.35])
    assert prob_threshold(draws, 0.10) == 0.75


# --- verdict gating ------------------------------------------------------------


def test_verdicts_wait_for_n():
    """Absence of evidence at small N must never read as refutation."""
    assert _verdict(0.01, n=2, needs=14, trusted=True) == "not testable yet"


def test_verdicts_wait_for_the_sampler():
    assert _verdict(0.99, n=100, needs=14, trusted=False) == "not testable yet"


def test_verdicts_are_three_way_once_gated():
    assert _verdict(0.95, n=20, needs=14, trusted=True) == "supported"
    assert _verdict(0.05, n=20, needs=14, trusted=True) == "not supported"
    assert _verdict(0.50, n=20, needs=14, trusted=True) == "inconclusive"
