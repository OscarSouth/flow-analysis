"""The graph must be rebuildable from the archive alone, with no API calls.

This is the claim that makes it safe to keep irreplaceable history behind a
disposable Docker volume: `data/*.jsonl` is the truth, Neo4j is derived, and if
that ever stopped being true the volume would quietly become a second original.

Marked `integration` because it needs Neo4j running (`just up`). `just check`
stays offline; `just test-integration` runs this.

The network is blocked for the duration of the rebuild rather than merely
expected to be idle — a rebuild that reaches for an endpoint must fail here, not
succeed quietly and leave the claim untested.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import pytest
from dagster import materialize

from flow_analysis.assets import ALL_ASSETS, GRAPH_ASSETS
from flow_analysis.definitions import defs
from flow_analysis.resources.graph import Neo4jResource

if TYPE_CHECKING:
    from neo4j import Driver

pytestmark = pytest.mark.integration


def _fingerprint(driver: Driver) -> dict[str, Any]:
    """Everything the graph contains, reduced to something comparable.

    Node identity is the labels plus the properties, deliberately not the
    internal element id: a rebuild creates new internal ids and that is not a
    difference anybody cares about. `computed_at` is excluded for the same
    reason as `observed_at` in the archive — it records when the run happened,
    not what it found.
    """
    volatile = {"computed_at"}
    with driver.session() as session:
        nodes = []
        for record in session.run(
            "MATCH (n) RETURN labels(n) AS labels, properties(n) AS props"
        ):
            props = {k: v for k, v in record["props"].items() if k not in volatile}
            nodes.append(
                json.dumps(
                    {"labels": sorted(record["labels"]), "props": props},
                    sort_keys=True,
                    default=str,
                )
            )
        rels = []
        for record in session.run("""
            MATCH (a)-[r]->(b)
            RETURN type(r) AS type, properties(a) AS a, properties(b) AS b
        """):
            rels.append(
                json.dumps(
                    {
                        "type": record["type"],
                        "from": _key(record["a"]),
                        "to": _key(record["b"]),
                    },
                    sort_keys=True,
                    default=str,
                )
            )

    return {
        "nodes": len(nodes),
        "relationships": len(rels),
        "node_digest": hashlib.sha256("\n".join(sorted(nodes)).encode()).hexdigest(),
        "rel_digest": hashlib.sha256("\n".join(sorted(rels)).encode()).hexdigest(),
    }


def _key(props: dict[str, Any]) -> str:
    """A node's natural key, whichever of them it carries."""
    for candidate in ("date", "name", "id"):
        if candidate in props:
            return f"{candidate}={props[candidate]}"
    return f"day={props.get('day')},activity={props.get('activity')}"


def _rebuild_graph_assets() -> None:
    """Materialise every graph asset, with the network unplugged."""
    import httpx

    class _NoNetwork(httpx.Client):
        def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
            raise AssertionError(
                "a rebuild reached for the network — the graph must be derivable "
                "from data/*.jsonl alone"
            )

    original = httpx.Client
    httpx.Client = _NoNetwork  # type: ignore[misc]
    try:
        result = materialize(
            ALL_ASSETS,
            selection=[a.key.to_user_string() for a in GRAPH_ASSETS],
            resources=defs.resources,
        )
        assert result.success
    finally:
        httpx.Client = original  # type: ignore[misc]


def test_purge_and_rebuild_reproduces_the_graph():
    """Purge the whole graph, rebuild from the archive, compare byte for byte.

    If this fails, something is being stored in Neo4j that is not derivable from
    `data/` — which would mean the graph had quietly become the only copy of
    something, and the Docker volume was no longer disposable.
    """
    with Neo4jResource().driver() as driver:
        before = _fingerprint(driver)
        assert before["nodes"] > 0, "nothing to rebuild — materialise the graph first"

        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

        emptied = _fingerprint(driver)
        assert emptied["nodes"] == 0
        assert emptied["relationships"] == 0

        _rebuild_graph_assets()

        after = _fingerprint(driver)

    assert after["nodes"] == before["nodes"]
    assert after["relationships"] == before["relationships"]
    assert after["node_digest"] == before["node_digest"]
    assert after["rel_digest"] == before["rel_digest"]


def test_rematerialising_twice_does_not_duplicate():
    """Every write is MERGE, so the second run updates rather than grows.

    Without the uniqueness constraints in `graph/schema.py` this is exactly where
    the graph would start drifting upward on every run, and every count reported
    from it would be wrong in a way that looks like progress.
    """
    with Neo4jResource().driver() as driver:
        _rebuild_graph_assets()
        once = _fingerprint(driver)
        _rebuild_graph_assets()
        twice = _fingerprint(driver)

    assert twice["nodes"] == once["nodes"]
    assert twice["relationships"] == once["relationships"]
    assert twice["node_digest"] == once["node_digest"]
