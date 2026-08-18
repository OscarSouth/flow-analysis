"""The JSON shape guards — a 200 that carries the wrong thing must be loud.

These exist because the alternative is a `cast`, which tells the type checker a
story and leaves the caller to fail somewhere unrelated. Every remote payload in
this repo passes through one of these two functions on the way in.
"""

from __future__ import annotations

import pytest

from flow_analysis.util import PayloadShapeError, json_array, json_object


def test_object_passes_through_unchanged():
    payload = {"id": "abc", "name": "Write"}
    assert json_object(payload, "whoami") is payload


def test_array_passes_through_unchanged():
    payload = [{"id": "abc"}, {"id": "def"}]
    assert json_array(payload, "cards") is payload


@pytest.mark.parametrize("value", [[], ["a"], "a string", 3, None, True], ids=type)
def test_an_object_that_is_not_an_object_raises(value):
    """Trello returns an array from some endpoints and an object from others.

    Requesting one and receiving the other is a real failure mode — the `fields`
    parameter and the path both shape the response — and it must not travel on
    to be discovered three modules away as an AttributeError.
    """
    with pytest.raises(PayloadShapeError):
        json_object(value, "board")


@pytest.mark.parametrize("value", [{}, {"a": 1}, "a string", 3, None], ids=type)
def test_an_array_that_is_not_an_array_raises(value):
    with pytest.raises(PayloadShapeError):
        json_array(value, "cards")


def test_the_message_names_the_call_and_what_arrived():
    """The point of failing here is being told where — so the message says so."""
    with pytest.raises(PayloadShapeError) as caught:
        json_object(["not", "an", "object"], "my_boards")

    message = str(caught.value)
    assert "my_boards" in message
    assert "list" in message


def test_an_empty_object_is_a_valid_object():
    """Empty is a shape, not a failure: a board with no labels returns `{}`."""
    assert json_object({}, "labels") == {}
    assert json_array([], "labels") == []
