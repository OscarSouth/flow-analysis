"""The reshaping layer, and the two places where a plausible-looking frame lies.

Both tests here are regressions for bugs that rendered without erroring — the
kind the charts happily draw and a reader then believes.
"""

from __future__ import annotations

import collections
from datetime import timedelta

import polars as pl
import pytest

from flow_analysis import fixtures, store
from flow_analysis.metrics import frames as fr
from flow_analysis.metrics import grid
from flow_analysis.metrics.calendar import flow_day
from flow_analysis.util import parse_iso


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ACTIONS_PATH", tmp_path / "actions.jsonl")
    monkeypatch.setattr(store, "CARDS_PATH", tmp_path / "cards.jsonl")
    monkeypatch.setattr(store, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)

    fx = fixtures.synthesize(days=120, end=fixtures.REFERENCE_END)
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


def test_rolling_window_is_trailing_and_drops_the_lead_in(seeded):
    """A forward window both shifts the curve early and ends on empty windows.

    The visible symptom was a dramatic collapse-or-spike in the final weeks that
    was nothing but the window running out of days to average.
    """
    _cfg, rows, _production = seeded
    grid = fr.grid_frame(rows)
    rolling = fr.rolling_rate(grid, windows=(28,))

    observed = grid.filter(pl.col("outcome") != "never_appeared")
    first, last = observed["day"].min(), observed["day"].max()

    # No point before a full window exists to average.
    assert rolling["day"].min() == first + timedelta(days=27)
    # And the series runs right up to the end rather than trailing off.
    assert rolling["day"].max() == last

    # Each point averages a full window: five modes over 28 days, minus any day
    # the mode never appeared. It must never be a handful of stragglers.
    assert rolling["n"].min() >= 20


def test_rolling_rate_matches_a_hand_computed_window(seeded):
    """Spot-check one point against the definition, not against itself."""
    _cfg, rows, _production = seeded
    grid = fr.grid_frame(rows)
    rolling = fr.rolling_rate(grid, windows=(28,))

    point = (
        rolling.sort("day").filter(pl.col("activity") == "Write").row(-1, named=True)
    )
    window_start = point["day"] - timedelta(days=27)
    expected = (
        grid.filter(
            (pl.col("activity") == "Write")
            & (pl.col("outcome") != "never_appeared")
            & (pl.col("day") >= window_start)
            & (pl.col("day") <= point["day"])
        )
        .select((pl.col("outcome") == "completed").mean())
        .item()
    )
    assert point["rate"] == pytest.approx(expected)


def test_store_redirect_leaves_the_real_paths_alone(tmp_path):
    """Fabricated rows must not be able to reach the real history.

    The store is append-only and dedupes on id, so a fixture write into the live
    files is not undoable through any normal command.
    """
    before = (store.DATA_DIR, store.ACTIONS_PATH, store.CARDS_PATH, store.SIGNALS_PATH)

    with store.redirect(tmp_path):
        assert tmp_path / "actions.jsonl" == store.ACTIONS_PATH
        store.append_actions(
            [{"id": "fake", "date": "2026-01-01T00:00:00.000Z"}], set()
        )
        assert (tmp_path / "actions.jsonl").exists()

    assert before == (
        store.DATA_DIR,
        store.ACTIONS_PATH,
        store.CARDS_PATH,
        store.SIGNALS_PATH,
    )


def test_store_redirect_restores_paths_after_a_failure(tmp_path):
    before = store.ACTIONS_PATH
    with pytest.raises(RuntimeError), store.redirect(tmp_path):
        raise RuntimeError("boom")
    assert before == store.ACTIONS_PATH
