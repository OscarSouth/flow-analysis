"""Incremental, gap-checked history sync.

Design note — why coverage is trustworthy:

Trello serves board actions newest-first. Every fetch here either extends the
*newest* end of what we hold (`since=<newest action id>`) or the *oldest* end
(`before=<oldest action id>`), and both walk contiguously without skipping. So
the covered region is a single unbroken interval by construction, and integrity
reduces to comparing its two endpoints against the requested span. There is no
interval-merging to get wrong.

The run is idempotent: actions are keyed by immutable id and de-duplicated, so
re-running immediately adds nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from . import store
from .metrics.calendar import day_bounds, flow_day
from .util import parse_iso

if TYPE_CHECKING:
    from .client import TrelloClient
    from .config import Config

# The action types the daily flow model needs. Stored verbatim so re-analysis
# never has to go back to the API.
DEFAULT_ACTION_TYPES = "createCard,updateCard,copyCard,moveCardToBoard,deleteCard"


@dataclass
class SyncResult:
    """What one sync actually moved, for the summary and the integrity check.

    The covered window matters as much as the counts: knowing history is
    complete requires knowing which span was fetched, not just how much.
    """

    new_actions: int = 0
    new_card_rows: int = 0
    oldest_covered: str | None = None
    newest_covered: str | None = None
    pages_fetched: int = 0
    warnings: list[str] = field(default_factory=list)


def _span_for(cfg: Config) -> tuple[datetime, datetime, date, date] | None:
    """UTC bounds of the region history must cover: start_date .. last complete day.

    Returns None when no flow day has finished yet — the day in progress cannot
    be complete, so demanding coverage of it would be a false alarm.
    """
    if cfg.start_date is None:
        raise ValueError(
            "history.start_date is not set in config/board.yaml. Set it to the first "
            "day the flow system was live, so sync knows how far back to guarantee."
        )
    now = datetime.now(UTC)
    last_complete = flow_day(now, cfg.timezone, cfg.drain_at) - timedelta(days=1)
    if last_complete < cfg.start_date:
        return None
    start_utc, _ = day_bounds(cfg.start_date, cfg.timezone, cfg.drain_at)
    _, end_utc = day_bounds(last_complete, cfg.timezone, cfg.drain_at)
    return start_utc, end_utc, cfg.start_date, last_complete


@dataclass
class ActionFetch:
    """Actions pulled in one walk, and the watermark they justify advancing to.

    The two travel together because the order they are persisted in matters: the
    rows must land *before* the watermark moves, or a failed write would leave
    state claiming coverage the archive does not have — and `integrity()` reads
    the watermark, so the gap would report as OK.
    """

    rows: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    pages: int = 0
    warnings: list[str] = field(default_factory=list)


def fetch_actions(
    client: TrelloClient,
    cfg: Config,
    state: dict[str, Any],
    *,
    backfill_from: date | None = None,
    all_actions: bool = False,
) -> ActionFetch:
    """Walk the board's actions, forward from the watermark and back to the start.

    Fetches and returns; writes nothing. Trello serves actions newest-first, so
    each walk extends one end of a single unbroken interval — see the module
    docstring for why that makes coverage checkable from two endpoints.
    """
    board_id = cfg.require_board()
    fetched = ActionFetch(state=dict(state))

    action_types = None if all_actions else DEFAULT_ACTION_TYPES
    previous_filter = state.get("action_filter")
    if previous_filter is not None and previous_filter != (action_types or "ALL"):
        fetched.warnings.append(
            f"Action filter changed ({previous_filter!r} -> "
            f"{action_types or 'ALL'!r}). "
            "Existing history was captured under the old filter; run "
            "`flow sync --backfill --all-actions` to re-walk the full span."
        )

    oldest_seen = state.get("oldest_action_date")
    newest_seen = state.get("newest_action_date")
    oldest_id = state.get("oldest_action_id")
    newest_id = state.get("newest_action_id")

    # --- forward: everything newer than what we already hold -------------------
    pages = client.actions(board_id, since=newest_id, action_types=action_types)
    forward_newest: dict[str, Any] | None = None
    forward_oldest: dict[str, Any] | None = None
    for page in pages:
        fetched.pages += 1
        if forward_newest is None:
            forward_newest = page[0]
        forward_oldest = page[-1]
        fetched.rows.extend(page)

    if forward_newest:
        newest_id = forward_newest["id"]
        newest_seen = forward_newest["date"]
        if oldest_seen is None:
            oldest_seen = forward_oldest["date"] if forward_oldest else None
            oldest_id = forward_oldest["id"] if forward_oldest else None

    # --- backward: extend to the requested start ------------------------------
    target_start: datetime | None = None
    if backfill_from is not None:
        target_start, _ = day_bounds(backfill_from, cfg.timezone, cfg.drain_at)
    elif cfg.start_date is not None:
        target_start, _ = day_bounds(cfg.start_date, cfg.timezone, cfg.drain_at)

    if target_start and oldest_id and oldest_seen:
        while parse_iso(oldest_seen) > target_start:
            page_found = False
            for page in client.actions(
                board_id, before=oldest_id, action_types=action_types
            ):
                page_found = True
                fetched.pages += 1
                fetched.rows.extend(page)
                oldest_id = page[-1]["id"]
                oldest_seen = page[-1]["date"]
                if parse_iso(oldest_seen) <= target_start:
                    break
            if not page_found:
                # Trello has nothing older; the board itself starts here.
                break

    fetched.state.update(
        {
            "board_id": board_id,
            "action_filter": action_types or "ALL",
            "newest_action_id": newest_id,
            "newest_action_date": newest_seen,
            "oldest_action_id": oldest_id,
            "oldest_action_date": oldest_seen,
            "last_sync_at": datetime.now(UTC).isoformat(),
        }
    )
    return fetched


def fetch_cards(client: TrelloClient, cfg: Config) -> list[dict[str, Any]]:
    """Every card the board holds, open and archived.

    Archived cards are how drained history is recovered: Trello keeps them
    indefinitely unless explicitly deleted, so the closed pass is what makes the
    daily purge non-destructive from the analysis's point of view.
    """
    board_id = cfg.require_board()
    rows: list[dict[str, Any]] = []
    for card_filter in ("open", "closed"):
        rows.extend(client.cards(board_id, card_filter))
    return rows


def run(
    client: TrelloClient,
    cfg: Config,
    *,
    backfill_from: date | None = None,
    all_actions: bool = False,
) -> SyncResult:
    """Pull actions and card snapshots into the archive.

    Incremental by default, walking back only as far as the last sync stopped.
    `backfill_from` re-walks from a date instead, which is how a gap is repaired;
    re-running is always safe because both stores dedupe.

    Fetching lives in `fetch_actions` / `fetch_cards`; this is the Layer C half
    that persists what they return, rows before watermark.
    """
    fetched = fetch_actions(
        client,
        cfg,
        store.load_state(),
        backfill_from=backfill_from,
        all_actions=all_actions,
    )
    result = SyncResult(pages_fetched=fetched.pages, warnings=list(fetched.warnings))
    result.new_actions = store.append_actions(fetched.rows, store.known_action_ids())
    result.new_card_rows = store.append_cards(
        fetch_cards(client, cfg), store.known_card_fingerprints()
    )
    store.save_state(fetched.state)

    result.oldest_covered = fetched.state.get("oldest_action_date")
    result.newest_covered = fetched.state.get("newest_action_date")
    return result


def integrity(cfg: Config) -> dict[str, Any]:
    """Is the local store complete from start_date through yesterday?"""
    state = store.load_state()
    report: dict[str, Any] = {"ok": True, "problems": [], "notes": []}

    if not state:
        report["ok"] = False
        report["problems"].append("No sync has run yet. Run: flow sync")
        return report

    if cfg.start_date is None:
        report["ok"] = False
        report["problems"].append(
            "history.start_date is unset in config/board.yaml, so completeness "
            "cannot be asserted. Set it to the first day the system was live."
        )
        return report

    span = _span_for(cfg)
    if span is None:
        report["notes"].append(
            f"No flow day has completed yet (start_date {cfg.start_date}). "
            "Completeness becomes checkable after the first day boundary at "
            f"{cfg.drain_at.strftime('%H:%M')} {cfg.timezone}."
        )
        return report
    start_utc, end_utc, start_day, end_day = span
    report["required_span"] = [start_day.isoformat(), end_day.isoformat()]

    oldest = state.get("oldest_action_date")
    newest = state.get("newest_action_date")
    if not oldest or not newest:
        report["ok"] = False
        report["problems"].append("Store holds no actions. Run: flow sync")
        return report

    report["covered"] = [oldest, newest]

    if parse_iso(oldest) > start_utc:
        report["ok"] = False
        report["problems"].append(
            f"History starts at {oldest}, later than the required start "
            f"({start_utc.isoformat()}). Fix: flow sync --backfill"
        )
    if parse_iso(newest) < end_utc:
        report["ok"] = False
        report["problems"].append(
            f"History ends at {newest}, earlier than end of {end_day} "
            f"({end_utc.isoformat()}). Fix: flow sync"
        )

    if report["ok"]:
        report["notes"].append(
            f"Contiguous coverage {oldest} .. {newest} — complete for "
            f"{start_day} through {end_day}."
        )
    return report


def render_result(result: SyncResult, report: dict[str, Any]) -> str:
    """The sync summary, with the integrity verdict attached.

    The verdict prints with the counts rather than separately, because a
    successful-looking sync over an incomplete archive is exactly the failure
    this check exists to catch.
    """
    lines = [
        "Sync complete.",
        f"  pages fetched:    {result.pages_fetched}",
        f"  new actions:      {result.new_actions}",
        f"  new card rows:    {result.new_card_rows}",
        f"  covered:          {result.oldest_covered} .. {result.newest_covered}",
    ]
    for warning in result.warnings:
        lines += ["", f"  WARNING: {warning}"]
    lines += ["", "Integrity:"]
    if report.get("ok"):
        lines += [f"  OK — {note}" for note in report.get("notes", [])]
    else:
        lines += [f"  PROBLEM — {p}" for p in report.get("problems", [])]
    return "\n".join(lines)
