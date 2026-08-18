"""GitHub as a reception signal: who found the work, and how they arrived.

Four things are collected, and they answer different questions:

  counters    stars / forks / watchers — a running total, so it survives gaps
  stars       one row per star with `starred_at`, which backfills the whole history
  traffic     per-day views and clones, **retained by GitHub for only 14 days**
  referrers   where the traffic came from, as a snapshot of the same 14 days

The retention is the one genuinely time-sensitive thing in this repo. Stars
backfill whenever we get to them; a day of traffic not collected is gone.

Rate limit is 5,000/hr authenticated — this uses about six calls per sync.

Everything here is **reception**: it is what came back, never what you produced.

Calibration, measured 2026-08-17 on OscarSouth/theHarmonicAlgorithm. Read this
before treating any of these numbers as a growth signal:

- **Stars are a decaying series, not a growing one.** 116 timestamped stars:
  18 (2018), 20 (2019), **37 (2020)**, 12, 11, 5, 8, 2 (2025), 3 (2026 to date).
  Attention peaked in 2020 and faded. At roughly three to five a year, the *rate*
  cannot support a trend claim on any horizon shorter than several years. The
  cumulative total is still a fair record of reach; the rate is close to dead.
- **Clones are contaminated; views are not.** The same fortnight showed 7 views
  from 5 unique visitors, but 55 clones from 41 unique cloners. Human readers do
  not outnumber themselves eight to one — that is mirrors, CI and crawlers. The
  largest clone days (18 on 2026-08-13, 11 on the 14th) also sit right on top of
  a push, so clones partly measure *your own* activity. Treat `views`/`uniques`
  as the human-attention signal and clones as infrastructure noise.
- **Referrers showed only `github.com`**, so no outside route in was visible at
  all during the window.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import httpx

from ..tiers import TIER_RECEPTION

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ..config import Config

API = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 20  # 2,000 stargazers; a hard stop so a bad response cannot loop
TRAFFIC_RETENTION_DAYS = 14


@dataclass
class GitHubSource:
    """One repository, read as reception.

    Stars, forks and watchers are what came back, never what you put out. The
    token is optional and the difference matters: without it only the totals are
    readable, and traffic — which GitHub keeps for 14 days only — is not.
    """

    owner: str
    repo: str
    token: str | None = None
    timeout: float = 20.0

    @property
    def slug(self) -> str:
        """owner/repo, as GitHub writes it and as the sync labels it."""
        return f"{self.owner}/{self.repo}"

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(
        self,
        client: httpx.Client,
        path: str,
        params: dict[str, Any] | None = None,
        accept: str = "application/vnd.github+json",
        attempts: int = 3,
    ) -> httpx.Response:
        """GET with a retry on gateway errors.

        Not defensive padding: a 502/504 from an intermediary is indistinguishable
        from a real failure at the call site, and the probe reports capability.
        Reporting "endpoint unavailable" because a proxy hiccuped would be a wrong
        conclusion about the account's permissions. 4xx is never retried — that
        *is* the answer.
        """
        last: httpx.Response | None = None
        for attempt in range(attempts):
            last = client.get(
                f"{API}{path}",
                params=params,
                headers=self._headers(accept),
                timeout=self.timeout,
            )
            if last.status_code not in (502, 503, 504):
                return last
            if attempt < attempts - 1:
                time.sleep(1.5 * (attempt + 1))
        assert last is not None
        return last

    # --- probe --------------------------------------------------------------

    def probe(self) -> dict[str, Any]:
        """What this account actually returns, endpoint by endpoint.

        Run before building on any of it. The docs say what is possible; this
        says what is permitted here — `starred_at` and every traffic endpoint
        return 401/403 without a token carrying push access.
        """
        checks: list[tuple[str, str, dict[str, Any] | None, str]] = [
            ("repo", f"/repos/{self.slug}", None, "application/vnd.github+json"),
            (
                "stars_with_timestamps",
                f"/repos/{self.slug}/stargazers",
                {"per_page": 1},
                "application/vnd.github.star+json",
            ),
            (
                "traffic_views",
                f"/repos/{self.slug}/traffic/views",
                None,
                "application/vnd.github+json",
            ),
            (
                "traffic_clones",
                f"/repos/{self.slug}/traffic/clones",
                None,
                "application/vnd.github+json",
            ),
            (
                "referrers",
                f"/repos/{self.slug}/traffic/popular/referrers",
                None,
                "application/vnd.github+json",
            ),
            (
                "paths",
                f"/repos/{self.slug}/traffic/popular/paths",
                None,
                "application/vnd.github+json",
            ),
        ]
        out: dict[str, Any] = {"slug": self.slug, "authenticated": bool(self.token)}
        results: dict[str, Any] = {}
        with httpx.Client(follow_redirects=True) as client:
            for name, path, params, accept in checks:
                try:
                    response = self._get(client, path, params, accept)
                except httpx.HTTPError as exc:  # network, not permission
                    results[name] = {"ok": False, "error": str(exc)}
                    continue
                entry: dict[str, Any] = {
                    "ok": response.is_success,
                    "status": response.status_code,
                }
                # A probe must never itself fail. Some error responses carry no
                # body at all, and a 204 carries none by design.
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                if response.is_success:
                    entry["sample"] = _summarise(name, payload)
                else:
                    entry["message"] = (payload or {}).get(
                        "message"
                    ) or response.reason_phrase
                results[name] = entry
                out["rate_limit_remaining"] = response.headers.get(
                    "x-ratelimit-remaining"
                )
        out["endpoints"] = results
        return out

    # --- collection ---------------------------------------------------------

    def counters(self, observed: datetime | None = None) -> Iterator[dict[str, Any]]:
        """Stars, forks and watchers as running totals.

        Cumulative, so diffing across a gap still yields the correct delta —
        which is why a missed week costs resolution but never the level.
        """
        moment = observed or datetime.now(UTC)
        day = moment.date().isoformat()
        with httpx.Client(follow_redirects=True) as client:
            response = self._get(client, f"/repos/{self.slug}")
            response.raise_for_status()
            repo = response.json()
        for metric, key in (
            ("stars", "stargazers_count"),
            ("forks", "forks_count"),
            ("watchers", "subscribers_count"),
        ):
            yield {
                "id": f"github:{metric}:{day}",
                "tier": TIER_RECEPTION,
                "source": "github",
                "kind": "counter",
                "metric": metric,
                "repo": self.slug,
                "observed_at": moment.isoformat(),
                "value": repo.get(key),
            }

    def stars(self) -> Iterator[dict[str, Any]]:
        """One row per star, carrying `starred_at`. Needs a token.

        Keyed on the starrer's login, so an unstar-then-restar collapses to one
        row rather than double-counting.
        """
        with httpx.Client(follow_redirects=True) as client:
            for page in range(1, MAX_PAGES + 1):
                response = self._get(
                    client,
                    f"/repos/{self.slug}/stargazers",
                    {"per_page": PER_PAGE, "page": page},
                    accept="application/vnd.github.star+json",
                )
                response.raise_for_status()
                rows = response.json() or []
                if not rows:
                    break
                for row in rows:
                    user = row.get("user") or {}
                    login = user.get("login")
                    starred_at = row.get("starred_at")
                    if not login or not starred_at:
                        continue
                    yield {
                        "id": f"github:star:{login}",
                        "tier": TIER_RECEPTION,
                        "source": "github",
                        "kind": "star",
                        "repo": self.slug,
                        "created_at": starred_at,
                        "actor": login,
                    }
                if len(rows) < PER_PAGE:
                    break

    def traffic(self, today: date | None = None) -> Iterator[dict[str, Any]]:
        """Per-day views and clones, for **completed** days only.

        Today's counts are still accumulating. Storing them would freeze a
        partial number in place, because the store dedupes on id and never
        updates — so the current day is skipped and picked up by a later sync.
        """
        cutoff = today or datetime.now(UTC).date()
        with httpx.Client(follow_redirects=True) as client:
            for kind, path in (("views", "views"), ("clones", "clones")):
                response = self._get(client, f"/repos/{self.slug}/traffic/{path}")
                response.raise_for_status()
                for row in response.json().get(kind) or []:
                    stamp = row.get("timestamp")
                    if not stamp:
                        continue
                    day = stamp[:10]
                    if date.fromisoformat(day) >= cutoff:
                        continue
                    yield {
                        "id": f"github:{kind}:{day}",
                        "tier": TIER_RECEPTION,
                        "source": "github",
                        "kind": f"traffic_{kind}",
                        "metric": kind,
                        "repo": self.slug,
                        "day": day,
                        "created_at": stamp,
                        "count": row.get("count"),
                        "uniques": row.get("uniques"),
                    }

    def traffic_windows(
        self, observed: datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        """GitHub's own totals for the trailing 14 days — the snapshot level.

        Worth storing separately from the per-day rows because `uniques` here is
        a true distinct-visitor count for the window, whereas summing the daily
        uniques double-counts anyone who came back on another day. Since polling
        will be irregular, this level is the unit that stays comparable: miss
        three weeks and you simply get a longer gap between snapshots.
        """
        moment = observed or datetime.now(UTC)
        day = moment.date().isoformat()
        with httpx.Client(follow_redirects=True) as client:
            for metric, path in (("views", "views"), ("clones", "clones")):
                response = self._get(client, f"/repos/{self.slug}/traffic/{path}")
                response.raise_for_status()
                payload = response.json() or {}
                yield {
                    "id": f"github:{metric}_window:{day}",
                    "tier": TIER_RECEPTION,
                    "source": "github",
                    "kind": "traffic_window",
                    "metric": metric,
                    "repo": self.slug,
                    "observed_at": moment.isoformat(),
                    "window_days": TRAFFIC_RETENTION_DAYS,
                    "count": payload.get("count"),
                    "uniques": payload.get("uniques"),
                }

    def referrers(self, observed: datetime | None = None) -> Iterator[dict[str, Any]]:
        """Where the traffic came from, over GitHub's trailing 14 days.

        A snapshot, not a series: the window moves and cannot be reconstructed,
        so each row records the window it describes.
        """
        moment = observed or datetime.now(UTC)
        day = moment.date().isoformat()
        with httpx.Client(follow_redirects=True) as client:
            response = self._get(
                client, f"/repos/{self.slug}/traffic/popular/referrers"
            )
            response.raise_for_status()
            for row in response.json() or []:
                name = row.get("referrer")
                if not name:
                    continue
                yield {
                    "id": f"github:referrer:{day}:{name}",
                    "tier": TIER_RECEPTION,
                    "source": "github",
                    "kind": "referrer_window",
                    "repo": self.slug,
                    "referrer": name,
                    "observed_at": moment.isoformat(),
                    "window_days": TRAFFIC_RETENTION_DAYS,
                    "count": row.get("count"),
                    "uniques": row.get("uniques"),
                }

    def rows(self) -> Iterator[dict[str, Any]]:
        """Everything this source can collect, given what the token allows."""
        yield from self.counters()
        if not self.token:
            return
        yield from self.stars()
        yield from self.traffic()
        yield from self.traffic_windows()
        yield from self.referrers()


def _summarise(name: str, payload: Any) -> dict[str, Any] | None:  # noqa: ANN401
    """A compact, non-secret digest of a probe response.

    `payload` is Any because it genuinely is: each probed endpoint returns a
    different shape — an object here, an array there — and this exists to
    reduce whichever arrived to something printable without secrets.
    """
    if name == "repo":
        return {
            k: payload.get(k)
            for k in (
                "stargazers_count",
                "forks_count",
                "subscribers_count",
                "created_at",
            )
        }
    if name == "stars_with_timestamps":
        first = (payload or [{}])[0]
        return {
            "has_starred_at": "starred_at" in first,
            "starred_at": first.get("starred_at"),
        }
    if name in {"traffic_views", "traffic_clones"}:
        key = "views" if name.endswith("views") else "clones"
        days = payload.get(key) or []
        return {
            "total_14d": payload.get("count"),
            "uniques_14d": payload.get("uniques"),
            "days_returned": len(days),
        }
    if name in {"referrers", "paths"}:
        return {
            "rows": len(payload or []),
            "top": [r.get("referrer") or r.get("path") for r in (payload or [])[:3]],
        }
    return None


def source_from_config(cfg: Config) -> GitHubSource | None:
    """Read the `signals.github` block, if configured."""
    from ..config import env_value

    block = ((cfg.intent.get("signals") or {}).get("github")) or {}
    owner = block.get("owner")
    repo = block.get("repo")
    if not owner or not repo:
        return None
    return GitHubSource(owner=owner, repo=repo, token=env_value("GITHUB_TOKEN"))
