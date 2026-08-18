"""The rolling Bayesian layer — Layer B around a Stan engine.

`prep` turns graph frames into Stan data dicts; `engine` runs a model and
gates it on its own diagnostics; `summarise` turns draws into posterior rows.
Priors live in the `.stan` files under `models/`, pre-registered.

A posterior is *visibility of uncertainty*: always shown, honestly wide. The
N-gates stop hiding and start annotating.
"""

from __future__ import annotations

from .engine import FitResult, run_model
from .prep import (
    adherence_data,
    cascade_data,
    contrast_data,
    day_window_minutes,
    survival_data,
)
from .summarise import prob_greatest, prob_threshold, summarise_draws

__all__ = [
    "FitResult",
    "adherence_data",
    "cascade_data",
    "contrast_data",
    "day_window_minutes",
    "prob_greatest",
    "prob_threshold",
    "run_model",
    "summarise_draws",
    "survival_data",
]
