"""Trello, as a resource.

The board is the practice's own record: Butler moves the cards, and this reads
what it did. Only ever read here — the two write paths this repo has (`bootstrap`
and `refill`) stay in the CLI, because the daily cycle belongs to Butler and
nothing scheduled on this machine should be able to touch the board.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from dagster import ConfigurableResource

from ..client import client_from_env

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ..client import TrelloClient


class TrelloResource(ConfigurableResource["TrelloResource"]):
    """A pooled Trello client, with the retry policy the archive depends on.

    Credentials come from `.env` via `client_from_env`, not from Dagster config:
    a token in run config would be visible in the UI and stored with the run.
    """

    @contextmanager
    def client(self) -> Iterator[TrelloClient]:
        """A client for the duration of one asset, closed on the way out."""
        with client_from_env() as client:
            yield client
