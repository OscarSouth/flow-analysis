"""Constraints and indexes, applied once at startup.

Every constraint here is a uniqueness constraint on a natural key, which is what
makes `MERGE` idempotent: rematerialising an asset must update the same node
rather than growing a second one. Without them the graph would silently
accumulate duplicates and every count would drift upward on each run.

Node labels carry the medallion layer — `(:Stg:FlowRow)`, `(:Dim:Day)` — rather
than a name prefix, so `MATCH (r:Enr:FlowRow)` stays label-indexed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neo4j import Driver

# (name, label, properties) — a composite key is a tuple of properties.
CONSTRAINTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # A flow day is unique by date. The `NEXT` chain hangs off these.
    ("day_date", "Day", ("date",)),
    # One row per (day, activity): the dense grid's own key.
    ("flow_row_key", "FlowRow", ("day", "activity")),
    # The five modes.
    ("activity_name", "Activity", ("name",)),
    # Where a signal came from: forum, github, youtube, apple_health.
    ("source_name", "Source", ("name",)),
    # Signals dedupe on the same id the archive uses.
    ("signal_id", "Signal", ("id",)),
    # One verdict per measure per run of the analysis.
    ("measure_name", "Measure", ("name",)),
    # Knowledge entities: names encode type and day (`review:2026-08-18:monthly`),
    # so uniqueness on the shared Meta label covers every meta type at once.
    ("meta_name", "Meta", ("name",)),
    ("interpretation_name", "Interpretation", ("name",)),
    ("note_name", "Note", ("name",)),
    # One posterior snapshot per measure per day — the ridgeline's backbone.
    ("posterior_key", "Posterior", ("measure", "day")),
)

INDEXES: tuple[tuple[str, str, str], ...] = (
    # Outcome is the most common filter on the grid.
    ("flow_row_outcome", "FlowRow", "outcome"),
    # Signals are read by tier constantly — production vs reception is the
    # load-bearing split, and scanning all 5,000 to find one tier is wasteful.
    ("signal_tier", "Signal", "tier"),
)


def apply_schema(driver: Driver, database: str | None = None) -> list[str]:
    """Create every constraint and index, idempotently.

    `IF NOT EXISTS` throughout, so this runs on every startup and does nothing
    on the second call. Returns what it declared, for the caller to print.
    """
    statements: list[str] = []
    for name, label, properties in CONSTRAINTS:
        keys = ", ".join(f"n.{prop}" for prop in properties)
        statements.append(
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE ({keys}) IS UNIQUE"
        )
    for name, label, prop in INDEXES:
        statements.append(
            f"CREATE INDEX {name} IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"
        )

    with driver.session(database=database) as session:
        for statement in statements:
            session.run(statement)
    return statements
