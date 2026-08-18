"""Config — the `require_*` family, which exists to fail with instructions.

An unresolved id is not an error to be handled; it means a setup step has not
run. Every message here names the command that fixes it, because these surface
to someone at a terminal.
"""

from __future__ import annotations

from datetime import date

import pytest

from flow_analysis.config import ConfigError
from flow_analysis.fixtures import fixture_config


@pytest.fixture
def cfg():
    return fixture_config(date(2026, 8, 16))


def test_a_resolved_role_gives_back_its_id(cfg):
    assert cfg.require_list_id("future") == cfg.lists["future"].id


def test_an_unresolved_list_names_the_command_that_resolves_it(cfg):
    """`require_lists` fails on the whole set, not one role at a time.

    A half-resolved board breaks the drain in ways that read as missing data
    rather than as a missing id, so the check is deliberately all-or-nothing.
    """
    cfg.lists["past"].id = None

    with pytest.raises(ConfigError) as caught:
        cfg.require_list_id("future")

    message = str(caught.value)
    assert "past" in message
    assert "flow bootstrap --apply" in message


def test_the_guarantee_is_stated_once_rather_than_per_caller(cfg):
    """The point of the helper: callers get `str`, not `str | None`.

    `require_lists` already raises on unresolved ids, but hands back `ListRole`
    with an optional `id`, so every call site was re-deriving that guarantee.
    """
    list_id = cfg.require_list_id("present")

    assert isinstance(list_id, str)
    assert list_id


def test_an_unknown_role_is_a_programming_error_not_a_setup_one(cfg):
    """An unknown role is a typo in this repo, not a problem on the board.

    It must not be dressed up as something `flow bootstrap --apply` can fix.
    """
    with pytest.raises(KeyError):
        cfg.require_list_id("presnet")
