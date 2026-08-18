"""The forum: your posts, an org-mate's, and everyone else's.

Queried through Flarum's public JSON:API, no auth — the same endpoints the site
already consumes in `~/theHarmonicAlgorithm-site/src/lib/forum.ts`.

Verified live 2026-08-17:
  GET /api/posts?page[limit]=20&sort=-createdAt  -> 6 posts, the entire forum
  authors seen: Oscar-UDAGAN, Saydyy-UDAGAN, UDAGAN, cvsouth

Layer A: this fetches and classifies. Bucketing those rows into flow days is
`metrics/production.py`, which never touches the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from ..tiers import TIER_INTERNAL_OTHER, TIER_PRODUCTION, TIER_RECEPTION
from ..util import json_object

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ..config import Config


PAGE_LIMIT = 50
MAX_PAGES = 40  # ~2000 posts; a hard stop so a bad filter cannot loop forever


@dataclass
class ForumSource:
    """Every post on the forum, split into your own and everyone else's.

    Earlier this filtered by author to collect only your posts. It now fetches
    the lot and classifies, because the interesting number is the one that was
    invisible before: whether anybody *else* is here. On 2026-08-17 the whole
    forum held six posts, one of them from a non-UDAGAN account — so the honest
    external baseline is approximately zero, and saying so is the point.
    """

    base_url: str
    self_authors: list[str] = field(default_factory=list)
    internal_suffix: str = "-UDAGAN"
    extra_internal: list[str] = field(default_factory=list)
    timeout: float = 20.0

    @staticmethod
    def _norm(names: list[str]) -> set[str]:
        return {n.strip().casefold() for n in names if n}

    def is_internal(self, username: str | None) -> bool:
        """Whether an author is you or the org.

        Matched on the name, so a new org account is handled automatically — at
        the cost of missing one that skips the suffix, which is what
        `extra_internal` is for.
        """
        if not username:
            # An unknown author (deleted account, or a shape change in the API)
            # is classed external. Wrong in that direction only over-counts
            # reception; wrong the other way would inflate *your own* output,
            # which is the failure this whole split exists to prevent.
            return False
        name = username.strip().casefold()
        if name in self._norm(self.extra_internal) or name in self._norm(
            self.self_authors
        ):
            return True
        return name == "udagan" or name.endswith(self.internal_suffix.casefold())

    def classify(self, username: str | None) -> str:
        """Which tier a post belongs to: yours, an org-mate's, or an outsider's."""
        if username and username.strip().casefold() in self._norm(self.self_authors):
            return TIER_PRODUCTION
        return TIER_INTERNAL_OTHER if self.is_internal(username) else TIER_RECEPTION

    def _get(
        self, client: httpx.Client, path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        response = client.get(
            f"{self.base_url}{path}",
            params=params,
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return json_object(response.json(), f"forum {path}")

    def posts(self) -> Iterator[dict[str, Any]]:
        """Every post on the forum, newest first, paginated and classified.

        Flarum returns `links.next` while more remain. Note the params are passed
        as a dict and encoded by httpx — a hand-built query string with literal
        `page[limit]` brackets came back as a non-JSON body in testing.
        """
        with httpx.Client(follow_redirects=True) as client:
            offset = 0
            for _ in range(MAX_PAGES):
                doc = self._get(
                    client,
                    "/api/posts",
                    {
                        "sort": "-createdAt",
                        "page[limit]": PAGE_LIMIT,
                        "page[offset]": offset,
                        "include": "user,discussion",
                    },
                )
                rows = doc.get("data") or []
                if not rows:
                    break

                included = doc.get("included") or []
                titles = {
                    item["id"]: (item.get("attributes") or {}).get("title")
                    for item in included
                    if item.get("type") == "discussions"
                }
                usernames = {
                    item["id"]: (item.get("attributes") or {}).get("username")
                    for item in included
                    if item.get("type") == "users"
                }

                for row in rows:
                    attrs = row.get("attributes") or {}
                    created = attrs.get("createdAt")
                    if not created:
                        continue
                    rel = row.get("relationships") or {}
                    discussion = ((rel.get("discussion") or {}).get("data") or {}).get(
                        "id"
                    )
                    user_id = ((rel.get("user") or {}).get("data") or {}).get("id")
                    author = usernames.get(user_id)
                    tier = self.classify(author)
                    yield {
                        "id": f"forum:post:{row['id']}",
                        "tier": tier,
                        "source": "forum",
                        "kind": "post" if tier != TIER_RECEPTION else "external_post",
                        "created_at": created,
                        "author": author,
                        "internal": tier != TIER_RECEPTION,
                        "discussion_id": discussion,
                        "discussion_title": titles.get(discussion),
                        # Post number 1 opens a thread; later numbers are replies.
                        "opens_thread": attrs.get("number") == 1,
                    }

                if not (doc.get("links") or {}).get("next"):
                    break
                offset += PAGE_LIMIT


def source_from_config(cfg: Config) -> ForumSource | None:
    """Read the `signals.forum` block, if configured.

    Only the url is required. A legacy `authors` list becomes `self_authors` —
    those were your own accounts, which is exactly what that field now means —
    so an older config keeps working without an edit.
    """
    block = ((cfg.intent.get("signals") or {}).get("forum")) or {}
    url = (block.get("url") or "").rstrip("/")
    if not url:
        return None
    return ForumSource(
        base_url=url,
        self_authors=list(block.get("self_authors") or block.get("authors") or []),
        internal_suffix=block.get("internal_suffix") or "-UDAGAN",
        extra_internal=list(block.get("extra_internal") or []),
    )
