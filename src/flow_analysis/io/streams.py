"""The three archive streams, and how each one dedupes.

One table, because the dedupe key is the thing that must not drift: actions key
on Trello's immutable action id, signals on a deterministic row id, and cards on
a content fingerprint — cards being the odd one out, since a card is re-observed
constantly and only a *changed* card is worth a new row.

Every function here delegates to `store`, which has always owned these files.
Nothing in this module reimplements appending; it only says which appender goes
with which stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .. import store

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@dataclass(frozen=True)
class RawStream:
    """What a raw asset hands to the IO manager.

    `state` travels with the rows so the two can be persisted in the right
    order — rows first, then the watermark that claims them. Streams with no
    watermark leave it None.
    """

    rows: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] | None = None


@dataclass(frozen=True)
class Stream:
    """One archive file: where it lives, how it dedupes, how it reads back."""

    name: str
    append: Callable[[list[dict[str, Any]]], int]
    load: Callable[[], list[dict[str, Any]]]
    path: Callable[[], Path]


def _append_actions(rows: list[dict[str, Any]]) -> int:
    return store.append_actions(rows, store.known_action_ids())


def _append_cards(rows: list[dict[str, Any]]) -> int:
    return store.append_cards(rows, store.known_card_fingerprints())


def _append_signals(rows: list[dict[str, Any]]) -> int:
    return store.append_signals(rows, store.known_signal_ids())


def _append_notes(rows: list[dict[str, Any]]) -> int:
    return store.append_notes(rows, store.known_note_ids())


# Paths are read through lambdas rather than captured at import: `store.redirect`
# rebinds them, and a fixture run must not write into `data/`.
STREAMS: dict[str, Stream] = {
    "actions": Stream(
        name="actions",
        append=_append_actions,
        load=store.load_actions,
        path=lambda: store.ACTIONS_PATH,
    ),
    "cards": Stream(
        name="cards",
        append=_append_cards,
        load=lambda: list(store.read_jsonl(store.CARDS_PATH)),
        path=lambda: store.CARDS_PATH,
    ),
    "signals": Stream(
        name="signals",
        append=_append_signals,
        load=store.load_signals,
        path=lambda: store.SIGNALS_PATH,
    ),
    "notes": Stream(
        name="notes",
        append=_append_notes,
        load=store.load_notes,
        path=lambda: store.NOTES_PATH,
    ),
}
