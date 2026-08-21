"""Staging assets — validated and deduplicated, still one row per observation.

The folded flow grid and the tiered signals. Nothing here draws a conclusion;
`enr` derives, `fct` judges.

These take their raw inputs as **asset arguments**, which is the point of the
JSONL IO manager: the fold receives cards and actions rather than reaching into
the store, so the lineage is real and a rebuild needs no network.
"""

# Dagster resolves resource and context annotations at run time, so this module
# deliberately does without `from __future__ import annotations`.

from typing import Any

import polars as pl
from dagster import AssetExecutionContext, asset

from ..metrics.calendar import flow_day
from ..metrics.grid import fold_rows, latest_observation, to_dicts
from ..resources import FlowConfigResource
from ..tiers import row_tier
from ..util import parse_iso

GROUP = "stg"

# Declared rather than inferred. Polars infers from the first rows only, and both
# frames are sparse in exactly the wrong way: the earliest signals are forum
# posts, which carry `created_at` and no `observed_at`, so inference decides that
# column is null and then fails on the first counter row that has one.
FLOW_ROW_SCHEMA = pl.Schema(
    {
        "day": pl.Utf8,
        "activity": pl.Utf8,
        "outcome": pl.Utf8,
        "card_id": pl.Utf8,
        "appeared_at": pl.Utf8,
        "started_at": pl.Utf8,
        "completed_at": pl.Utf8,
        "archived_at": pl.Utf8,
        "minutes_to_start": pl.Float64,
        "minutes_to_complete": pl.Float64,
        "pull_rank": pl.Int64,
        "interleaved": pl.Int64,
        "deep": pl.Boolean,
        "failure_kind": pl.Utf8,
    }
)

# The full scalar payload rides into the graph as sparse node properties —
# queryable in Cypher, which a JSON blob would not be. `day` is the SOURCE'S own
# day where one exists (YouTube analytics report their day, and reception reads
# it); `flow_day` is computed from `created_at` at the 04:00 boundary and is
# what links to the calendar. Shadowing the native day with the computed one was
# a live bug caught while planning the re-point: it would have shifted every
# YouTube row's history quietly.
SIGNAL_SCHEMA = pl.Schema(
    {
        "id": pl.Utf8,
        "tier": pl.Utf8,
        "source": pl.Utf8,
        "kind": pl.Utf8,
        "created_at": pl.Utf8,
        "observed_at": pl.Utf8,
        "day": pl.Utf8,
        "flow_day": pl.Utf8,
        # -- payload: identity and text --
        "channel_id": pl.Utf8,
        "device": pl.Utf8,
        "metric": pl.Utf8,
        "unit": pl.Utf8,
        "activity": pl.Utf8,
        "repo": pl.Utf8,
        "actor": pl.Utf8,
        "title": pl.Utf8,
        "video_id": pl.Utf8,
        "author": pl.Utf8,
        "discussion_id": pl.Utf8,
        "discussion_title": pl.Utf8,
        "referrer": pl.Utf8,
        # -- payload: counts and measures --
        "views": pl.Int64,
        "minutes_watched": pl.Int64,
        "subscribers_gained": pl.Int64,
        "subscribers_lost": pl.Int64,
        "count": pl.Int64,
        "uniques": pl.Int64,
        "window_days": pl.Int64,
        # Mixed by construction: GitHub counters write ints, body measurements
        # write floats, and the archive preserves each row's own type. Object
        # keeps that verbatim — coercing to Float64 turned "stars 116" into
        # "stars 116.0" in every rendered surface.
        "value": pl.Object,
        "duration_minutes": pl.Float64,
        # -- payload: the workout heart-rate series (kind: workout_hr) --
        # Object rather than pl.List so the integer lists ride verbatim into
        # `to_dicts` and land as Neo4j primitive arrays. Two parallel arrays by
        # necessity: Neo4j properties cannot nest.
        "workout_id": pl.Utf8,
        "ended_at": pl.Utf8,
        "hr_offsets_s": pl.Object,
        "hr_bpm": pl.Object,
        "hr_avg_session": pl.Float64,
        "hr_min_session": pl.Float64,
        "hr_max_session": pl.Float64,
        "active_kcal": pl.Float64,
        "avg_mets": pl.Float64,
        # -- payload: flags --
        "strength": pl.Boolean,
        "opens_thread": pl.Boolean,
        "internal": pl.Boolean,
    }
)

FLOW_ROW_CYPHER = """
UNWIND $rows AS row
MERGE (r:Stg:FlowRow {day: row.day, activity: row.activity})
SET r.outcome = row.outcome,
    r.card_id = row.card_id,
    r.appeared_at = row.appeared_at,
    r.started_at = row.started_at,
    r.completed_at = row.completed_at,
    r.archived_at = row.archived_at,
    r.minutes_to_start = row.minutes_to_start,
    r.minutes_to_complete = row.minutes_to_complete,
    r.pull_rank = row.pull_rank,
    r.interleaved = row.interleaved,
    r.deep = row.deep,
    r.failure_kind = row.failure_kind
WITH r, row
MATCH (d:Dim:Day {date: row.day})
MERGE (r)-[:ON_DAY]->(d)
WITH r, row
MATCH (a:Dim:Activity {name: row.activity})
MERGE (r)-[:OF_ACTIVITY]->(a)
"""

FLOW_ROW_LOAD = """
MATCH (r:Stg:FlowRow)
RETURN r.day AS day, r.activity AS activity, r.outcome AS outcome,
       r.card_id AS card_id, r.appeared_at AS appeared_at,
       r.started_at AS started_at, r.completed_at AS completed_at,
       r.archived_at AS archived_at,
       r.minutes_to_start AS minutes_to_start,
       r.minutes_to_complete AS minutes_to_complete,
       r.pull_rank AS pull_rank, r.interleaved AS interleaved,
       r.deep AS deep, r.failure_kind AS failure_kind
ORDER BY r.day, r.activity
"""

# `SET s = row` replaces the property map wholesale, so a field that became
# null disappears rather than sticking — rematerialisation stays idempotent.
SIGNAL_CYPHER = """
UNWIND $rows AS row
MERGE (s:Stg:Signal {id: row.id})
SET s = row
WITH s, row
MERGE (src:Dim:Source {name: row.source})
MERGE (s)-[:FROM_SOURCE]->(src)
WITH s, row
WHERE row.flow_day IS NOT NULL
MATCH (d:Dim:Day {date: row.flow_day})
MERGE (s)-[:ON_DAY]->(d)
"""

SIGNAL_LOAD = """
MATCH (s:Stg:Signal)
RETURN s.id AS id, s.tier AS tier, s.source AS source, s.kind AS kind,
       s.created_at AS created_at, s.observed_at AS observed_at,
       s.day AS day, s.flow_day AS flow_day,
       s.channel_id AS channel_id, s.device AS device, s.metric AS metric,
       s.unit AS unit, s.activity AS activity, s.repo AS repo, s.actor AS actor,
       s.title AS title, s.video_id AS video_id, s.author AS author,
       s.discussion_id AS discussion_id, s.discussion_title AS discussion_title,
       s.referrer AS referrer,
       s.views AS views, s.minutes_watched AS minutes_watched,
       s.subscribers_gained AS subscribers_gained,
       s.subscribers_lost AS subscribers_lost,
       s.count AS count, s.uniques AS uniques, s.window_days AS window_days,
       s.value AS value, s.duration_minutes AS duration_minutes,
       s.workout_id AS workout_id, s.ended_at AS ended_at,
       s.hr_offsets_s AS hr_offsets_s, s.hr_bpm AS hr_bpm,
       s.hr_avg_session AS hr_avg_session, s.hr_min_session AS hr_min_session,
       s.hr_max_session AS hr_max_session, s.active_kcal AS active_kcal,
       s.avg_mets AS avg_mets,
       s.strength AS strength, s.opens_thread AS opens_thread,
       s.internal AS internal
ORDER BY coalesce(s.created_at, s.observed_at)
"""


@asset(
    group_name=GROUP,
    io_manager_key="graph_io_manager",
    metadata={"cypher_template": FLOW_ROW_CYPHER, "load_cypher": FLOW_ROW_LOAD},
    description="One row per (flow day, activity) — the dense grid.",
)
def stg_flow_grid(
    context: AssetExecutionContext,
    flow_config: FlowConfigResource,
    raw_trello_cards: list[dict[str, Any]],
    raw_trello_actions: list[dict[str, Any]],
    dim_day: pl.DataFrame,
    dim_activity: pl.DataFrame,
) -> pl.DataFrame:
    """Fold the archived cards and actions into the grid.

    `dim_day` and `dim_activity` are declared as inputs and deliberately unused:
    the Cypher `MATCH`es those nodes to attach `ON_DAY` and `OF_ACTIVITY`, so
    they have to exist first. Dagster orders the run from this declaration — the
    dependency is real even though the value is never read.
    """
    _ = dim_day, dim_activity  # phantom dependencies; see the docstring

    cards = latest_observation(raw_trello_cards)
    rows = fold_rows(flow_config.load(), cards, raw_trello_actions)
    context.log.info("folded %d grid row(s) from %d card(s)", len(rows), len(cards))
    return pl.DataFrame(to_dicts(rows), schema=FLOW_ROW_SCHEMA)


@asset(
    group_name=GROUP,
    io_manager_key="graph_io_manager",
    metadata={"cypher_template": SIGNAL_CYPHER, "load_cypher": SIGNAL_LOAD},
    description="External signals, tiered, one node per archived row.",
)
def stg_signals(
    context: AssetExecutionContext,
    flow_config: FlowConfigResource,
    raw_forum_posts: list[dict[str, Any]],
    raw_github_signals: list[dict[str, Any]],
    raw_youtube_signals: list[dict[str, Any]],
    raw_health_signals: list[dict[str, Any]],
    dim_day: pl.DataFrame,
) -> pl.DataFrame:
    """Every signal row, with its tier resolved and its flow day attached.

    All four sources share one archive file, so each input hands back the same
    stream; they are declared separately because each is a real dependency — the
    graph should be built behind every source that landed — and deduplicated by
    id here. That is the archive's own key, so this cannot drop a row.

    The tier is resolved rather than trusted: rows written before the field
    existed default to production, and without that a stranger's star would read
    as your own output.

    Rows that are *levels* rather than events — a star total, a traffic window —
    carry no `created_at` and attach to no day. They belong to the snapshot
    surfaces, not to the calendar.
    """
    _ = dim_day  # phantom dependency: the Cypher MATCHes (:Dim:Day)

    cfg = flow_config.load()
    merged: dict[str, dict[str, Any]] = {}
    for stream in (
        raw_forum_posts,
        raw_github_signals,
        raw_youtube_signals,
        raw_health_signals,
    ):
        for row in stream:
            merged[row["id"]] = row

    columns = list(SIGNAL_SCHEMA.keys())
    rows = []
    for row in merged.values():
        created = row.get("created_at")
        staged = {key: row.get(key) for key in columns}
        staged["tier"] = row_tier(row)
        staged["source"] = row.get("source") or "unknown"
        staged["flow_day"] = (
            flow_day(parse_iso(created), cfg.timezone, cfg.drain_at).isoformat()
            if created
            else None
        )
        rows.append(staged)
    context.log.info("staged %d signal(s)", len(rows))
    return pl.DataFrame(rows, schema=SIGNAL_SCHEMA)
