"""`python -m flow_analysis.graph` — apply constraints and indexes.

Run by `just up` after the container is healthy. Idempotent, so it runs on every
start and does nothing on the second one.
"""

from __future__ import annotations

from ..resources.graph import Neo4jResource
from .schema import apply_schema


def main() -> int:
    """Apply the schema, and say how much was declared."""
    with Neo4jResource().driver() as driver:
        applied = apply_schema(driver)
    print(f"Graph schema: {len(applied)} constraint(s) and index(es) applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
