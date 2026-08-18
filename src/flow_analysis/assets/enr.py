"""Enrichment — what one row cannot know on its own.

Per-row derivations (latency, pull rank, interleaving, failure kind) are already
computed by the fold and stored on `(:Stg:FlowRow)`, so recomputing them here
would be a second implementation of the same thing. What belongs at this layer is
what needs the *other* rows: a day's adherence across all five modes, set beside
what that day produced.

That pairing is the one the analysis keeps coming back to — high adherence with
no output is `adherence_without_production`, the measure that detects quiet
stagnation — and having it as a node makes it a Cypher question rather than a
Python script.
"""

# Dagster resolves resource and context annotations at run time, so this module
# deliberately does without `from __future__ import annotations`.

import polars as pl
from dagster import AssetExecutionContext, asset

from ..metrics.grid import COMPLETED, NEVER_APPEARED

GROUP = "enr"

DAY_ADHERENCE_CYPHER = """
UNWIND $rows AS row
MATCH (d:Dim:Day {date: row.day})
SET d:Enr,
    d.completed = row.completed,
    d.observed = row.observed,
    d.adherence = row.adherence,
    d.production = row.production,
    d.perfect = row.perfect
"""

DAY_ADHERENCE_LOAD = """
MATCH (d:Enr:Day)
RETURN d.date AS day, d.completed AS completed, d.observed AS observed,
       d.adherence AS adherence, d.production AS production, d.perfect AS perfect
ORDER BY d.date
"""


@asset(
    group_name=GROUP,
    io_manager_key="graph_io_manager",
    metadata={
        "cypher_template": DAY_ADHERENCE_CYPHER,
        "load_cypher": DAY_ADHERENCE_LOAD,
    },
    description="Per-day adherence across the five modes, beside that day's output.",
)
def enr_day_adherence(
    context: AssetExecutionContext,
    stg_flow_grid: pl.DataFrame,
    stg_signals: pl.DataFrame,
) -> pl.DataFrame:
    """Completion rate per flow day, with production counted beside it.

    `never_appeared` rows are excluded from the denominator: the refill rule not
    firing is a system fault, not a decision not to work, and counting it as a
    miss would blame the practice for the machinery.

    Production is the **production tier only**. Without that filter a stranger's
    star would count as your own output, which is exactly the confusion this
    pairing exists to detect.

    Writes onto the existing `(:Dim:Day)` nodes rather than creating a parallel
    set — a day is one thing, and the `Enr` label marks that it now carries
    derived properties too.
    """
    if stg_flow_grid.is_empty():
        context.log.info("no grid rows yet — nothing to enrich")
        return pl.DataFrame(
            schema={
                "day": pl.Utf8,
                "completed": pl.Int64,
                "observed": pl.Int64,
                "adherence": pl.Float64,
                "production": pl.Int64,
                "perfect": pl.Boolean,
            }
        )

    observed = stg_flow_grid.filter(pl.col("outcome") != NEVER_APPEARED)
    per_day = (
        observed.group_by("day")
        .agg(
            completed=(pl.col("outcome") == COMPLETED).sum().cast(pl.Int64),
            observed=pl.len().cast(pl.Int64),
        )
        .with_columns(
            adherence=pl.col("completed") / pl.col("observed"),
            perfect=pl.col("completed") == pl.col("observed"),
        )
    )

    production = (
        stg_signals.filter(
            (pl.col("tier") == "production") & pl.col("flow_day").is_not_null()
        )
        .group_by(pl.col("flow_day").alias("day"))
        .agg(production=pl.len().cast(pl.Int64))
    )

    enriched = (
        per_day.join(production, on="day", how="left")
        .with_columns(pl.col("production").fill_null(0))
        .sort("day")
    )
    context.log.info("enriched %d day(s)", enriched.height)
    return enriched
