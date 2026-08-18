"""All graph persistence, in one place.

No asset calls Neo4j directly. Assets return a Polars DataFrame and declare the
Cypher beside themselves in `@asset(metadata={...})`:

    cypher_template   UNWIND batch write, run with `rows` bound to the frame
    load_cypher       how a downstream asset reads it back
    pre_cypher        optional clear-down, run once before the batches
    post_cypher       optional second pass, e.g. chaining `(:Day)-[:NEXT]->`

Templates are co-located with the asset rather than pooled in a shared
`queries.py`, so reading an asset tells you exactly what it writes.

Everything is `MERGE`, never `CREATE`: rematerialising must update the same nodes
rather than growing a second copy, which is what makes the graph rebuildable
from the archive and safe to purge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl
from dagster import ConfigurableIOManager, InputContext, OutputContext

from ..resources.graph import Neo4jResource

if TYPE_CHECKING:
    from collections.abc import Mapping

# Neo4j's transaction memory is finite and the write is a single UNWIND, so rows
# go in batches. 1,000 is comfortable for this project's row counts and keeps a
# failed batch small enough to reason about.
BATCH_SIZE = 1_000


class Neo4jIOManager(ConfigurableIOManager):
    """Write a frame into the graph, and read one back out."""

    neo4j: Neo4jResource

    def handle_output(self, context: OutputContext, obj: pl.DataFrame) -> None:
        """Run the asset's `cypher_template` over its rows, then any `post_cypher`.

        An empty frame is a legitimate outcome — the practice may be two days old
        and a measure may have nothing to say — so it writes nothing and says so
        rather than failing.
        """
        template = _required(context.definition_metadata, "cypher_template", context)
        pre = (context.definition_metadata or {}).get("pre_cypher")
        post = (context.definition_metadata or {}).get("post_cypher")

        rows = obj.to_dicts()
        written = 0
        with self.neo4j.driver() as driver, driver.session() as session:
            if pre:
                # Runs once, before any batch: the place to clear derived edges
                # that a fresh materialisation replaces wholesale, so pairs that
                # no longer hold do not linger from an earlier run.
                session.run(pre)
            for start in range(0, len(rows), BATCH_SIZE):
                batch = rows[start : start + BATCH_SIZE]
                session.run(template, rows=batch)
                written += len(batch)
            if post:
                session.run(post)

        context.add_output_metadata(
            {
                "rows_written": written,
                "batches": (written + BATCH_SIZE - 1) // BATCH_SIZE,
                "ran_post_cypher": bool(post),
            }
        )

    def load_input(self, context: InputContext) -> pl.DataFrame:
        """Read an upstream asset back out of the graph with its `load_cypher`."""
        upstream = context.upstream_output
        if upstream is None:  # pragma: no cover - Dagster always sets this
            raise ValueError("load_input called without an upstream output")
        query = _required(upstream.definition_metadata, "load_cypher", context)
        with self.neo4j.driver() as driver, driver.session() as session:
            records = [dict(record) for record in session.run(query)]
        # Scan every row before deciding the schema. Polars infers from the first
        # 100 by default, and these frames are sparse in exactly the wrong way:
        # the oldest signals are forum posts, which carry no `observed_at`, so a
        # sampled inference calls that column null and then fails on the first
        # counter row that has one. Row counts here are thousands, not millions.
        return pl.DataFrame(records, infer_schema_length=None)


def _required(
    metadata: Mapping[str, Any] | None,
    key: str,
    context: InputContext | OutputContext,
) -> str:
    """Fetch a required Cypher template, or say which asset is missing which one.

    Failing here beats a silent no-op: an asset that declares no write would
    materialise successfully and leave the graph empty.
    """
    value = (metadata or {}).get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{context!r}: @asset(metadata=...) must declare {key!r} as Cypher"
        )
    return value
