"""The rolling posterior snapshot — uncertainty as a first-class fact.

One row per (measure, flow day): the posterior summary plus the diagnostics
that decide whether to believe it. Rows accumulate daily, which is what makes
the evolving-distribution view (ridgelines) a graph query rather than a re-fit.

The all-Bayes decision (2026-08-18) and the contract registry (2026-08-19):
the statistical contracts in `metrics/contracts.py` are judged here — each
over its own trailing window — as posterior probabilities against their
pre-registered margins, with a four-way verdict: supported (p ≥ 0.90), not
supported (p ≤ 0.10), inconclusive between, not testable yet below the gate
or on an untrusted fit. Criteria in docs/06-diagnostics.md. Deterministic
contracts (c6-c8) are judged in `metrics/diagnostics.py`; the base
posteriors (adherence, latency, cascade) remain full-history.
"""

# Dagster resolves resource and context annotations at run time, so this module
# deliberately does without `from __future__ import annotations`.

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
from dagster import AssetExecutionContext, asset

from .. import store
from ..io.streams import RawStream
from ..metrics.calendar import flow_day
from ..metrics.contracts import (
    GAP_PATTERN,
    GAP_WRITE,
    LEAD_MARGIN,
    by_key,
)
from ..metrics.grid import ABANDONED, NEVER_APPEARED, NEVER_STARTED
from ..metrics.inference import (
    adherence_data,
    cascade_data,
    completion_arm,
    contrast_data,
    day_window_minutes,
    outcome_counts,
    prob_any_leader,
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
# upper bar, refuted below the lower, and inconclusive between. Margins live
# in the contract registry — one source.
P_SUPPORTED = 0.90
P_REFUTED = 0.10

# One month in days, for the c9 exposure. The Julian-average constant rather
# than 30: a 90-day window is 2.957 months, and rounding the exposure moves
# the posterior rate for free.
DAYS_PER_MONTH = 30.44

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
    """Four-way verdict, gated exactly as everything else is gated.

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

    # --- latency survival per mode -------------------------------------------
    t_max = day_window_minutes(cfg.refill_at, cfg.drain_at)
    for activity in activities:
        survival = survival_data(stg_flow_grid, activity, t_max)
        if survival["N_obs"] + survival["N_cens"] == 0:
            continue
        fit = run_model("latency_survival", survival)
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

    # --- the statistical contracts, each over its own trailing window --------
    # The registry (metrics/contracts.py) is the source of windows, gates and
    # margins; this section only supplies the data and the model per contract.

    def windowed(days: int | None) -> pl.DataFrame:
        if days is None:
            return stg_flow_grid
        floor = (
            (datetime.fromisoformat(today) - timedelta(days=days)).date().isoformat()
        )
        return stg_flow_grid.filter(pl.col("day") > floor)

    def observed_days(frame: pl.DataFrame) -> int:
        return int(frame.filter(pl.col("outcome") != NEVER_APPEARED)["day"].n_unique())

    # c1/c2 — a persistent leader in a failure outcome (any mode, per draw)
    for key, outcome in (
        ("c1_allocation_failure", NEVER_STARTED),
        ("c2_capacity_failure", ABANDONED),
    ):
        contract = by_key(key)
        frame = windowed(contract.window_days)
        counts = outcome_counts(frame, activities, outcome)
        fit = run_model("adherence_hierarchical", counts)
        draws_by_mode = {a: fit.draws["theta"][:, i] for i, a in enumerate(activities)}
        p_any = prob_any_leader(draws_by_mode, margin=LEAD_MARGIN)
        lead = prob_greatest(draws_by_mode, margin=LEAD_MARGIN)
        n = observed_days(frame)
        emit(
            contract.measure,
            "adherence_hierarchical",
            fit,
            summarise_draws(fit.draws["mu"]),
            probability=p_any,
            verdict=_verdict(p_any, n, contract.needs, fit.trusted),
            extra={
                "p_lead_by_mode": lead,
                "margin": LEAD_MARGIN,
                "window_days": contract.window_days,
                "outcome": outcome,
            },
        )

    # c3/c4 — completion divergence between a named pair of modes
    for key, high, low in (
        ("c3_correct_and_dead", "Train", "Express"),
        ("c4_well_running_dry", "Reveal", "Absorb"),
    ):
        contract = by_key(key)
        frame = windowed(contract.window_days)
        arm_high = completion_arm(frame, high)
        arm_low = completion_arm(frame, low)
        if arm_high["n"] == 0 or arm_low["n"] == 0:
            continue
        fit_high = run_model("beta_binomial", arm_high)
        fit_low = run_model("beta_binomial", arm_low)
        diff = fit_high.draws["theta"] - fit_low.draws["theta"]
        p_gap = prob_threshold(diff, GAP_PATTERN)
        combined = type(fit_high)(
            draws={},
            rhat_max=max(fit_high.rhat_max, fit_low.rhat_max),
            ess_min=min(fit_high.ess_min, fit_low.ess_min),
            divergences=fit_high.divergences + fit_low.divergences,
            trusted=fit_high.trusted and fit_low.trusted,
        )
        n = observed_days(frame)
        emit(
            contract.measure,
            "beta_binomial",
            combined,
            summarise_draws(diff),
            probability=p_gap,
            verdict=_verdict(p_gap, n, contract.needs, combined.trusted),
            extra={
                "gap_bar": GAP_PATTERN,
                "high": high,
                "low": low,
                "window_days": contract.window_days,
            },
        )

    # c5 — Write-missed days depress the other four (the surviving old H3)
    contract = by_key("c5_write_carries_the_others")
    frame = windowed(contract.window_days)
    done = contrast_data(frame, "Write", arm_completed=True)
    missed = contrast_data(frame, "Write", arm_completed=False)
    if done["n"] > 0 and missed["n"] > 0:
        fit_done = run_model("beta_binomial", done)
        fit_missed = run_model("beta_binomial", missed)
        diff = fit_done.draws["theta"] - fit_missed.draws["theta"]
        p_c5 = prob_threshold(diff, GAP_WRITE)
        combined = type(fit_done)(
            draws={},
            rhat_max=max(fit_done.rhat_max, fit_missed.rhat_max),
            ess_min=min(fit_done.ess_min, fit_missed.ess_min),
            divergences=fit_done.divergences + fit_missed.divergences,
            trusted=fit_done.trusted and fit_missed.trusted,
        )
        emit(
            contract.measure,
            "beta_binomial",
            combined,
            summarise_draws(diff),
            probability=p_c5,
            verdict=_verdict(
                p_c5, observed_days(frame), contract.needs, combined.trusted
            ),
            extra={"gap_bar": GAP_WRITE, "window_days": contract.window_days},
        )

    # c9 — the publication-cadence floor, rolling and indefinite. Exposure is
    # the flow-era days actually inside the window, so early on the model sees
    # a short window honestly rather than 90 days of imagined silence.
    contract = by_key("c9_publication_rate")
    if cfg.start_date is not None:
        era_days = (datetime.fromisoformat(today).date() - cfg.start_date).days + 1
        window = contract.window_days or 90
        floor = (
            (datetime.fromisoformat(today) - timedelta(days=window)).date().isoformat()
        )
        in_window = enr_day_adherence.filter(
            (pl.col("day") > floor) & (pl.col("day") >= cfg.start_date.isoformat())
        )
        events = int(
            in_window["production"].fill_null(0).sum() if in_window.height else 0
        )
        exposure_days = min(era_days, window)
        fit = run_model(
            "poisson_rate",
            {
                "y": events,
                "exposure_months": max(exposure_days, 1) / DAYS_PER_MONTH,
                "prior_a": 2.0,
                "prior_b": 2.0,
            },
        )
        p_floor = prob_threshold(fit.draws["lambda"], 1.0)
        emit(
            contract.measure,
            "poisson_rate",
            fit,
            summarise_draws(fit.draws["lambda"]),
            probability=p_floor,
            verdict=_verdict(p_floor, era_days, contract.needs, fit.trusted),
            extra={
                "events": events,
                "exposure_days": exposure_days,
                "window_days": window,
            },
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

    # --- replay the archived history ------------------------------------------
    # The graph's snapshot history is derived, and each run fits only today —
    # without this replay a purge-and-rebuild would destroy every prior day
    # (it did, on 2026-08-19). The archive (data/posteriors.jsonl, written by
    # raw_posterior_snapshots downstream) is the durable record; re-emitting
    # its latest state per (measure, day) makes the MERGE reconstruct history
    # on every run, idempotently.
    columns = list(SCHEMA.keys())
    history = [
        {key: row.get(key) for key in columns}
        for row in store.latest_posteriors(store.load_posteriors())
        if row.get("day") != today
    ]
    if history:
        context.log.info("replayed %d archived snapshot row(s)", len(history))
    return pl.DataFrame(history + rows, schema=SCHEMA)


@asset(
    group_name=GROUP,
    metadata={"jsonl_stream": "posteriors"},
    description="Archive of posterior snapshots — what makes history rebuildable.",
)
def raw_posterior_snapshots(
    context: AssetExecutionContext, fct_posteriors: pl.DataFrame
) -> RawStream:
    """Append every snapshot state to the append-only archive.

    Ids are content hashes (timestamp excluded), so replayed history and an
    unchanged same-day re-fit dedupe to nothing, while a re-fit on new data
    lands as a new state. `store.latest_posteriors` resolves the current
    state per (measure, day) exactly the way the graph's MERGE does.
    """
    captured_at = datetime.now(UTC).isoformat()
    rows = [
        {"id": store.posterior_id(row), "captured_at": captured_at, **row}
        for row in fct_posteriors.to_dicts()
    ]
    context.log.info("snapshotting %d posterior row(s) to the archive", len(rows))
    return RawStream(rows=rows)
