"""The Trello client — retries, and the shape check on the way back in.

No network. `request` is stubbed, so what is under test is the layer above it:
the typed wrappers that promise a dict or a list to everything downstream.
"""

from __future__ import annotations

from typing import Any

import pytest

from flow_analysis.client import TrelloClient
from flow_analysis.util import PayloadShapeError


class _Stub(TrelloClient):
    """A client whose transport returns whatever the test hands it."""

    def __init__(self, payload: Any) -> None:  # noqa: ANN401 - whatever JSON arrived
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def request(
        self, method: str, path: str, params: dict[str, Any] | None = None
    ) -> Any:  # noqa: ANN401 - matches the real transport's return
        self.calls.append((method, path))
        return self.payload


def test_an_object_endpoint_returning_an_array_fails_at_the_boundary():
    """The alternative is an AttributeError three modules away.

    `whoami` promises a dict to everything downstream; if Trello ever answers
    with something else, the failure belongs here, named, rather than wherever
    the first `.get()` happens to run.
    """
    client = _Stub([{"id": "x"}])

    with pytest.raises(PayloadShapeError, match="whoami"):
        client.whoami()


def test_a_list_endpoint_returning_an_object_fails_at_the_boundary():
    client = _Stub({"message": "unauthorized"})

    with pytest.raises(PayloadShapeError, match="cards"):
        client.cards("board123")


def test_a_well_shaped_response_passes_straight_through():
    client = _Stub({"id": "me", "username": "oscarsouth"})

    assert client.whoami() == {"id": "me", "username": "oscarsouth"}
    assert client.calls == [("GET", "/members/me")]


def test_an_empty_list_is_a_valid_answer():
    """A board with no labels is a fact, not a failure."""
    client = _Stub([])
    assert client.labels("board123") == []
