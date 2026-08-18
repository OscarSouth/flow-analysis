"""Neo4j: the derived store.

`data/*.jsonl` is the truth; everything here is rebuilt from it. Purging the
volume and rematerialising must reproduce the graph exactly, with **no external
API calls** — that is what makes it safe to keep irreplaceable history behind a
disposable Docker volume, and it is asserted by `tests/test_rebuildable.py`.
"""

from __future__ import annotations

from .schema import CONSTRAINTS, apply_schema

__all__ = ["CONSTRAINTS", "apply_schema"]
