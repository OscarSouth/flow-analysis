"""Fold raw Trello actions into one row per (flow day, activity).

Layer B. The board is a moving picture and this is the still: cards and actions
are handed in, never loaded. That is what lets a Dagster asset feed the fold
from the IO manager without the fold reaching around it into the store.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from ..util import card_created_at, parse_iso
from .calendar import flow_day

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..config import Config

# Outcomes, worst to best. Ordering matters for the report's stacked summary.
NEVER_APPEARED = "never_appeared"
NEVER_STARTED = "never_started"
ABANDONED = "abandoned_in_progress"
COMPLETED = "completed"


@dataclass
class FlowRow:
    """One (day, activity) cell of the flow grid.

    A row exists for every activity on every day in the span, including days the
    card never appeared — absence is the finding the grid exists to make visible,
    so it must be a row rather than a missing key.
    """

    day: str
    activity: str
    outcome: str
    card_id: str | None = None
    appeared_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    archived_at: str | None = None
    minutes_to_start: float | None = None
    minutes_to_complete: float | None = None
    # Order this activity was pulled into `present` that day, 1-based. None if
    # never started. Reveals which modes get reached for first and which wait.
    pull_rank: int | None = None
    # How many other flow cards were already in `present` when this one started.
    interleaved: int | None = None

    @property
    def failure_kind(self) -> str | None:
        """Which kind of failure this was — see docs/06-diagnostics.md.

        Wiggins' generative uninspiration covers both, but the remedies are
        opposite: allocation wants time, capacity wants skill.
        """
        if self.outcome == NEVER_STARTED:
            return "allocation"
        if self.outcome == ABANDONED:
            return "capacity"
        return None

    def as_dict(self) -> dict[str, Any]:
        """Flatten for serialisation, with the derived failure kind included."""
        return asdict(self) | {"failure_kind": self.failure_kind}


def _flow_card_ids(
    cfg: Config, cards: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Cards that belong to the daily cycle.

    Membership is by the Flow label (what the purge rule keys off) intersected
    with the configured activity names (what the spawn rule creates). Requiring
    both keeps a stray hand-labelled card out of the statistics.
    """
    label_id = cfg.label_id
    activities = set(cfg.activities)
    out: dict[str, dict[str, Any]] = {}
    for card_id, card in cards.items():
        if card.get("name") not in activities:
            continue
        if label_id and not any(
            lb.get("id") == label_id for lb in card.get("labels", [])
        ):
            continue
        out[card_id] = card
    return out


def _transitions(
    actions: Iterable[dict[str, Any]], card_ids: set[str]
) -> dict[str, list[dict[str, Any]]]:
    """Per-card, time-ordered list of {at, to_list_id, closed}."""
    events: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        data = action.get("data") or {}
        card = data.get("card") or {}
        card_id = card.get("id")
        if card_id not in card_ids:
            continue

        entry: dict[str, Any] | None = None
        if action["type"] == "createCard":
            entry = {
                "at": action["date"],
                "to_list_id": (data.get("list") or {}).get("id"),
                "closed": False,
                "kind": "create",
            }
        elif action["type"] == "updateCard":
            if data.get("listAfter"):
                entry = {
                    "at": action["date"],
                    "to_list_id": data["listAfter"].get("id"),
                    "closed": False,
                    "kind": "move",
                }
            elif "closed" in (data.get("old") or {}) or card.get("closed") is not None:
                entry = {
                    "at": action["date"],
                    "to_list_id": None,
                    "closed": bool(card.get("closed")),
                    "kind": "archive",
                }
        if entry:
            events.setdefault(card_id, []).append(entry)

    for card_id in events:
        events[card_id].sort(key=lambda e: e["at"])
    return events


def _minutes(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return round((parse_iso(b) - parse_iso(a)).total_seconds() / 60.0, 1)


def latest_observation(
    rows: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """The most recent snapshot of each card, keyed by card id.

    The archive appends a card row only when its meaningful state changed, so a
    card has many rows and only the newest describes it now. `observed_at`
    decides rather than file order: the order happens to agree today, but a
    backfill that re-observed older state would quietly win otherwise.
    """
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        card_id = row.get("id")
        if not card_id:
            continue
        current = latest.get(card_id)
        if current is None or row["observed_at"] >= current["observed_at"]:
            latest[card_id] = row
    return latest


def fold_rows(
    cfg: Config,
    cards: dict[str, dict[str, Any]],
    actions: Iterable[dict[str, Any]],
) -> list[FlowRow]:
    """Fold observed cards and actions into the flow grid.

    Every card's journey through the lists is replayed from the actions, so the
    grid is derived from what happened rather than from what the board looks
    like today.

    `cards` is the latest observation per card id — `store.load_cards_latest()`
    in Layer C, an upstream asset under Dagster. Neither is this module's
    business.
    """
    lists = cfg.require_lists()
    present_id = lists["present"].id
    past_id = lists["past"].id

    flow_cards = _flow_card_ids(cfg, cards)
    events = _transitions(actions, set(flow_cards))

    rows: dict[tuple[str, str], FlowRow] = {}
    for card_id, card in flow_cards.items():
        spawned = card_created_at(card_id)
        day = flow_day(spawned, cfg.timezone, cfg.drain_at)
        key = (day.isoformat(), card["name"])

        started_at = completed_at = archived_at = None
        for event in events.get(card_id, []):
            if event["kind"] == "archive" and event["closed"] and archived_at is None:
                archived_at = event["at"]
            if event["to_list_id"] == present_id and started_at is None:
                started_at = event["at"]
            if event["to_list_id"] == past_id and completed_at is None:
                completed_at = event["at"]

        # A card sitting in Out with no recorded move (e.g. history predates the
        # store) still counts as complete.
        if completed_at is None and card.get("idList") == past_id:
            completed_at = card.get("observed_at")

        if completed_at:
            outcome = COMPLETED
        elif started_at:
            outcome = ABANDONED
        else:
            outcome = NEVER_STARTED

        spawned_iso = spawned.isoformat()
        row = FlowRow(
            day=key[0],
            activity=card["name"],
            outcome=outcome,
            card_id=card_id,
            appeared_at=spawned_iso,
            started_at=started_at,
            completed_at=completed_at,
            archived_at=archived_at,
            minutes_to_start=_minutes(spawned_iso, started_at),
            minutes_to_complete=_minutes(spawned_iso, completed_at),
        )

        # Duplicate (day, activity) can happen if a card was made by hand as well
        # as by the rule. Keep the better outcome so a manual completion counts.
        existing = rows.get(key)
        if existing is None or _rank(outcome) > _rank(existing.outcome):
            rows[key] = row

    _assign_pull_order(rows)
    return _fill_grid(cfg, rows)


def _assign_pull_order(rows: dict[tuple[str, str], FlowRow]) -> None:
    """Rank each day's activities by when they were first pulled into `present`.

    The refill drops the five in a random order, so pull order is a choice rather
    than an artefact of the list. Persistent last-place is a different signal from
    persistent never-started: one is deprioritised, the other is never reached.
    """
    by_day: dict[str, list[FlowRow]] = {}
    for (day, _activity), row in rows.items():
        if row.started_at:
            by_day.setdefault(day, []).append(row)

    for day_rows in by_day.values():
        day_rows.sort(key=lambda r: r.started_at or "")
        for rank, row in enumerate(day_rows, start=1):
            row.pull_rank = rank
            # Bound once: every row in `by_day` was filtered on `started_at`
            # above, but that guard lives on the other side of a dict and so
            # narrows nothing here.
            started = row.started_at or ""
            # How many were already open when this one began — started earlier
            # and either still running or finished after this one started.
            row.interleaved = sum(
                1
                for other in day_rows
                if other is not row
                and (other.started_at or "") < started
                and (other.completed_at is None or other.completed_at > started)
            )


def _rank(outcome: str) -> int:
    return {NEVER_APPEARED: 0, NEVER_STARTED: 1, ABANDONED: 2, COMPLETED: 3}[outcome]


def _fill_grid(cfg: Config, rows: dict[tuple[str, str], FlowRow]) -> list[FlowRow]:
    """Emit a row for every (day, activity) in the span.

    A day when the spawn rule silently failed shows up as never_appeared rather
    than vanishing from the record — the failure that is easiest to miss is the
    one where nothing appears at all.
    """
    if not rows:
        return []
    days = sorted({key[0] for key in rows})
    first = cfg.start_date or date.fromisoformat(days[0])
    last = date.fromisoformat(days[-1])

    complete: list[FlowRow] = []
    cursor = first
    while cursor <= last:
        iso = cursor.isoformat()
        for activity in cfg.activities:
            row = rows.get((iso, activity))
            complete.append(
                row or FlowRow(day=iso, activity=activity, outcome=NEVER_APPEARED)
            )
        cursor += timedelta(days=1)
    return complete


def to_dicts(rows: list[FlowRow]) -> list[dict[str, Any]]:
    """The grid as plain dicts, for the frames and the JSON surfaces."""
    return [row.as_dict() for row in rows]
