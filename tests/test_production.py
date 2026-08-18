"""Bucketing tiered events into flow days, and the tier filter that guards it.

Without the filter a stranger's star reads as your own output and
`adherence_without_production` says the opposite of the truth.
"""

from __future__ import annotations

from datetime import date, time

import pytest

from flow_analysis import store
from flow_analysis.fixtures import fixture_config
from flow_analysis.metrics.production import production_by_day, reception_by_day
from flow_analysis.tiers import (
    TIER_INTERNAL_OTHER,
    TIER_PRODUCTION,
    TIER_RECEPTION,
    row_tier,
)


@pytest.fixture
def store_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SIGNALS_PATH", tmp_path / "signals.jsonl")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


def test_an_org_mates_post_is_not_your_production(store_paths):
    """Someone else's post must not answer a question about your own output.

    `adherence_without_production` asks whether *your* practice produced
    anything.
    """
    cfg = fixture_config(date(2026, 7, 1))
    rows = [
        {
            "id": "a",
            "tier": TIER_INTERNAL_OTHER,
            "created_at": "2026-07-09T08:00:00+00:00",
        },
    ]
    assert production_by_day(cfg, rows) == {}
    assert reception_by_day(cfg, rows) == {}


def test_signals_append_is_idempotent(store_paths):
    rows = [
        {"id": "forum:post:1", "created_at": "2026-07-05T16:14:39+00:00"},
        {"id": "forum:post:2", "created_at": "2026-07-06T10:00:00+00:00"},
    ]
    known: set[str] = set()
    assert store.append_signals(rows, known) == 2
    assert store.append_signals(rows, known) == 0
    assert len(store.load_signals()) == 2


def test_production_buckets_on_the_flow_day_boundary(store_paths):
    """A post at 01:00 belongs to the previous day.

    The same 04:00 boundary the board uses: at 01:00 the cards have not yet been
    drained.
    """
    cfg = fixture_config(date(2026, 7, 1))
    assert cfg.drain_at == time(4, 0)

    rows = [
        # 01:00 on the 9th, London — before the boundary, so it counts to the 8th.
        {"id": "a", "created_at": "2026-07-09T00:00:00+00:00"},
        # 09:00 on the 9th — after the boundary, counts to the 9th.
        {"id": "b", "created_at": "2026-07-09T08:00:00+00:00"},
    ]
    production = production_by_day(cfg, rows)
    assert production == {"2026-07-08": 1, "2026-07-09": 1}


def test_reception_rows_cannot_inflate_production(store_paths):
    """The corruption hazard, pinned.

    `production_by_day` feeds `adherence_without_production` and `aberration`.
    If a reception row — someone else starring the repo, a stranger's forum post
    — were counted there, the board would read as if *you* had produced it, and
    the one measure that can detect quiet stagnation would say the opposite.
    """
    cfg = fixture_config(date(2026, 7, 1))
    own = [
        {
            "id": "p1",
            "tier": TIER_PRODUCTION,
            "created_at": "2026-07-09T08:00:00+00:00",
        },
    ]
    before = production_by_day(cfg, own)

    mixed = [
        *own,
        {
            "id": "r1",
            "tier": TIER_RECEPTION,
            "source": "github",
            "created_at": "2026-07-09T09:00:00+00:00",
        },
        {
            "id": "r2",
            "tier": TIER_RECEPTION,
            "source": "forum",
            "created_at": "2026-07-09T10:00:00+00:00",
        },
        # A level, not an occurrence: no event time, so it belongs to no day.
        {
            "id": "c1",
            "tier": TIER_RECEPTION,
            "source": "github",
            "metric": "stars",
            "observed_at": "2026-07-09T09:00:00+00:00",
            "value": 118,
        },
    ]
    assert production_by_day(cfg, mixed) == before

    # And the reception side sees exactly the two that are events.
    assert reception_by_day(cfg, mixed) == {"2026-07-09": 2}


def test_legacy_rows_without_a_tier_count_as_production(store_paths):
    """Rows predating the field were all your own forum posts."""
    cfg = fixture_config(date(2026, 7, 1))
    legacy = [{"id": "old", "created_at": "2026-07-09T08:00:00+00:00"}]
    assert row_tier(legacy[0]) == TIER_PRODUCTION
    assert production_by_day(cfg, legacy) == {"2026-07-09": 1}
