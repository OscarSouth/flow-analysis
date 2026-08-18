"""Small shared helpers.

Deliberately thin, and deliberately not a metrics module: the flow-day
calendar moved to `metrics/calendar.py`, which is where the day boundary is
defined once and everything else derives from it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo


class PayloadShapeError(RuntimeError):
    """A request succeeded and still did not carry what it was supposed to.

    Separate from the HTTP errors each source raises: those say the call failed,
    this says the call worked and the payload is unusable. Both must be loud —
    a source that quietly returns nothing looks exactly like a quiet channel.
    """


def json_object(value: object, what: str) -> dict[str, Any]:
    """Assert that a decoded payload is an object, at the point it arrives.

    Every remote shape is a promise until it turns up. A `cast` would let a
    changed response travel on and fail somewhere unrelated — an AttributeError
    three modules away, blamed on the wrong code. This fails where it broke.
    """
    if not isinstance(value, dict):
        raise PayloadShapeError(
            f"{what}: expected an object, got {type(value).__name__}"
        )
    return value


def json_array(value: object, what: str) -> list[dict[str, Any]]:
    """The array counterpart of `json_object`, with the same reasoning.

    Only the outer shape is checked. Trello and GitHub both vary which *keys*
    come back depending on the `fields` requested, so element contents are not
    something a static promise could describe honestly.
    """
    if not isinstance(value, list):
        raise PayloadShapeError(
            f"{what}: expected an array, got {type(value).__name__}"
        )
    return value


def card_created_at(card_id: str) -> datetime:
    """When a card was created, read out of its own id.

    Trello object ids are Mongo ObjectIds: the first 8 hex chars are the creation
    time as a Unix epoch. Every card therefore self-reports when it was made,
    with no need to bake a date into the card name.
    """
    return datetime.fromtimestamp(int(card_id[:8], 16), tz=UTC)


def to_local(moment: datetime, tz_name: str) -> datetime:
    """Move a moment into the practice's timezone.

    A naive datetime is treated as UTC, which is what every stored timestamp is.
    Everything about the flow day is local, so this is where that starts.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(ZoneInfo(tz_name))


def parse_iso(value: str) -> datetime:
    """Trello emits e.g. '2026-08-16T05:00:00.000Z'."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
