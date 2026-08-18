"""GDS visibility assets — observed structure, never inference.

The repo's discipline splits visibility from inference, and GDS outputs are
classed the same way: what these assets write is *structure of what happened*
(which modes co-complete, which past day most resembles which) with no claim
attached. The inference-class uses — regime clustering, knowledge-network
centrality, embeddings — are registered DevProposals with explicit gates.

Pattern: refresh the standing projections, stream the algorithm, hand the frame
to the IO manager like any other asset. `pre_cypher` clears the derived edges
first, so pairs that no longer hold cannot linger from an earlier run.
"""

# Dagster resolves resource and context annotations at run time, so this module
# deliberately does without `from __future__ import annotations`.

import polars as pl
from dagster import AssetExecutionContext, asset

from ..graph.projections import CO_COMPLETION, DAY_FEATURES, refresh_projections
from ..resources.graph import Neo4jResource

GROUP = "enr"

ACTIVITY_SIM_PRE = "MATCH (:Dim:Activity)-[r:CO_COMPLETES]->() DELETE r"
ACTIVITY_SIM_CYPHER = """
UNWIND $rows AS row
MATCH (a:Dim:Activity {name: row.a})
MATCH (b:Dim:Activity {name: row.b})
MERGE (a)-[r:CO_COMPLETES]->(b)
SET r.similarity = row.similarity
"""
ACTIVITY_SIM_LOAD = """
MATCH (a:Dim:Activity)-[r:CO_COMPLETES]->(b:Dim:Activity)
RETURN a.name AS a, b.name AS b, r.similarity AS similarity
ORDER BY a, b
"""

DAY_SIM_PRE = "MATCH (:Enr:Day)-[r:SIMILAR_DAY]->() DELETE r"
DAY_SIM_CYPHER = """
UNWIND $rows AS row
MATCH (a:Dim:Day {date: row.a})
MATCH (b:Dim:Day {date: row.b})
MERGE (a)-[r:SIMILAR_DAY]->(b)
SET r.score = row.score
"""
DAY_SIM_LOAD = """
MATCH (a:Enr:Day)-[r:SIMILAR_DAY]->(b:Enr:Day)
RETURN a.date AS a, b.date AS b, r.score AS score
ORDER BY a, b
"""

SIM_SCHEMA = pl.Schema({"a": pl.Utf8, "b": pl.Utf8, "similarity": pl.Float64})
DAY_SCHEMA = pl.Schema({"a": pl.Utf8, "b": pl.Utf8, "score": pl.Float64})


@asset(
    group_name=GROUP,
    io_manager_key="graph_io_manager",
    metadata={
        "cypher_template": ACTIVITY_SIM_CYPHER,
        "pre_cypher": ACTIVITY_SIM_PRE,
        "load_cypher": ACTIVITY_SIM_LOAD,
    },
    description="Which modes travel together — Jaccard over shared completed days.",
)
def enr_activity_similarity(
    context: AssetExecutionContext,
    neo4j: Neo4jResource,
    stg_flow_grid: pl.DataFrame,
) -> pl.DataFrame:
    """Node similarity between modes, by the days they complete together.

    Visibility only: an observed overlap, not a facilitation claim — the
    co-occurrence *inference* (which modes enable which) is the pre-registered
    contrast models' job, and the probit DevProposal's after that.
    """
    _ = stg_flow_grid  # phantom dependency: the projection reads staged rows

    with neo4j.driver() as driver:
        sizes = refresh_projections(driver)
        if sizes[CO_COMPLETION] == 0:
            # Nothing completed yet — an empty projection is a young practice,
            # not a failure, and streaming over it would error.
            context.log.info("no completed rows yet — no co-completion structure")
            return pl.DataFrame([], schema=SIM_SCHEMA)
        with driver.session() as session:
            records = [
                dict(record)
                for record in session.run(
                    f"""
                    CALL gds.nodeSimilarity.stream('{CO_COMPLETION}')
                    YIELD node1, node2, similarity
                    RETURN gds.util.asNode(node1).name AS a,
                           gds.util.asNode(node2).name AS b,
                           similarity
                    """
                )
            ]
    context.log.info(
        "co-completion projection: %d edge(s); %d similarity pair(s)",
        sizes[CO_COMPLETION],
        len(records),
    )
    return pl.DataFrame(records, schema=SIM_SCHEMA)


@asset(
    group_name=GROUP,
    io_manager_key="graph_io_manager",
    metadata={
        "cypher_template": DAY_SIM_CYPHER,
        "pre_cypher": DAY_SIM_PRE,
        "load_cypher": DAY_SIM_LOAD,
    },
    description="Which past day most resembles which — KNN over day features.",
)
def enr_day_similarity(
    context: AssetExecutionContext,
    neo4j: Neo4jResource,
    enr_day_adherence: pl.DataFrame,
) -> pl.DataFrame:
    """K-nearest days by enriched features — retrieval, not inference.

    This is the agent's "last time the practice looked like this" lookup. The
    clustering that would *name* regimes is gated (DevProposal, 60 days) and
    superseded by the HMM when that gate opens.
    """
    _ = enr_day_adherence  # phantom dependency: features must be enriched first

    with neo4j.driver() as driver:
        sizes = refresh_projections(driver)
        if sizes[DAY_FEATURES] == 0:
            context.log.info("no enriched days yet — no day similarity")
            return pl.DataFrame([], schema=DAY_SCHEMA)
        with driver.session() as session:
            # knn is approximate and randomised by default; unseeded it returned
            # a different edge set run to run (2 vs 6 on three days), which broke
            # purge-and-rebuild equivalence on 2026-08-18. sampleRate 1.0 +
            # deltaThreshold 0 make it effectively exhaustive at this scale, and
            # randomSeed (the platform seed) with concurrency 1 — GDS requires
            # single-threaded for a seed to bind — pins the rest.
            records = [
                dict(record)
                for record in session.run(
                    f"""
                    CALL gds.knn.stream('{DAY_FEATURES}', {{
                        nodeProperties: ['adherence', 'production'],
                        topK: 3,
                        sampleRate: 1.0,
                        deltaThreshold: 0.0,
                        randomSeed: 108,
                        concurrency: 1
                    }})
                    YIELD node1, node2, similarity
                    RETURN gds.util.asNode(node1).date AS a,
                           gds.util.asNode(node2).date AS b,
                           similarity AS score
                    """
                )
            ]
    context.log.info("day KNN: %d pair(s)", len(records))
    return pl.DataFrame(records, schema=DAY_SCHEMA)
