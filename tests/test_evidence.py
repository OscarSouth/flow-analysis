"""The review pack, and its refusals.

The pack exists so a prepared prompt never has to compute anything. Its job is
therefore to be right about the numbers *and* honest about which numbers it does
not have.
"""

from __future__ import annotations

import collections
from typing import TYPE_CHECKING

import pytest

from flow_analysis import evidence as ev
from flow_analysis import fixtures, store
from flow_analysis.metrics import grid
from flow_analysis.metrics.calendar import flow_day
from flow_analysis.util import parse_iso

if TYPE_CHECKING:
    from flow_analysis.config import Config
    from flow_analysis.metrics.grid import FlowRow


def _seed(
    tmp_path, monkeypatch, days: int
) -> tuple[Config, list[FlowRow], dict[str, int]]:
    monkeypatch.setattr(store, "ACTIONS_PATH", tmp_path / "actions.jsonl")
    monkeypatch.setattr(store, "CARDS_PATH", tmp_path / "cards.jsonl")
    monkeypatch.setattr(store, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)

    fx = fixtures.synthesize(days=days, end=fixtures.REFERENCE_END)
    store.append_actions(fx.actions, set())
    store.append_cards(fx.cards, set())
    cfg = fixtures.fixture_config(fx.days[0])
    rows = grid.fold_rows(cfg, store.load_cards_latest(), store.load_actions())
    production: collections.Counter = collections.Counter()
    for post in fx.forum:
        production[
            flow_day(
                parse_iso(post["created_at"]), cfg.timezone, cfg.drain_at
            ).isoformat()
        ] += 1
    return cfg, rows, dict(production)


@pytest.fixture
def full(tmp_path, monkeypatch):
    return _seed(tmp_path, monkeypatch, 120)


@pytest.fixture
def thin(tmp_path, monkeypatch):
    return _seed(tmp_path, monkeypatch, 9)


def test_window_takes_the_last_n_days(full):
    cfg, rows, production = full
    pack = ev.build(cfg, rows, production, [], window=28)

    assert pack["n_days_window"] == 28
    assert pack["n_days_total"] == 120
    # And the prior window is the 28 days before those, not an overlap.
    windowed = {r.day for r in ev.window_rows(rows, 28)}
    prior = {
        r.day for r in ev.window_rows([r for r in rows if r.day not in windowed], 28)
    }
    assert not (windowed & prior)
    assert max(prior) < min(windowed)


def test_patterns_refuse_below_the_rate_gate(thin):
    """A prescription to transform R or T must not come from nine days."""
    cfg, rows, production = thin
    pack = ev.build(cfg, rows, production, [], window=28)

    assert pack["patterns"]["ok"] is False
    assert pack["patterns"]["fired"] == []
    assert "Not evaluated" in ev.render(pack)


def test_a_pattern_needs_a_real_gap_before_it_fires():
    """Two rates a few points apart is noise, and noise must not prescribe."""
    activities = ["Write", "Absorb", "Train", "Express", "Reveal"]
    table = {a: {"rate": 0.5} for a in activities}

    # A gap under the margin fires nothing.
    table["Express"]["rate"] = 0.5 + ev.MARGIN - 0.01
    table["Train"]["rate"] = 0.5
    assert ev.firings(table, n_days=60, activities=activities)["fired"] == []

    # Clearing it fires exactly the row the table says it should.
    table["Express"]["rate"] = 0.5 + ev.MARGIN + 0.01
    fired = ev.firings(table, n_days=60, activities=activities)["fired"]
    assert [f["key"] for f in fired] == ["ideas_without_execution"]
    assert fired[0]["at_fault"] == "T"
    assert fired[0]["csf_mode"] == "generative uninspiration"


def test_renamed_activities_drop_the_rows_that_no_longer_apply():
    """The table is written in terms of the five names; a rename retires a row."""
    activities = ["Write", "Absorb", "Practice", "Express", "Reveal"]
    table = {a: {"rate": 0.5} for a in activities}
    table["Express"]["rate"] = 0.95  # would fire ideas_without_execution vs Train

    fired = ev.firings(table, n_days=60, activities=activities)["fired"]
    assert all(f["key"] != "ideas_without_execution" for f in fired)


def test_render_states_its_own_adequacy(thin):
    cfg, rows, production = thin
    text = ev.render(ev.build(cfg, rows, production, [], window=28))

    assert "insufficient data" in text
    assert "Still underpowered" in text
    # The standing caveat is never optional.
    assert "Nothing here is causal" in text


def test_render_on_a_full_history_carries_numbers_not_dicts(full):
    cfg, rows, production = full
    text = ev.render(ev.build(cfg, rows, production, [], window=28))

    assert "{'" not in text, "a raw dict reached the rendered pack"
    assert "Pre-registered hypotheses" in text
    assert "Nothing here is causal" in text
