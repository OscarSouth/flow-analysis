"""Fact assets — the verdicts, each carrying its own adequacy.

Every measure is stored with the N it had and the N it needed, and with whether
it cleared. **A refusal is a result and is stored as one**: a measure that could
not be evaluated on the data available is a fact about the practice's age, not a
missing row, and dropping it would make the graph look like the question was
never asked.

Nothing here is causal. Card order is randomised for variety, not for inference,
so any coupling is confounded by construction — `confounded` rides along on the
node so a Cypher query cannot quietly forget it.
"""

# Dagster resolves resource and context annotations at run time, so this module
# deliberately does without `from __future__ import annotations`.

import json
from typing import Any

import polars as pl
from dagster import AssetExecutionContext, asset

from ..metrics import diagnostics as dx
from ..metrics.grid import FlowRow
from ..resources import FlowConfigResource

GROUP = "fct"

MEASURE_CYPHER = """
UNWIND $rows AS row
MERGE (m:Fct:Measure {name: row.name})
SET m.ok = row.ok,
    m.n = row.n,
    m.needs = row.needs,
    m.value_json = row.value_json,
    m.detail_json = row.detail_json,
    m.verdict = row.verdict,
    m.preregistered = row.preregistered,
    m.computed_at = row.computed_at
"""

MEASURE_LOAD = """
MATCH (m:Fct:Measure)
RETURN m.name AS name, m.ok AS ok, m.n AS n, m.needs AS needs,
       m.verdict AS verdict, m.preregistered AS preregistered,
       m.value_json AS value_json, m.detail_json AS detail_json,
       m.computed_at AS computed_at
ORDER BY m.name
"""

# The three committed to publicly in article 05, before any data existed. They
# are tested exactly as published — finding a flattering pattern afterwards is
# trivially easy and worth nothing.
PREREGISTERED = frozenset(
    {
        "h1_train_most_never_started",
        "h2_express_slowest_to_start",
        "h3_write_carries_the_others",
    }
)


@asset(
    group_name=GROUP,
    io_manager_key="graph_io_manager",
    metadata={"cypher_template": MEASURE_CYPHER, "load_cypher": MEASURE_LOAD},
    description="Every diagnostic and pre-registered verdict, with its adequacy.",
)
def fct_measures(
    context: AssetExecutionContext,
    flow_config: FlowConfigResource,
    stg_flow_grid: pl.DataFrame,
    stg_signals: pl.DataFrame,
) -> pl.DataFrame:
    """Run every diagnostic over the graph's own grid and store the verdicts.

    The grid is read back out of Neo4j rather than re-folded, which is the point
    of the layering: this is a fact about what the staged data says, and if the
    two disagreed the graph would be lying about itself.

    Values are stored as JSON strings. Neo4j properties are scalars or arrays of
    scalars, and these are nested — a per-mode table of medians, a lag profile —
    so flattening them into properties would either lose the shape or invent a
    dozen node types for things nothing joins on.
    """
    from datetime import UTC, datetime

    cfg = flow_config.load()
    rows = [FlowRow(**row) for row in stg_flow_grid.drop("failure_kind").to_dicts()]
    production = _production_by_day(stg_signals)

    diagnostics = dx.run_all(cfg, rows, production)
    computed_at = datetime.now(UTC).isoformat()

    records: list[dict[str, Any]] = []
    for name, measure in diagnostics["measures"].items():
        value = measure.value
        verdict = value.get("verdict") if isinstance(value, dict) else None
        records.append(
            {
                "name": name,
                "ok": measure.ok,
                "n": measure.n,
                "needs": measure.needs,
                "value_json": json.dumps(value, default=str),
                "detail_json": json.dumps(measure.detail, default=str),
                "verdict": verdict,
                "preregistered": name in PREREGISTERED,
                "computed_at": computed_at,
            }
        )

    refused = [r["name"] for r in records if not r["ok"]]
    context.log.info(
        "%d measure(s); %d still under-powered: %s",
        len(records),
        len(refused),
        ", ".join(refused) or "none",
    )
    return pl.DataFrame(
        records,
        schema={
            "name": pl.Utf8,
            "ok": pl.Boolean,
            "n": pl.Int64,
            "needs": pl.Int64,
            "value_json": pl.Utf8,
            "detail_json": pl.Utf8,
            "verdict": pl.Utf8,
            "preregistered": pl.Boolean,
            "computed_at": pl.Utf8,
        },
    )


def _production_by_day(signals: pl.DataFrame) -> dict[str, int]:
    """Production-tier events per flow day — the shared Layer B aggregation.

    The tier filter is the guard: without it someone else's star reads as your
    own output and `adherence_without_production` says the opposite of the truth.
    """
    from ..metrics.production import production_from_signals

    return production_from_signals(signals)
