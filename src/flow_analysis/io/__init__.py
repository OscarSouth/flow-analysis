"""Layer C — persistence. One IO manager per store.

`data/*.jsonl` is the archive and the truth; Neo4j (step 5) is derived from it.
No asset touches either directly: assets return values, and these managers put
them where they belong.
"""

from __future__ import annotations

from .jsonl_io_manager import JsonlIOManager
from .streams import STREAMS, RawStream

__all__ = ["STREAMS", "JsonlIOManager", "RawStream"]
