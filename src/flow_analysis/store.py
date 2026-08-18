"""Append-only local store: actions, card snapshots, and sync state."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import DATA_DIR
from .util import json_object

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

ACTIONS_PATH = DATA_DIR / "actions.jsonl"
CARDS_PATH = DATA_DIR / "cards.jsonl"
STATE_PATH = DATA_DIR / "state.json"
# External production signal (forum posts). Trello can only record that the
# practice ran; this records whether anything came of it.
SIGNALS_PATH = DATA_DIR / "signals.jsonl"
# The knowledge layer's truth: validated snapshots of the agent's memory —
# reviews, interpretations, prescriptions, transformations. The memory MCP's
# working file is mutable; this is the append-only record it promotes into.
NOTES_PATH = DATA_DIR / "notes.jsonl"


def ensure_data_dir() -> None:
    """Create the archive directory. Every write path calls this first."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


@contextmanager
def redirect(data_dir: Path) -> Iterator[None]:
    """Point the store at another directory for the duration of the block.

    Fabricated data must never reach the real history — the store is
    append-only and dedupes on id, so a fixture write is not undoable through
    the normal path. Anything generating fixtures wraps its writes in this.
    """
    global DATA_DIR, ACTIONS_PATH, CARDS_PATH, STATE_PATH, SIGNALS_PATH, NOTES_PATH
    saved = (DATA_DIR, ACTIONS_PATH, CARDS_PATH, STATE_PATH, SIGNALS_PATH, NOTES_PATH)
    DATA_DIR = Path(data_dir)
    ACTIONS_PATH = DATA_DIR / "actions.jsonl"
    CARDS_PATH = DATA_DIR / "cards.jsonl"
    STATE_PATH = DATA_DIR / "state.json"
    SIGNALS_PATH = DATA_DIR / "signals.jsonl"
    NOTES_PATH = DATA_DIR / "notes.jsonl"
    try:
        yield
    finally:
        (
            DATA_DIR,
            ACTIONS_PATH,
            CARDS_PATH,
            STATE_PATH,
            SIGNALS_PATH,
            NOTES_PATH,
        ) = saved


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Stream one JSON object per line, tolerating a missing file.

    A missing file is an empty history, not an error: the first sync on a fresh
    machine reads before it writes.
    """
    if not path.exists():
        return
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    """Append rows and return how many landed.

    Append-only by design. This archive is the only copy of history older than
    Trello's 1,000-action export cap, so nothing here ever rewrites or truncates.
    Keys are sorted so a diff of the file shows changed data, not reordering.
    """
    ensure_data_dir()
    count = 0
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            count += 1
    return count


# --- actions ---------------------------------------------------------------


def known_action_ids() -> set[str]:
    """Every action id already stored, for the dedupe on the next append."""
    return {row["id"] for row in read_jsonl(ACTIONS_PATH)}


def append_actions(actions: Iterable[dict[str, Any]], known: set[str]) -> int:
    """Append only actions not already stored.

    Action ids are immutable, so this makes overlapping fetch windows and
    repeated runs harmless — which is what lets `sync` be run at any time,
    as often as you like, without thinking about it.
    """
    fresh = []
    for action in actions:
        if action["id"] in known:
            continue
        known.add(action["id"])
        fresh.append(action)
    return append_jsonl(ACTIONS_PATH, fresh)


def load_actions() -> list[dict[str, Any]]:
    """The whole action history, oldest first. The board's own timestamps."""
    return sorted(read_jsonl(ACTIONS_PATH), key=lambda a: a["date"])


# --- card snapshots --------------------------------------------------------


def _card_fingerprint(card: dict[str, Any]) -> str:
    """Hash the fields whose change is worth a new row.

    Deliberately excludes `dateLastActivity`: it moves on any touch, which would
    write a new snapshot for every card on every sync and drown the real edits.
    """
    material = json.dumps(
        {
            "id": card.get("id"),
            "name": card.get("name"),
            "idList": card.get("idList"),
            "closed": card.get("closed"),
            "labels": sorted(lb.get("id", "") for lb in card.get("labels", [])),
            "due": card.get("due"),
            "dueComplete": card.get("dueComplete"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def known_card_fingerprints() -> set[str]:
    """Every card state already stored, for the dedupe on the next append."""
    return {
        row["fingerprint"] for row in read_jsonl(CARDS_PATH) if "fingerprint" in row
    }


def append_cards(cards: Iterable[dict[str, Any]], known: set[str]) -> int:
    """Append a card row only when its meaningful state has changed.

    The fingerprint covers the fields the analysis reads, so a full weekly pull
    of every card costs almost nothing on disk: unchanged cards write no row.
    """
    now = datetime.now(UTC).isoformat()
    fresh = []
    for card in cards:
        fingerprint = _card_fingerprint(card)
        if fingerprint in known:
            continue
        known.add(fingerprint)
        fresh.append({**card, "fingerprint": fingerprint, "observed_at": now})
    return append_jsonl(CARDS_PATH, fresh)


def load_cards_latest() -> dict[str, dict[str, Any]]:
    """Most recent observation per card id.

    The reduction itself lives in `metrics.grid.latest_observation`, so the
    Dagster asset — which receives card rows from the IO manager rather than
    reading this file — collapses them exactly the same way.
    """
    from .metrics.grid import latest_observation

    return latest_observation(read_jsonl(CARDS_PATH))


# --- external signals ------------------------------------------------------


def known_signal_ids() -> set[str]:
    """Every signal id already stored, for the dedupe on the next append."""
    return {row["id"] for row in read_jsonl(SIGNALS_PATH)}


def append_signals(signals: Iterable[dict[str, Any]], known: set[str]) -> int:
    """Append only signals not already stored.

    Ids are deterministic fingerprints where the source gives no stable one, so
    re-importing an overlapping export is free rather than duplicating history.
    """
    fresh = []
    for signal in signals:
        if signal["id"] in known:
            continue
        known.add(signal["id"])
        fresh.append(signal)
    return append_jsonl(SIGNALS_PATH, fresh)


def _signal_time(row: dict[str, Any]) -> str:
    """When a signal row happened, or failing that when it was observed.

    Event rows (a post, a star) carry `created_at`; counter and window rows are
    levels rather than occurrences and carry only `observed_at`. Sorting must
    tolerate both, or adding a level breaks every reader of the store.
    """
    return row.get("created_at") or row.get("observed_at") or ""


def load_signals() -> list[dict[str, Any]]:
    """Every signal, ordered by when it happened rather than when it was seen."""
    return sorted(read_jsonl(SIGNALS_PATH), key=_signal_time)


# --- knowledge notes ---------------------------------------------------------


def known_note_ids() -> set[str]:
    """Every note id already stored, for the dedupe on the next append."""
    return {row["id"] for row in read_jsonl(NOTES_PATH)}


def append_notes(notes: Iterable[dict[str, Any]], known: set[str]) -> int:
    """Append only notes not already stored.

    Ids are content hashes, so re-snapshotting an unchanged memory adds
    nothing, and an *edited* memory entity lands as a new row — the record
    keeps every state an entity has passed through.
    """
    fresh = []
    for note in notes:
        if note["id"] in known:
            continue
        known.add(note["id"])
        fresh.append(note)
    return append_jsonl(NOTES_PATH, fresh)


def load_notes() -> list[dict[str, Any]]:
    """Every archived note, in append order — capture order, by construction."""
    return list(read_jsonl(NOTES_PATH))


# --- state -----------------------------------------------------------------


def load_state() -> dict[str, Any]:
    """Sync bookkeeping: where the last incremental pull stopped.

    Derived, not history — losing it costs one full re-fetch, nothing more.
    """
    if not STATE_PATH.exists():
        return {}
    return json_object(json.loads(STATE_PATH.read_text()), str(STATE_PATH))


def save_state(state: dict[str, Any]) -> None:
    """Write the sync bookkeeping back, formatted to stay readable by eye."""
    ensure_data_dir()
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
