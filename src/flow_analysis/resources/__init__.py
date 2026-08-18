"""Layer A — the things that reach outside this machine.

One `ConfigurableResource` per origin. Each wraps a source object the CLI has
always used, so there is one implementation of every API quirk — the 14-day
traffic retention, the YouTube settle window, the two strength-training
spellings — and Dagster is a second caller of it rather than a second copy.

Credentials come from `.env` through `config.read_env()`, never from Dagster
config, so nothing secret can end up in a run's stored config or in the UI.
"""

from __future__ import annotations

from .board import TrelloResource
from .flow_config import FlowConfigResource
from .sources import (
    ForumResource,
    GitHubResource,
    HealthResource,
    YouTubeResource,
)

__all__ = [
    "FlowConfigResource",
    "ForumResource",
    "GitHubResource",
    "HealthResource",
    "TrelloResource",
    "YouTubeResource",
]
