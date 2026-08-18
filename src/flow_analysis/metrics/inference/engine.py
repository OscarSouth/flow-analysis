"""Run one Stan model, seed-pinned, and gate it on its own diagnostics.

The engine trusts nothing it cannot verify: R-hat, bulk ESS and divergences
ride out with every fit, and `trusted` is decided here — once, by fixed rule —
rather than by whoever happens to read the posterior later.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# Fixed for determinism: the same data must produce the same posterior rows.
SEED = 108
CHAINS = 4
WARMUP = 1000
SAMPLES = 1000

# The gate. R-hat above 1.01 means the chains disagree about where the
# posterior is; thin bulk ESS means the draws are too correlated to trust the
# quantiles; any divergence means the sampler hit geometry it could not follow.
RHAT_MAX = 1.01
ESS_MIN = 400.0

MODELS_DIR = Path(__file__).resolve().parents[4] / "models"


@dataclass(frozen=True)
class FitResult:
    """Draws plus the diagnostics that decide whether to believe them."""

    draws: dict[str, np.ndarray]
    rhat_max: float
    ess_min: float
    divergences: int
    trusted: bool


def run_model(model_name: str, data: dict[str, Any]) -> FitResult:
    """Compile (cached), sample (seed-pinned), gate.

    cmdstanpy caches the compiled executable beside the `.stan` file, so the
    first run of a session pays the compile and the rest are seconds.
    """
    from cmdstanpy import CmdStanModel

    model = CmdStanModel(stan_file=MODELS_DIR / f"{model_name}.stan")
    fit = model.sample(
        data=data,
        seed=SEED,
        chains=CHAINS,
        iter_warmup=WARMUP,
        iter_sampling=SAMPLES,
        show_progress=False,
        show_console=False,
    )

    summary = fit.summary()
    rhat_max = float(np.nanmax(summary["R_hat"].to_numpy()))
    ess_min = float(np.nanmin(summary["ESS_bulk"].to_numpy()))
    divergences = int(np.sum(fit.method_variables()["divergent__"]))

    draws = {
        name: np.asarray(fit.stan_variable(name)) for name in fit.metadata.stan_vars
    }
    return FitResult(
        draws=draws,
        rhat_max=rhat_max,
        ess_min=ess_min,
        divergences=divergences,
        trusted=(rhat_max < RHAT_MAX and ess_min > ESS_MIN and divergences == 0),
    )
