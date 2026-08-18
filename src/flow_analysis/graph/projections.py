"""Standing GDS projections — created by the platform, streamed by anyone.

The neo4j MCP is read-only by design, and creating a projection writes to the
GDS catalog — so the platform owns projection lifecycle, and the agent runs
`gds.*.stream` against these standing names through read-cypher.

Recreated (drop-then-project) on every refresh: a stale projection quietly
answering yesterday's structure is the same lie as a stale surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neo4j import Driver

# Bipartite activity→day through completed flow rows, oriented so that
# nodeSimilarity (which compares source nodes by shared out-neighbours) asks:
# which modes travel together across days, as observed structure.
CO_COMPLETION = "flow_cocompletion"

# Days with their enriched features, for similarity ("which past day most
# resembles today") and, once gated, regime exploration.
DAY_FEATURES = "flow_days"


def refresh_projections(driver: Driver) -> dict[str, int]:
    """Drop and re-project both standing graphs; return their sizes."""
    sizes: dict[str, int] = {}
    with driver.session() as session:
        for name in (CO_COMPLETION, DAY_FEATURES):
            session.run(
                "CALL gds.graph.drop($name, false) YIELD graphName",
                name=name,
            ).consume()

        record = session.run(
            f"""
            MATCH (d:Dim:Day)<-[:ON_DAY]-(r:Stg:FlowRow {{outcome: 'completed'}})
                  -[:OF_ACTIVITY]->(a:Dim:Activity)
            WITH gds.graph.project('{CO_COMPLETION}', a, d) AS g
            RETURN g.relationshipCount AS n
            """
        ).single()
        sizes[CO_COMPLETION] = int(record["n"] or 0) if record else 0

        record = session.run(
            f"""
            MATCH (d:Enr:Day)
            WITH gds.graph.project(
                '{DAY_FEATURES}', d, null,
                {{
                    sourceNodeProperties: d {{
                        .adherence, .completed, .observed, .production
                    }},
                    targetNodeProperties: {{}}
                }}
            ) AS g
            RETURN g.nodeCount AS n
            """
        ).single()
        sizes[DAY_FEATURES] = int(record["n"] or 0) if record else 0
    return sizes
