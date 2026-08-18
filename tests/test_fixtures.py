"""The synthetic store must contain the patterns the analysis claims to detect.

If these break, every downstream test is checking machinery against data that no
longer poses the question it was built to pose.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

import pytest

from flow_analysis import fixtures, store
from flow_analysis.metrics import diagnostics as dx
from flow_analysis.metrics import grid


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
    return fx, cfg, grid.fold_rows(cfg, store.load_cards_latest(), store.load_actions())


def test_grid_is_dense(seeded):
    fx, _cfg, rows = seeded
    assert len(rows) == len(fx.days) * len(fixtures.ACTIVITIES)


def test_card_ids_carry_appearance_time(seeded):
    """util.card_created_at reads the id, so a wrong id means a wrong day."""
    _fx, _cfg, rows = seeded
    for row in rows[:20]:
        assert row.appeared_at is not None


def test_all_three_outcomes_present(seeded):
    """Allocation failure and capacity failure must both occur.

    Otherwise the split that distinguishes them has nothing to distinguish.
    """
    _, _, rows = seeded
    seen = Counter(r.outcome for r in rows)
    assert seen[grid.COMPLETED] > 0
    assert seen[grid.NEVER_STARTED] > 0
    assert seen[grid.ABANDONED] > 0


def test_train_is_most_often_never_started(seeded):
    """Pre-registered hypothesis 1, from article 05."""
    _, _, rows = seeded
    counts = Counter(r.activity for r in rows if r.outcome == grid.NEVER_STARTED)
    assert counts.most_common(1)[0][0] == "Train"


def test_express_has_longest_start_latency(seeded):
    """Pre-registered hypothesis 2, from article 05."""
    _, _, rows = seeded
    medians = {}
    for activity in fixtures.ACTIVITIES:
        lat = sorted(
            r.minutes_to_start
            for r in rows
            if r.activity == activity and r.minutes_to_start is not None
        )
        medians[activity] = lat[len(lat) // 2]
    assert max(medians, key=medians.get) == "Express"


def test_write_missed_days_depress_the_others(seeded):
    """Pre-registered hypothesis 3, from article 05."""
    _, _, rows = seeded
    by_day: dict[str, dict[str, str]] = {}
    for row in rows:
        by_day.setdefault(row.day, {})[row.activity] = row.outcome

    with_write, without_write = [], []
    for outcomes in by_day.values():
        others = [a for a in fixtures.ACTIVITIES if a != "Write"]
        rate = sum(1 for a in others if outcomes.get(a) == grid.COMPLETED) / len(others)
        (
            with_write if outcomes.get("Write") == grid.COMPLETED else without_write
        ).append(rate)

    assert without_write, "fixture produced no Write-missed days"
    assert sum(with_write) / len(with_write) > sum(without_write) / len(without_write)


def test_dormant_channel_is_fully_closed(seeded):
    """Dormancy: a channel that is never attempted.

    No analogue in Wiggins' catalogue, because his systems always run.
    """
    fx, _, rows = seeded
    activity, lo, hi = "Absorb", 62, 78
    dormant_days = {d.isoformat() for d in fx.days[lo : hi + 1]}
    during = [r for r in rows if r.activity == activity and r.day in dormant_days]
    assert during
    assert all(r.outcome == grid.NEVER_STARTED for r in during)


def test_forum_signal_is_sparse_but_present(seeded):
    fx, _, _ = seeded
    assert 5 < len(fx.forum) < len(fx.days)


def test_synthesis_is_deterministic():
    a = fixtures.synthesize(days=30, seed=3)
    b = fixtures.synthesize(days=30, seed=3)
    assert [x["id"] for x in a.actions] == [x["id"] for x in b.actions]
    assert fixtures.synthesize(days=30, seed=4).forum != a.forum


@pytest.mark.parametrize("offset", range(7))
def test_the_failure_split_survives_every_weekday(tmp_path, monkeypatch, offset):
    """Train fails by allocation and Express by capacity, whatever day it ends on.

    The seed fixes the random stream but `end` defaults to yesterday, so the
    weekend modifiers slide against that stream as the real calendar advances.
    Express used to sit at a 0.50 never-start rate, which meant the intended
    split only appeared when `end` landed on a Sunday: the test asserting it
    passed on Mondays and failed the other six days, silently, for as long as it
    existed. Sweeping a whole week is what makes that impossible to reintroduce.
    """
    monkeypatch.setattr(store, "ACTIONS_PATH", tmp_path / "actions.jsonl")
    monkeypatch.setattr(store, "CARDS_PATH", tmp_path / "cards.jsonl")
    monkeypatch.setattr(store, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)

    end = fixtures.REFERENCE_END + timedelta(days=offset)
    fx = fixtures.synthesize(days=120, end=end)
    store.append_actions(fx.actions, set())
    store.append_cards(fx.cards, set())
    cfg = fixtures.fixture_config(fx.days[0])

    rows = grid.fold_rows(cfg, store.load_cards_latest(), store.load_actions())
    value = dx.allocation_vs_capacity(rows, cfg.activities).value

    assert value["Train"]["dominant"] == "allocation", f"end={end:%Y-%m-%d %a}"
    assert value["Express"]["dominant"] == "capacity", f"end={end:%Y-%m-%d %a}"
