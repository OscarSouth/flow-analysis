"""The rolling posterior snapshot — uncertainty as a first-class fact.

One row per (measure, flow day): the posterior summary plus the diagnostics
that decide whether to believe it. Rows accumulate daily, which is what makes
the evolving-distribution view (ridgelines) a graph query rather than a re-fit.

The all-Bayes decision (2026-08-18): the three publicly pre-registered
hypotheses are judged here, as posterior probabilities against their
pre-registered margins, with a three-way verdict — supported (p ≥ 0.90),
not supported (p ≤ 0.10), inconclusive between. Criteria in
docs/06-diagnostics.md.
"""

# Dagster resolves resource and context annotations at run time, so this module
# deliberately does without `from __future__ import annotations`.

import json
from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl
from dagster import AssetExecutionContext, asset

from ..metrics.calendar import flow_day
from ..metrics.diagnostics import MIN_DAYS_RATE, MIN_OBS_LATENCY
from ..metrics.grid import NEVER_APPEARED, NEVER_STARTED
from ..metrics.inference import (
    adherence_data,
    cascade_data,
    contrast_data,
    day_window_minutes,
    prob_greatest,
    prob_threshold,
    run_model,
    summarise_draws,
    survival_data,
)
from ..resources import FlowConfigResource

GROUP = "fct"

# Decision thresholds, pre-registered 2026-08-18. A claim is supported when its
# posterior probability (including the published effect margin) clears the
# upper bar, refuted below the lower, and inconclusive between.
P_SUPPORTED = 0.90
P_REFUTED = 0.10
LEAD_MARGIN = 1.2  # the published 20% lead over the runner-up
H3_GAP = 0.10  # the published ten points of completion rate

POSTERIOR_CYPHER = """
UNWIND $rows AS row
MERGE (p:Fct:Posterior {measure: row.measure, day: row.day})
SET p += row
"""

POSTERIOR_LOAD = """
MATCH (p:Fct:Posterior)
RETURN p.measure AS measure, p.day AS day, p.model AS model,
       p.mean AS mean, p.median AS median,
       p.ci_low AS ci_low, p.ci_high AS ci_high,
       p.probability AS probability, p.verdict AS verdict,
       p.rhat_max AS rhat_max, p.ess_min AS ess_min,
       p.divergences AS divergences, p.trusted AS trusted,
       p.extra_json AS extra_json
ORDER BY p.day, p.measure
"""

SCHEMA = pl.Schema(
    {
        "measure": pl.Utf8,
        "day": pl.Utf8,
        "model": pl.Utf8,
        "mean": pl.Float64,
        "median": pl.Float64,
        "ci_low": pl.Float64,
        "ci_high": pl.Float64,
        "probability": pl.Float64,
        "verdict": pl.Utf8,
        "rhat_max": pl.Float64,
        "ess_min": pl.Float64,
        "divergences": pl.Int64,
        "trusted": pl.Boolean,
        "extra_json": pl.Utf8,
    }
)


def _verdict(probability: float, n: int, needs: int, trusted: bool) -> str:
    """Three-way verdict, gated exactly as everything else is gated.

    The posterior is always stored (visibility); the verdict is inference and
    waits for N. Without the gate, pooling shrinkage at small N drives every
    mode's lead-probability toward zero, and absence of evidence would read as
    refutation — the exact misreading the three-way scheme exists to prevent.
    A fit the sampler itself distrusts cannot produce a verdict either.
    """
    if n < needs or not trusted:
        return "not testable yet"
    if probability >= P_SUPPORTED:
        return "supported"
    if probability <= P_REFUTED:
        return "not supported"
    return "inconclusive"


@asset(
    group_name=GROUP,
    io_manager_key="graph_io_manager",
    metadata={"cypher_template": POSTERIOR_CYPHER, "load_cypher": POSTERIOR_LOAD},
    description="Daily posterior snapshots, with diagnostics and verdicts.",
)
def fct_posteriors(
    context: AssetExecutionContext,
    flow_config: FlowConfigResource,
    stg_flow_grid: pl.DataFrame,
    enr_day_adherence: pl.DataFrame,
) -> pl.DataFrame:
    """Fit the pre-registered models over the staged grid, snapshot today.

    Every fit is seed-pinned; every row carries R-hat, bulk ESS and divergence
    count, and `trusted` is decided by the engine's fixed gate. An untrusted
    posterior is stored — it is a fact about the sampler meeting this data —
    but must never be read as a result.
    """
    cfg = flow_config.load()
    activities = list(cfg.activities)
    today = flow_day(datetime.now(UTC), cfg.timezone, cfg.drain_at).isoformat()

    rows: list[dict[str, Any]] = []

    def emit(
        measure: str,
        model: str,
        fit: Any,  # noqa: ANN401 - FitResult, kept loose for the closure
        summary: dict[str, float],
        probability: float | None = None,
        verdict: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        rows.append(
            {
                "measure": measure,
                "day": today,
                "model": model,
                "mean": summary.get("mean"),
                "median": summary.get("median"),
                "ci_low": summary.get("ci_low"),
                "ci_high": summary.get("ci_high"),
                "probability": probability,
                "verdict": verdict,
                "rhat_max": fit.rhat_max,
                "ess_min": fit.ess_min,
                "divergences": fit.divergences,
                "trusted": fit.trusted,
                "extra_json": json.dumps(extra, default=str) if extra else None,
            }
        )

    # --- adherence: hierarchical completion, one fit, six measures ----------
    completion = adherence_data(stg_flow_grid, activities)
    fit = run_model("adherence_hierarchical", completion)
    emit(
        "adherence:practice",
        "adherence_hierarchical",
        fit,
        summarise_draws(fit.draws["mu"]),
    )
    for index, activity in enumerate(activities):
        emit(
            f"adherence:{activity}",
            "adherence_hierarchical",
            fit,
            summarise_draws(fit.draws["theta"][:, index]),
        )

    # --- H1: Train is the most frequent never-started -----------------------
    # The same hierarchical model over never-started counts: the claim is about
    # rates of a failure mode, and pooling keeps a two-count lead honest.
    never = {
        "M": completion["M"],
        "n": completion["n"],
        "k": [
            stg_flow_grid.filter(
                (pl.col("activity") == a) & (pl.col("outcome") == NEVER_STARTED)
            ).height
            for a in activities
        ],
    }
    fit = run_model("adherence_hierarchical", never)
    lead = prob_greatest(
        {a: fit.draws["theta"][:, i] for i, a in enumerate(activities)},
        margin=LEAD_MARGIN,
    )
    observed_days = int(
        stg_flow_grid.filter(pl.col("outcome") != NEVER_APPEARED)["day"].n_unique()
    )
    p_h1 = lead.get("Train", 0.0)
    emit(
        "prereg:h1_train_most_never_started",
        "adherence_hierarchical",
        fit,
        summarise_draws(fit.draws["theta"][:, activities.index("Train")])
        if "Train" in activities
        else {},
        probability=p_h1,
        verdict=_verdict(p_h1, observed_days, MIN_DAYS_RATE, fit.trusted),
        extra={"p_lead_by_mode": lead, "margin": LEAD_MARGIN},
    )

    # --- latency survival per mode, and H2 ----------------------------------
    t_max = day_window_minutes(cfg.refill_at, cfg.drain_at)
    median_draws: dict[str, np.ndarray] = {}
    survival_trusted = True
    min_started = 10**9
    for activity in activities:
        survival = survival_data(stg_flow_grid, activity, t_max)
        if survival["N_obs"] + survival["N_cens"] == 0:
            continue
        fit = run_model("latency_survival", survival)
        survival_trusted = survival_trusted and fit.trusted
        min_started = min(min_started, survival["N_obs"])
        median_draws[activity] = fit.draws["median_minutes"]
        emit(
            f"latency_median:{activity}",
            "latency_survival",
            fit,
            summarise_draws(fit.draws["median_minutes"]),
        )
        emit(
            f"p_never_started:{activity}",
            "latency_survival",
            fit,
            summarise_draws(fit.draws["p_never_started"]),
        )
    if "Express" in median_draws and len(median_draws) == len(activities):
        lead = prob_greatest(median_draws, margin=LEAD_MARGIN)
        p_h2 = lead["Express"]
        emit(
            "prereg:h2_express_slowest_to_start",
            "latency_survival",
            fit,
            summarise_draws(median_draws["Express"]),
            probability=p_h2,
            verdict=_verdict(p_h2, min_started, MIN_OBS_LATENCY, survival_trusted),
            extra={"p_lead_by_mode": lead, "margin": LEAD_MARGIN},
        )

    # --- H3: days Write is missed depress the others -------------------------
    done = contrast_data(stg_flow_grid, "Write", arm_completed=True)
    missed = contrast_data(stg_flow_grid, "Write", arm_completed=False)
    if done["n"] > 0 and missed["n"] > 0:
        fit_done = run_model("beta_binomial", done)
        fit_missed = run_model("beta_binomial", missed)
        diff = fit_done.draws["theta"] - fit_missed.draws["theta"]
        p_h3 = prob_threshold(diff, H3_GAP)
        h3_days = int(
            stg_flow_grid.filter(pl.col("outcome") != NEVER_APPEARED)["day"].n_unique()
        )
        combined = type(fit_done)(
            draws={},
            rhat_max=max(fit_done.rhat_max, fit_missed.rhat_max),
            ess_min=min(fit_done.ess_min, fit_missed.ess_min),
            divergences=fit_done.divergences + fit_missed.divergences,
            trusted=fit_done.trusted and fit_missed.trusted,
        )
        emit(
            "prereg:h3_write_carries_the_others",
            "beta_binomial",
            combined,
            summarise_draws(diff),
            probability=p_h3,
            verdict=_verdict(p_h3, h3_days, MIN_DAYS_RATE, combined.trusted),
            extra={"gap_bar": H3_GAP},
        )

    # --- the cascade: production windows ~ cumulative commitment ------------
    days = enr_day_adherence.to_dicts()
    cascade = cascade_data(days, 28, y_field="production", history_field="completed")
    if cascade["W"] >= 3:
        fit = run_model("cumulative_cascade", cascade)
        emit(
            "cascade:production~commitment",
            "cumulative_cascade",
            fit,
            summarise_draws(fit.draws["beta1"]),
            probability=prob_threshold(fit.draws["beta1"], 0.0),
            extra={"windows": cascade["W"], "confounded": True},
        )

    untrusted = [r["measure"] for r in rows if not r["trusted"]]
    context.log.info(
        "%d posterior row(s) for %s; %d untrusted: %s",
        len(rows),
        today,
        len(untrusted),
        ", ".join(untrusted) or "none",
    )
    return pl.DataFrame(rows, schema=SCHEMA)
