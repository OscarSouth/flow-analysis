"""The contract registry: completeness, vocabulary, and the trailing window.

The registry is the single source for measure names, gates and CSF typing —
a malformed entry would propagate everywhere, so its invariants are pinned
here rather than trusted.
"""

from __future__ import annotations

from datetime import date

import pytest

from flow_analysis.metrics.contracts import (
    CSF_COMPONENTS,
    PERSISTENCE_DAYS,
    REGISTRY,
    by_key,
    trailing,
)

VERDICTS = {"supported", "not supported", "inconclusive", "not testable yet"}


def test_registry_keys_are_unique_and_scheme_shaped():
    keys = [c.key for c in REGISTRY]
    assert len(keys) == len(set(keys))
    for contract in REGISTRY:
        assert contract.measure == f"contract:{contract.key}"


def test_every_component_is_csf_vocabulary():
    for contract in REGISTRY:
        assert contract.component in CSF_COMPONENTS, contract.key


def test_every_contract_has_a_positive_gate_and_a_valid_polarity():
    for contract in REGISTRY:
        assert contract.needs >= 1, contract.key
        assert contract.kind in {"posterior", "deterministic"}, contract.key
        assert contract.healthy_verdict in VERDICTS, contract.key
        if contract.window_days is not None:
            assert contract.window_days >= contract.needs or (
                contract.needs_unit != "days"
            ), contract.key


def test_c9_is_the_only_health_positive_contract():
    """Failure-positive is the convention; c9's floor is the exception."""
    positive = [c.key for c in REGISTRY if c.healthy_verdict == "supported"]
    assert positive == ["c9_publication_rate"]


def test_by_key_refuses_unknown_contracts():
    with pytest.raises(KeyError, match="no contract"):
        by_key("h1_train_most_never_started")


def test_persistence_is_at_least_a_week():
    assert PERSISTENCE_DAYS >= 7


def test_trailing_window_is_half_open_and_none_passes_through():
    rows = [{"day": f"2026-08-{d:02d}"} for d in range(1, 20)]
    today = date(2026, 8, 19)
    week = trailing(rows, 7, today)
    assert [r["day"] for r in week] == [
        "2026-08-13",
        "2026-08-14",
        "2026-08-15",
        "2026-08-16",
        "2026-08-17",
        "2026-08-18",
        "2026-08-19",
    ]
    assert trailing(rows, None, today) == rows
    assert trailing([{"day": None}, {}], 7, today) == []
