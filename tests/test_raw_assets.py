"""Raw assets — what they do when a source is not configured, and what they store.

No network: sources are stubbed. What is under test is the asset layer's own
behaviour, not the sources', which have their own tests.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import pytest
from dagster import build_asset_context, materialize

from flow_analysis import store
from flow_analysis.assets import RAW_ASSETS
from flow_analysis.assets import raw as raw_assets
from flow_analysis.fixtures import fixture_config
from flow_analysis.io import JsonlIOManager
from flow_analysis.resources import (
    ForumResource,
    GitHubResource,
    HealthResource,
    YouTubeResource,
)
from flow_analysis.tiers import TIER_RECEPTION

if TYPE_CHECKING:
    from collections.abc import Iterator

    from flow_analysis.config import Config


class _StubConfig:
    """Stands in for FlowConfigResource without reading config/board.yaml."""

    def load(self) -> Config:
        return fixture_config(date(2026, 8, 16))


class _NoSource:
    """A resource for a source that is not configured — the normal state."""

    def source(self, cfg) -> None:
        return None


@pytest.fixture
def archive(tmp_path):
    with store.redirect(tmp_path):
        yield tmp_path


@pytest.mark.parametrize(
    ("asset_fn", "resource_kwarg"),
    [
        (raw_assets.raw_forum_posts, "forum"),
        (raw_assets.raw_github_signals, "github"),
        (raw_assets.raw_youtube_signals, "youtube"),
        (raw_assets.raw_health_signals, "health"),
    ],
)
def test_an_unconfigured_source_yields_nothing_rather_than_failing(
    archive, asset_fn, resource_kwarg
):
    """Not having authorised YouTube is a setup state, not a broken pipeline.

    The run must stay green so the *other* sources still land — GitHub traffic is
    retained for 14 days only, and losing a day to an unrelated missing
    credential would cost data that cannot be re-fetched.
    """
    result = asset_fn(
        context=build_asset_context(),
        flow_config=_StubConfig(),
        **{resource_kwarg: _NoSource()},
    )
    assert result.rows == []
    assert result.state is None


def test_a_configured_source_stores_its_rows_through_the_io_manager(archive):
    """End to end for one asset: fetch, dedupe, land in signals.jsonl."""

    class _Rows:
        def source(self, cfg) -> _Rows:
            return self

        def posts(self) -> Iterator[dict[str, Any]]:
            yield {
                "id": "forum:post:1",
                "tier": TIER_RECEPTION,
                "created_at": "2026-08-17T09:00:00+00:00",
            }

    result = materialize(
        [raw_assets.raw_forum_posts],
        resources={
            "io_manager": JsonlIOManager(),
            "flow_config": _StubConfig(),
            "forum": _Rows(),
        },
    )

    assert result.success
    assert [row["id"] for row in store.load_signals()] == ["forum:post:1"]


def test_every_raw_asset_declares_where_its_rows_land(archive):
    """The IO manager refuses an undeclared stream, so this is the paired check."""
    for asset_def in RAW_ASSETS:
        for key, metadata in asset_def.metadata_by_key.items():
            assert metadata.get("jsonl_stream") in {
                "actions",
                "cards",
                "signals",
                "notes",
            }, key


def test_the_configured_sources_are_all_wired_into_definitions():
    """A source with no asset would sync silently forever."""
    from flow_analysis.definitions import defs

    names = {a.key.to_user_string() for a in RAW_ASSETS}
    assert names == {
        "raw_trello_actions",
        "raw_trello_cards",
        "raw_forum_posts",
        "raw_github_signals",
        "raw_youtube_signals",
        "raw_health_signals",
        "raw_agent_memory",
    }
    assert set(defs.resources) >= {"io_manager", "flow_config", "trello"}


def test_resources_treat_absence_as_normal_and_not_as_failure():
    """Each source resource returns None rather than raising when unconfigured."""
    cfg = fixture_config(date(2026, 8, 16))  # no `signals` block at all
    assert ForumResource().source(cfg) is None
    assert GitHubResource().source(cfg) is None
    assert YouTubeResource().source(cfg) is None
    assert HealthResource().source(cfg) is None
