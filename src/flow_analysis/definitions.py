"""The Dagster code location: every asset, every resource, one object.

Lineage lives here rather than in the graph — Dagster owns which asset feeds
which, so nothing downstream has to model it.
"""

from __future__ import annotations

from dagster import Definitions

from .assets import ALL_ASSETS
from .io import JsonlIOManager
from .io.neo4j_io_manager import Neo4jIOManager
from .resources import (
    FlowConfigResource,
    ForumResource,
    GitHubResource,
    HealthResource,
    TrelloResource,
    YouTubeResource,
)
from .resources.graph import Neo4jResource

defs = Definitions(
    assets=ALL_ASSETS,
    resources={
        # The archive. Append-only, dedupes per stream, never rewritten.
        "io_manager": JsonlIOManager(),
        # The derived store. Every write is MERGE, so a rematerialisation
        # updates the same nodes rather than growing a second copy.
        "graph_io_manager": Neo4jIOManager(neo4j=Neo4jResource()),
        "neo4j": Neo4jResource(),
        "flow_config": FlowConfigResource(),
        "trello": TrelloResource(),
        "forum": ForumResource(),
        "github": GitHubResource(),
        "youtube": YouTubeResource(),
        "health": HealthResource(),
    },
)
