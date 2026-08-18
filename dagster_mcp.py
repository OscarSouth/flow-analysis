"""Dagster MCP server launcher with FastMCP compatibility patch.

Why: mcp-server-dagster v0.1.2 passes `description=` to FastMCP.__init__(),
which was removed in mcp SDK >=1.6.0. This wrapper patches the constructor
before importing the server module, then runs it with stdio transport
(compatible with Claude Code's MCP config pattern).

See: https://github.com/kyryl-opens-ml/mcp-server-dagster/issues/3
"""

import os

from mcp.server.fastmcp import FastMCP

# --- Patch FastMCP to accept (and ignore) the removed `description` kwarg ---
_original_init = FastMCP.__init__


def _patched_init(self, *args, **kwargs) -> None:  # noqa: ANN001, ANN002, ANN003
    kwargs.pop("description", None)
    _original_init(self, *args, **kwargs)


FastMCP.__init__ = _patched_init  # type: ignore[assignment]

# --- Configure GraphQL URL from environment ---
# Default matches `dagster dev` on localhost:3000
graphql_url = os.environ.get("DAGSTER_GRAPHQL_URL", "http://localhost:3000/graphql")

# --- Import server (triggers FastMCP instantiation with patched init) ---
from mcp_dagster.server import dagster_client, mcp  # noqa: E402

dagster_client.graphql_url = graphql_url

# --- Run with stdio transport (Claude Code compatible) ---
if __name__ == "__main__":
    mcp.run()
