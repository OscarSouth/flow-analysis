"""The external signal sources, as resources.

Each returns the existing source object or `None`. **`None` is a normal state, not
an error**: a source with no block in `config/board.yaml`, or no credential in
`.env`, is simply not configured, and the asset skips rather than failing the run.

What must never be silent is a source that *is* configured and cannot read — a
lapsed credential recording zeros looks exactly like a channel nobody watched.
That distinction lives in the source objects themselves and is preserved here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dagster import ConfigurableResource

if TYPE_CHECKING:
    from ..config import Config
    from ..sources.forum import ForumSource
    from ..sources.github import GitHubSource
    from ..sources.health import HealthSource
    from ..sources.youtube import YouTubeSource


class ForumResource(ConfigurableResource["ForumResource"]):
    """Flarum's public JSON:API — your posts, an org-mate's, and outsiders'."""

    def source(self, cfg: Config) -> ForumSource | None:
        """The configured forum, or None if `signals.forum` is absent."""
        from ..sources import forum

        return forum.source_from_config(cfg)


class GitHubResource(ConfigurableResource["GitHubResource"]):
    """One repository, read as reception."""

    def source(self, cfg: Config) -> GitHubSource | None:
        """The configured repo, or None if `signals.github` is absent."""
        from ..sources import github

        return github.source_from_config(cfg)


class YouTubeResource(ConfigurableResource["YouTubeResource"]):
    """Uploads as production, the views they earn as reception."""

    def source(self, cfg: Config) -> YouTubeSource | None:
        """The channel, or None when unconfigured or not yet authorised.

        Both cases return None on purpose: OAuth not having happened yet is a
        setup state, and `flow auth youtube` is the fix, not a failed run.
        """
        from ..sources import youtube

        source = youtube.source_from_config(cfg)
        if source is None or not source.configured:
            return None
        return source


class HealthResource(ConfigurableResource["HealthResource"]):
    """An Apple Health export dropped into `ingest/`.

    A missing export is the *normal* state, because the export is purged once its
    rows are stored — see `HealthSource.purge`. Absence here means nothing was
    delivered, not that anything failed.
    """

    def source(self, cfg: Config) -> HealthSource | None:
        """The export, or None if `signals.health` is absent or nothing landed."""
        from ..sources import health

        source = health.source_from_config(cfg)
        if source is None or not source.archive_path.exists():
            return None
        return source
