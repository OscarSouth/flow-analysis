"""The one place analysis frames come out of the graph.

Every surface — report, evidence, dashboard, notebook, brief — reads through
these loaders. No surface embeds Cypher and none reads the archive: two analysis
paths over the same data would eventually disagree, and the graph is the single
source of analysis by decision (2026-08-18).

Failure is loud by design. A surface that reported zeros because Neo4j was down
would look exactly like a practice that stopped — the one lie this codebase is
built to never tell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl
from neo4j.exceptions import AuthError, ServiceUnavailable

from ..assets.dim import DAY_LOAD
from ..assets.fct import MEASURE_LOAD
from ..assets.stg import FLOW_ROW_LOAD, SIGNAL_LOAD
from ..metrics.grid import FlowRow
from ..resources.graph import Neo4jResource

if TYPE_CHECKING:
    from collections.abc import Sequence


class GraphUnavailableError(RuntimeError):
    """Neo4j cannot be reached. The platform is offline, not quiet."""


class GraphEmptyError(RuntimeError):
    """The graph holds nothing where history should be."""


def _frame(query: str) -> pl.DataFrame:
    """Run one read query and hand back a frame.

    `infer_schema_length=None` scans every row before deciding the schema — the
    signal payload is sparse in exactly the wrong way for sampled inference.
    """
    try:
        with Neo4jResource().driver() as driver, driver.session() as session:
            records = [dict(record) for record in session.run(query)]
    except (ServiceUnavailable, AuthError, OSError) as exc:
        raise GraphUnavailableError(
            "Neo4j is not reachable — analysis reads the graph and only the "
            "graph. Fix: `just up`, then `uv run flow sync` if the graph is "
            "behind the archive."
        ) from exc
    return pl.DataFrame(records, infer_schema_length=None)


def flow_grid() -> pl.DataFrame:
    """The dense (day, activity) grid, as staged.

    Raises rather than returning empty: a grid with no rows after the practice
    has started means the graph was never materialised, and every number
    downstream would silently read as a practice that never ran.
    """
    frame = _frame(FLOW_ROW_LOAD)
    if frame.is_empty():
        raise GraphEmptyError(
            "The graph holds no flow rows. Fix: `uv run flow sync` (materialises "
            "raw and graph layers), or `just up` first if Neo4j is down."
        )
    return frame


def flow_rows() -> list[FlowRow]:
    """The grid as FlowRow objects, for the metrics that take them.

    `failure_kind` is stored on the node but derived on the dataclass, so it is
    dropped before reconstruction.
    """
    return [FlowRow(**row) for row in flow_grid().drop("failure_kind").to_dicts()]


def signals_frame() -> pl.DataFrame:
    """Every staged signal with its full payload.

    Empty is legitimate here — a practice with no external sources configured
    still has a board — so this does not raise on emptiness.
    """
    return _frame(SIGNAL_LOAD)


def signal_dicts() -> list[dict[str, Any]]:
    """Signals as the dicts the reception/embodiment metrics consume.

    Deliberately bypasses polars: a frame forces one type per column, and
    `value` is int for counters and float for body measurements. The driver
    hands back each node's own types, exactly as the archive stored them.
    """
    try:
        with Neo4jResource().driver() as driver, driver.session() as session:
            return [dict(record["row"]) for record in session.run(SIGNAL_DICTS)]
    except (ServiceUnavailable, AuthError, OSError) as exc:
        raise GraphUnavailableError(
            "Neo4j is not reachable — analysis reads the graph and only the "
            "graph. Fix: `just up`, then `uv run flow sync`."
        ) from exc


SIGNAL_DICTS = """
MATCH (s:Stg:Signal)
RETURN s{.*} AS row
ORDER BY coalesce(s.created_at, s.observed_at)
"""


def day_adherence() -> pl.DataFrame:
    """Per-day adherence beside production, from the enriched calendar."""
    return _frame(
        """
        MATCH (d:Enr:Day)
        RETURN d.date AS day, d.completed AS completed, d.observed AS observed,
               d.adherence AS adherence, d.production AS production,
               d.perfect AS perfect
        ORDER BY d.date
        """
    )


def calendar() -> pl.DataFrame:
    """The dense flow-day calendar."""
    return _frame(DAY_LOAD)


def posteriors(day: str | None = None) -> pl.DataFrame:
    """Posterior snapshots — all days (the ridgeline), or one day's slice."""
    from ..assets.posteriors import POSTERIOR_LOAD

    frame = _frame(POSTERIOR_LOAD)
    if day is not None and not frame.is_empty():
        frame = frame.filter(pl.col("day") == day)
    return frame


def measures() -> pl.DataFrame:
    """Every stored measure with its adequacy — refusals included."""
    return _frame(MEASURE_LOAD)


def knowledge_entities() -> list[dict[str, Any]]:
    """Every knowledge entity's current state, scalar fields flattened.

    `props_json` carries the full parsed form; the scalars the brief needs
    (entity_type, day, status, confirmed, measure) come back as columns.
    """
    query = """
    MATCH (n) WHERE n:Meta OR n:Interpretation OR n:Note
    RETURN n.name AS name, n.entity_type AS entity_type, n.day AS day,
           n.status AS status, n.confirmed AS confirmed, n.measure AS measure,
           n.cadence AS cadence, n.captured_at AS captured_at
    ORDER BY n.day, n.name
    """
    return _frame(query).to_dicts()


def outcome_targets() -> set[str]:
    """Names of entities that have an inbound OUTCOME_OF — closed loops."""
    query = """
    MATCH (:Stg:Note)-[:OUTCOME_OF]->(t)
    RETURN DISTINCT t.name AS name
    """
    frame = _frame(query)
    return set() if frame.is_empty() else set(frame["name"].to_list())


def production_by_day() -> dict[str, int]:
    """Production-tier events per flow day, from the graph.

    Same aggregation the fct layer uses — one implementation, in Layer B.
    """
    from ..metrics.production import production_from_signals

    return production_from_signals(signals_frame())


__all__: Sequence[str] = [
    "GraphEmptyError",
    "GraphUnavailableError",
    "calendar",
    "day_adherence",
    "flow_grid",
    "flow_rows",
    "measures",
    "production_by_day",
    "signal_dicts",
    "signals_frame",
]
