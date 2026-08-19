"""Knowledge assets — the agent's record of the practice, in the graph.

The taxonomy is validated at capture (`raw_agent_memory`), so by the time rows
arrive here they are well-formed. This layer's job is placement: each entity
type lands under its CSF-assigned labels, joins the calendar by its day, and
points at the measure it concerns — so "what did the last review conclude, and
did it hold?" is a Cypher question.

Names are natural keys (`review:2026-08-18:monthly`), so an entity edited in
the working set MERGEs onto the same node with its latest state, while the
archive underneath keeps every state it passed through.
"""

# Dagster resolves resource and context annotations at run time, so this module
# deliberately does without `from __future__ import annotations`.

import json
from typing import Any

import polars as pl
from dagster import AssetExecutionContext, asset

GROUP = "meta"

# apoc.merge.node takes the label list per row, which is what lets one asset
# place every entity type in the taxonomy — Cypher alone cannot parameterise
# labels.
KNOWLEDGE_CYPHER = """
UNWIND $rows AS row
CALL apoc.merge.node(row.labels, {name: row.name}, {}, {}) YIELD node
SET node += row.props
"""

# Structural links are derived from fields, not declared by the agent: every
# dated entity joins the calendar, anything naming a measure points at it, and
# anything naming the day's modes (`activities: Train, Express` — comma-
# separated) points at those (:Stg:FlowRow) state rows. REFLECTS_ON is
# structural like ON_DAY: derived here, never agent-declared, excluded from
# LINKS_LOAD.
KNOWLEDGE_POST = """
MATCH (n) WHERE (n:Meta OR n:Interpretation OR n:Note) AND n.day IS NOT NULL
MATCH (d:Dim:Day {date: n.day})
MERGE (n)-[:ON_DAY]->(d)
WITH DISTINCT 1 AS _
MATCH (n) WHERE (n:Meta OR n:Interpretation) AND n.measure IS NOT NULL
MATCH (m:Fct:Measure {name: n.measure})
MERGE (n)-[:CONCERNS]->(m)
WITH DISTINCT 1 AS _
MATCH (n) WHERE (n:Meta OR n:Interpretation OR n:Note)
  AND n.day IS NOT NULL AND n.activities IS NOT NULL
UNWIND split(n.activities, ',') AS act
MATCH (r:Stg:FlowRow {day: n.day, activity: trim(act)})
MERGE (n)-[:REFLECTS_ON]->(r)
"""

KNOWLEDGE_LOAD = """
MATCH (n) WHERE n:Meta OR n:Interpretation OR n:Note
RETURN n.name AS name, n.entity_type AS entity_type, n.day AS day,
       n.captured_at AS captured_at, n.props_json AS props_json
ORDER BY n.day, n.name
"""

LINKS_CYPHER = """
UNWIND $rows AS row
MATCH (a {name: row.from_name})
MATCH (b {name: row.to_name})
WHERE (a:Meta OR a:Interpretation OR a:Note)
  AND (b:Meta OR b:Interpretation OR b:Note OR b:Measure OR b:Activity)
CALL apoc.merge.relationship(a, row.rel_type, {}, {}, b, {}) YIELD rel
RETURN count(rel) AS linked
"""

# This list must cover every value of taxonomy.RELATION_TYPES (bar the
# structural ON_DAY): a relation missing here is written by LINKS_CYPHER but
# invisible on read-back, which the equivalence check would read as data loss.
# tests/test_knowledge.py pins the two in lockstep.
LINKS_LOAD = """
MATCH (a)-[r]->(b)
WHERE (a:Meta OR a:Interpretation OR a:Note)
  AND type(r) IN ['CONCERNS','FOLLOWS_FROM','TESTS','PRESCRIBED_BY',
                  'OUTCOME_OF','ENABLED_BY',
                  'REVISES','CHALLENGES','SUPPORTS','CITES']
RETURN a.name AS from_name, type(r) AS rel_type, b.name AS to_name
ORDER BY from_name, rel_type, to_name
"""


@asset(
    group_name=GROUP,
    io_manager_key="graph_io_manager",
    metadata={
        "cypher_template": KNOWLEDGE_CYPHER,
        "post_cypher": KNOWLEDGE_POST,
        "load_cypher": KNOWLEDGE_LOAD,
    },
    description="The agent's captured record: reviews, verdicts, proposals.",
)
def stg_knowledge(
    context: AssetExecutionContext,
    raw_agent_memory: list[dict[str, Any]],
    dim_day: pl.DataFrame,
    fct_measures: pl.DataFrame,
    stg_flow_grid: pl.DataFrame,
) -> pl.DataFrame:
    """Place every captured entity under its labels, latest state winning.

    The archive holds every state an entity passed through (content-hash rows);
    the graph holds the current one — later captures MERGE onto the same name.
    Scalar fields become properties; the full parsed form rides as `props_json`
    so nothing the agent wrote is unreachable.
    """
    _ = dim_day  # phantom dependency: the post-cypher MATCHes (:Dim:Day)
    # Phantom dependency: the post-cypher also MATCHes (:Fct:Measure) for the
    # CONCERNS edges. Without it, a from-empty rebuild ordered this asset
    # before fct_measures and the MATCH found nothing — silently, because
    # MERGE-on-MATCH cannot fail. Caught by purge-and-rebuild on 2026-08-18:
    # four CONCERNS edges present in the live graph, absent after rebuild.
    _ = fct_measures
    # Same bug class, avoided rather than caught: REFLECTS_ON MATCHes
    # (:Stg:FlowRow), so the grid must land first.
    _ = stg_flow_grid

    latest: dict[str, dict[str, Any]] = {}
    for row in raw_agent_memory:
        if row.get("note_kind") == "entity":
            latest[row["name"]] = row

    rows = []
    for note in latest.values():
        props = {
            key: value
            for key, value in note.items()
            if key not in {"id", "labels", "note_kind", "observations"}
            and isinstance(value, (str, int, float, bool))
        }
        props["props_json"] = json.dumps(
            {k: v for k, v in note.items() if k not in {"id", "labels", "note_kind"}},
            sort_keys=True,
        )
        rows.append({"name": note["name"], "labels": note["labels"], "props": props})
    context.log.info("placed %d knowledge entit(ies)", len(rows))
    schema: dict[str, pl.DataType] = {
        "name": pl.Utf8(),
        "labels": pl.List(pl.Utf8),
        "props": pl.Object(),
    }
    return pl.DataFrame(rows, schema=pl.Schema(schema))


@asset(
    group_name=GROUP,
    io_manager_key="graph_io_manager",
    metadata={"cypher_template": LINKS_CYPHER, "load_cypher": LINKS_LOAD},
    description="Agent-declared relations between knowledge entities.",
)
def stg_knowledge_links(
    context: AssetExecutionContext,
    raw_agent_memory: list[dict[str, Any]],
    stg_knowledge: pl.DataFrame,
) -> pl.DataFrame:
    """The closed relation set, between nodes that already exist.

    `stg_knowledge` is a declared input so the nodes land first; a relation
    whose endpoint is missing simply matches nothing rather than creating a
    dangling node — the endpoint's own capture is the fix.
    """
    _ = stg_knowledge  # phantom dependency: endpoints must exist first

    rows = [
        {
            "from_name": row["from_name"],
            "to_name": row["to_name"],
            "rel_type": row["rel_type"],
        }
        for row in raw_agent_memory
        if row.get("note_kind") == "relation"
    ]
    context.log.info("declared %d relation(s)", len(rows))
    return pl.DataFrame(
        rows,
        schema=pl.Schema(
            {"from_name": pl.Utf8, "to_name": pl.Utf8, "rel_type": pl.Utf8}
        ),
    )
