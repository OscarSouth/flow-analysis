"""Raw assets — one per source stream, stored verbatim as fetched.

Nothing is reshaped here. The archive holds what the API said, so a later change
of mind about modelling never requires going back to an endpoint that may no
longer answer — GitHub traffic in particular is retained for 14 days only, and a
day not collected is gone for good.

Each asset declares which archive file it lands in, and the `JsonlIOManager`
does the writing. An unconfigured source yields no rows rather than failing: not
having authorised YouTube is a setup state, not a broken pipeline.
"""

# No `from __future__ import annotations` here on purpose: Dagster validates the
# `context` parameter and resolves resource parameters by inspecting the actual
# annotation objects, and stringified annotations fail both checks.

from datetime import date
from pathlib import Path
from typing import Any

from dagster import AssetExecutionContext, asset
from dagster import Config as AssetConfig

from .. import store
from ..config import Config
from ..io import RawStream
from ..resources import (
    FlowConfigResource,
    ForumResource,
    GitHubResource,
    HealthResource,
    TrelloResource,
    YouTubeResource,
)
from ..sync import fetch_actions, fetch_cards

# Dagster resolves these annotations at run time to work out which parameters are
# resources, so they cannot live in a TYPE_CHECKING block however much the linter
# would prefer it. `runtime-evaluated-decorators` in pyproject.toml tells ruff.

GROUP = "raw"


class ActionWalkConfig(AssetConfig):
    """How far back this run should walk.

    The defaults are the everyday case: extend forward from the watermark, and
    keep the action-type filter the archive was captured under. Both overrides
    exist to repair a gap — `flow sync --backfill` — and not to be scheduled.
    """

    backfill_from: str | None = None
    all_actions: bool = False


@asset(
    group_name=GROUP,
    metadata={"jsonl_stream": "actions"},
    description="Board actions, newest-first walk, verbatim.",
)
def raw_trello_actions(
    context: AssetExecutionContext,
    config: ActionWalkConfig,
    flow_config: FlowConfigResource,
    trello: TrelloResource,
) -> RawStream:
    """Every board action from `start_date` to now, incrementally.

    Trello serves actions newest-first, and each walk extends one end of a single
    unbroken interval, so coverage stays checkable from two endpoints. The
    watermark rides along with the rows: the IO manager saves it only once they
    have landed.
    """
    cfg = flow_config.load()
    backfill = (
        date.fromisoformat(config.backfill_from) if config.backfill_from else None
    )
    with trello.client() as client:
        fetched = fetch_actions(
            client,
            cfg,
            store.load_state(),
            backfill_from=backfill,
            all_actions=config.all_actions,
        )
    for warning in fetched.warnings:
        context.log.warning(warning)
    context.log.info(
        "fetched %d action(s) over %d page(s)", len(fetched.rows), fetched.pages
    )
    return RawStream(rows=fetched.rows, state=fetched.state)


@asset(
    group_name=GROUP,
    metadata={"jsonl_stream": "cards"},
    description="Card snapshots, open and archived, appended only when changed.",
)
def raw_trello_cards(
    context: AssetExecutionContext,
    flow_config: FlowConfigResource,
    trello: TrelloResource,
) -> RawStream:
    """Every card the board holds, including the archived ones.

    The closed pass is what makes the daily purge non-destructive for the
    analysis: Trello keeps archived cards indefinitely, so drained history is
    still readable.
    """
    cfg = flow_config.load()
    with trello.client() as client:
        rows = fetch_cards(client, cfg)
    context.log.info("observed %d card(s)", len(rows))
    return RawStream(rows=rows)


@asset(
    group_name=GROUP,
    metadata={"jsonl_stream": "signals"},
    description="Forum posts, tiered as production / internal_other / reception.",
)
def raw_forum_posts(
    context: AssetExecutionContext,
    flow_config: FlowConfigResource,
    forum: ForumResource,
) -> RawStream:
    """Every post on the forum, classified by author on the way in."""
    source = forum.source(flow_config.load())
    if source is None:
        context.log.info("no signals.forum block in config/board.yaml — skipping")
        return RawStream()
    rows = list(source.posts())
    context.log.info("fetched %d forum post(s)", len(rows))
    return RawStream(rows=rows)


@asset(
    group_name=GROUP,
    metadata={"jsonl_stream": "signals"},
    description="Stars, forks, watchers, and traffic — reception, never production.",
)
def raw_github_signals(
    context: AssetExecutionContext,
    flow_config: FlowConfigResource,
    github: GitHubResource,
) -> RawStream:
    """What the repository earned.

    Traffic is retained by GitHub for **14 days only**, which is the one genuinely
    time-sensitive thing in this project: stars backfill whenever we get to them,
    traffic does not.
    """
    source = github.source(flow_config.load())
    if source is None:
        context.log.info("no signals.github block in config/board.yaml — skipping")
        return RawStream()
    rows = list(source.rows())
    if not source.token:
        context.log.warning(
            "no GITHUB_TOKEN in .env, so only star/fork/watcher totals were "
            "collected. Traffic is retained for 14 days only."
        )
    context.log.info("fetched %d github row(s)", len(rows))
    return RawStream(rows=rows)


@asset(
    group_name=GROUP,
    metadata={"jsonl_stream": "signals"},
    description="Uploads (production) and settled daily analytics (reception).",
)
def raw_youtube_signals(
    context: AssetExecutionContext,
    flow_config: FlowConfigResource,
    youtube: YouTubeResource,
) -> RawStream:
    """Public uploads and exact per-day analytics.

    Only days old enough to have settled are fetched: the store dedupes on id and
    never updates, so a day written too early would be frozen at a partial figure.
    """
    source = youtube.source(flow_config.load())
    if source is None:
        context.log.info("youtube not configured or not authorised — skipping")
        return RawStream()
    rows = list(source.rows())
    context.log.info("fetched %d youtube row(s)", len(rows))
    return RawStream(rows=rows)


@asset(
    group_name=GROUP,
    metadata={"jsonl_stream": "signals"},
    description="Workouts and body measurements from an Apple Health export.",
)
def raw_health_signals(
    context: AssetExecutionContext,
    flow_config: FlowConfigResource,
    health: HealthResource,
) -> RawStream:
    """Embodiment: a second observer of Train, not an impact metric.

    The export is consumed and then **purged**, and only ever after a successful
    import — the zip is 35 MB of personal data sitting in a working directory, and
    everything read from it is already in the archive. No export present is the
    normal state, so it skips rather than failing.
    """
    source = health.source(flow_config.load())
    if source is None:
        context.log.info("no Apple Health export in ingest/ — skipping")
        return RawStream()
    rows = list(source.rows())
    context.log.info("read %d health row(s)", len(rows))
    return RawStream(rows=rows)


def purge_consumed_export(cfg: Config) -> list[str]:
    """Delete an export whose rows are stored. Called after a successful run.

    Deliberately *not* part of the asset: the asset returns rows and the IO
    manager writes them afterwards, so an asset that purged its own input would
    delete the export before knowing the rows had landed.
    """
    from ..sources import health

    source = health.source_from_config(cfg)
    if source is None:
        return []
    return source.purge()


MEMORY_FILE = Path(__file__).resolve().parents[3] / ".claude" / "memory.jsonl"


def _note_id(payload: dict[str, Any]) -> str:
    """A deterministic id from the note's content.

    No timestamp inside the hash: re-snapshotting an unchanged memory must
    produce the same id and dedupe to nothing, while any edit produces a new
    row — the archive keeps every state an entity has passed through.
    """
    import hashlib
    import json

    material = json.dumps(payload, sort_keys=True)
    return "note:" + hashlib.sha256(material.encode()).hexdigest()[:16]


@asset(
    group_name=GROUP,
    metadata={"jsonl_stream": "notes"},
    description="Validated snapshot of the agent's memory — the knowledge layer's raw.",
)
def raw_agent_memory(context: AssetExecutionContext) -> RawStream:
    """Snapshot the memory MCP's working file into the archive, validated.

    Validation happens HERE, before the truth, deviating from raw-verbatim
    doctrine deliberately: the memory file is agent-authored, not an external
    API, and the validating gate at capture is the whole consistency mechanism.
    A taxonomy mistake is cheap to fix in the working set (edit or delete the
    memory entity) and permanent everywhere after it — so a bad entity fails
    the asset loudly and nothing lands.

    The memory server rewrites its file on delete; the archive never rewrites.
    A deletion simply stops appearing in new snapshots. History stays.
    """
    from datetime import UTC, datetime

    from ..taxonomy import validate_entity, validate_relation

    if not MEMORY_FILE.exists():
        from .. import store

        archived = len(store.latest_notes(store.load_notes()))
        if archived:
            context.log.warning(
                "memory working set missing at %s while %d entit(ies) are "
                "archived — the graph is unaffected, but MCP recall is empty; "
                "`flow memory restore` rebuilds the file",
                MEMORY_FILE,
                archived,
            )
        else:
            context.log.info(
                "no memory working set at %s — nothing to promote", MEMORY_FILE
            )
        return RawStream()

    import json

    captured_at = datetime.now(UTC).isoformat()
    rows: list[dict[str, Any]] = []
    for line in MEMORY_FILE.read_text().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("type") == "entity":
            payload = validate_entity(item)
            payload["note_kind"] = "entity"
        elif item.get("type") == "relation":
            payload = validate_relation(item)
            payload["note_kind"] = "relation"
        else:
            continue
        rows.append({"id": _note_id(payload), "captured_at": captured_at, **payload})
    context.log.info("snapshot: %d note(s) from the memory working set", len(rows))
    return RawStream(rows=rows)


def working_set_entity_names() -> set[str]:
    """Entity names currently in the MCP working set; empty if the file is gone.

    Tolerant by design — this feeds the brief's drift check, which must be
    able to describe a corrupt file rather than crash on it.
    """
    import json

    if not MEMORY_FILE.exists():
        return set()
    names: set[str] = set()
    for line in MEMORY_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("type") == "entity" and item.get("name"):
            names.add(item["name"])
    return names


def restore_working_set(force: bool = False) -> tuple[int, int]:
    """Rebuild `.claude/memory.jsonl` from the archive's current state.

    The archive keeps observations verbatim, so the round-trip is lossless:
    a re-snapshot of the restored file appends nothing. Returns (entities,
    relations) written. Refuses to overwrite a non-empty working set unless
    forced — the working set may hold captures newer than the archive.
    """
    import json

    from .. import store
    from ..taxonomy import RELATION_TYPES

    if MEMORY_FILE.exists() and MEMORY_FILE.read_text().strip() and not force:
        raise RuntimeError(
            f"{MEMORY_FILE} is not empty — restoring would overwrite captures "
            "that may not be archived yet. Run `flow sync` first, then "
            "`flow memory restore --force`."
        )

    notes = store.load_notes()
    entities = store.latest_notes(notes)
    relations = store.relation_notes(notes)
    to_relation_key = {upper: lower for lower, upper in RELATION_TYPES.items()}

    lines = [
        json.dumps(
            {
                "type": "entity",
                "name": row["name"],
                "entityType": row["entity_type"],
                "observations": row["observations"],
            },
            sort_keys=True,
        )
        for row in entities.values()
    ]
    lines += [
        json.dumps(
            {
                "type": "relation",
                "from": row["from_name"],
                "to": row["to_name"],
                "relationType": to_relation_key[row["rel_type"]],
            },
            sort_keys=True,
        )
        for row in relations
    ]
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text("\n".join(lines) + ("\n" if lines else ""))
    return len(entities), len(relations)


RAW_ASSETS = [
    raw_trello_actions,
    raw_trello_cards,
    raw_forum_posts,
    raw_github_signals,
    raw_youtube_signals,
    raw_health_signals,
    raw_agent_memory,
]
