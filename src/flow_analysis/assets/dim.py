"""Dimension assets — the things facts hang off.

Layers are Neo4j **labels**, not name prefixes: these write `(:Dim:Day)` and
`(:Dim:Activity)`, so `MATCH (d:Dim:Day)` stays label-indexed.

Every write is `MERGE` on the natural key the schema constrains, so
rematerialising updates the same nodes instead of growing a second set.
"""

# Dagster resolves resource and context annotations at run time, so this module
# deliberately does without `from __future__ import annotations`.

from datetime import date

import polars as pl
from dagster import AssetExecutionContext, asset

from ..metrics.calendar import calendar_days
from ..resources import FlowConfigResource

GROUP = "dim"

DAY_CYPHER = """
UNWIND $rows AS row
MERGE (d:Dim:Day {date: row.date})
SET d.weekday = row.weekday,
    d.weekday_index = row.weekday_index,
    d.is_weekend = row.is_weekend,
    d.iso_week = row.iso_week,
    d.month = row.month,
    d.year = row.year
"""

# The chain is a second pass because it needs every node to exist first. Matching
# on `date` arithmetic keeps it independent of insertion order, so a backfill
# that adds older days still links them correctly.
DAY_NEXT_CYPHER = """
MATCH (a:Dim:Day), (b:Dim:Day)
WHERE date(b.date) = date(a.date) + duration({days: 1})
MERGE (a)-[:NEXT]->(b)
"""

DAY_LOAD = """
MATCH (d:Dim:Day)
RETURN d.date AS date, d.weekday AS weekday, d.weekday_index AS weekday_index,
       d.is_weekend AS is_weekend, d.iso_week AS iso_week, d.month AS month,
       d.year AS year
ORDER BY d.date
"""

ACTIVITY_CYPHER = """
UNWIND $rows AS row
MERGE (a:Dim:Activity {name: row.name})
SET a.position = row.position, a.letter = row.letter
"""

ACTIVITY_LOAD = """
MATCH (a:Dim:Activity)
RETURN a.name AS name, a.position AS position, a.letter AS letter
ORDER BY a.position
"""


@asset(
    group_name=GROUP,
    io_manager_key="graph_io_manager",
    metadata={
        "cypher_template": DAY_CYPHER,
        "post_cypher": DAY_NEXT_CYPHER,
        "load_cypher": DAY_LOAD,
    },
    description="The flow-day calendar, dense, with a NEXT chain between days.",
)
def dim_day(
    context: AssetExecutionContext, flow_config: FlowConfigResource
) -> pl.DataFrame:
    """Every flow day from the epoch to today, whether or not anything happened.

    The span starts at `history.start_date` — the day the practice went live —
    because everything is measured from the epoch and never from birth. It ends
    today rather than yesterday: the day in progress is a real day, it is simply
    not complete, and the gates elsewhere are what decline to draw conclusions
    from it.
    """
    cfg = flow_config.load()
    if cfg.start_date is None:
        raise ValueError(
            "history.start_date is unset in config/board.yaml, so the calendar "
            "has no epoch to start from. Set it to the first day the flow system "
            "was live."
        )
    days = calendar_days(cfg.start_date, date.today())
    context.log.info("calendar spans %d day(s) from %s", len(days), cfg.start_date)
    return pl.DataFrame(days)


@asset(
    group_name=GROUP,
    io_manager_key="graph_io_manager",
    metadata={"cypher_template": ACTIVITY_CYPHER, "load_cypher": ACTIVITY_LOAD},
    description="The five W.A.T.E.R. modes, in their canonical order.",
)
def dim_activity(
    context: AssetExecutionContext, flow_config: FlowConfigResource
) -> pl.DataFrame:
    """The five modes, from config rather than hard-coded.

    Card titles are a contract: the refill rule creates cards by literal name and
    the grid joins on it, so these names must be the configured ones or a mode
    records as `never_appeared` forever.
    """
    activities = list(flow_config.load().activities)
    rows = [
        {"name": name, "position": index + 1, "letter": name[0].upper()}
        for index, name in enumerate(activities)
    ]
    context.log.info("modes: %s", ", ".join(activities))
    return pl.DataFrame(rows)
