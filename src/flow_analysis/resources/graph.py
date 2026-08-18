"""Neo4j, as a resource.

Credentials come from `.env` like every other secret here, never from Dagster
run config — config is stored with the run and shown in the UI.

The MCP server connects to the same database with `NEO4J_READ_ONLY=true`: reading
the graph to answer a question is the point, and every write goes through the IO
manager so there is one place where the graph changes.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from dagster import ConfigurableResource

from neo4j import GraphDatabase

from ..config import read_env

if TYPE_CHECKING:
    from collections.abc import Iterator

    from neo4j import Driver

DEFAULT_URI = "bolt://localhost:7689"


class Neo4jResource(ConfigurableResource["Neo4jResource"]):
    """A driver for the derived store.

    `database` is left at the server default. This project runs one database;
    naming it here would only be a second place to keep in step.
    """

    def _credentials(self) -> tuple[str, str, str]:
        env = read_env()
        uri = env.get("NEO4J_URI") or DEFAULT_URI
        user = env.get("NEO4J_USER") or "neo4j"
        password = env.get("NEO4J_PASSWORD")
        if not password:
            raise RuntimeError(
                "NEO4J_PASSWORD is not set in .env. The graph is derived, so this "
                "is recoverable: set it and re-run, or `just up` for a fresh "
                "container."
            )
        return uri, user, password

    @contextmanager
    def driver(self) -> Iterator[Driver]:
        """A driver for the duration of one asset, closed on the way out."""
        uri, user, password = self._credentials()
        driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            # Sparse properties are the design (the signal payload varies by
            # source), so "property key does not exist" notifications are
            # noise, not warnings.
            notifications_min_severity="OFF",
        )
        try:
            yield driver
        finally:
            driver.close()
