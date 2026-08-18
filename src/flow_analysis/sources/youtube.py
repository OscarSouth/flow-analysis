"""YouTube: uploads are production, everything they earn is reception.

An upload is a Reveal artefact — something that left the building — so it lands
in the **production** tier. The views and subscribers it goes on to earn are
**reception**. Keeping those apart is what stops the audience's response from
inflating the measure of your own output.

Two APIs, because they answer different questions:

  Data API v3        the uploads playlist -> when you published    (production)
  Analytics API v2   daily views, subs gained/lost, watch time     (reception)

The public subscriber count carries no daily resolution, and above 1,000 YouTube
also rounds it to three significant figures. The Analytics API returns exact daily
figures with full backfill instead — 6,204 days on this channel, going back to
2009 — which is the whole reason for the OAuth setup. Audience size is not the
point: the channel has 58 subscribers. Precision and history are.

Auth is a Desktop-app OAuth client with a loopback redirect. The refresh token
lives in `.env` beside the other credentials; `flow auth youtube` obtains it, and
the consent happens in your own browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

from ..tiers import TIER_PRODUCTION, TIER_RECEPTION
from ..util import json_object

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ..config import Config

TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
DATA_URL = "https://www.googleapis.com/youtube/v3"

SCOPES = (
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
)

# YouTube Analytics keeps revising the last few days. The store dedupes on id and
# never updates, so a day written too early would be frozen at a partial figure —
# the same trap as GitHub's traffic. Three days is comfortably past settling.
SETTLE_DAYS = 3

# Analytics data starts here for most channels; earlier requests error rather
# than return empty.
EARLIEST = date(2005, 1, 1)

METRICS = "views,estimatedMinutesWatched,subscribersGained,subscribersLost"


@dataclass
class YouTubeSource:
    """One channel: uploads as production, everything they earn as reception.

    Unconfigured is a normal state, not an error — `configured` is False until
    the OAuth credentials are in `.env`, and the sync skips the source rather
    than failing the run.
    """

    channel_id: str
    client_id: str | None = None
    client_secret: str | None = None
    refresh_token: str | None = None
    timeout: float = 30.0

    @property
    def configured(self) -> bool:
        """Whether the OAuth triple is present. Nothing is attempted without it."""
        return bool(self.client_id and self.client_secret and self.refresh_token)

    # --- auth ---------------------------------------------------------------

    def access_token(self, client: httpx.Client) -> str:
        """Exchange the long-lived refresh token for a short-lived access token.

        Raises rather than returning empty: a lapsed grant must fail loudly. The
        alternative — recording zeros — would look exactly like a channel nobody
        watched, which is the worst possible silent failure here.
        """
        if not self.configured:
            raise RuntimeError(
                "YouTube is not authorised. Run: uv run flow auth youtube"
            )
        response = client.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=self.timeout,
        )
        if not response.is_success:
            detail = (response.json() or {}).get("error_description") or response.text
            raise RuntimeError(
                f"YouTube token refresh failed ({response.status_code}): {detail}"
            )
        token = json_object(response.json(), "YouTube token refresh").get(
            "access_token"
        )
        if not isinstance(token, str) or not token:
            # A refresh that returns 200 without a token would otherwise fail as
            # a 401 on the next call, blaming the credential rather than this.
            raise RuntimeError("YouTube token refresh returned no access_token")
        return token

    # --- probe --------------------------------------------------------------

    def probe(self) -> dict[str, Any]:
        """What this grant actually permits, and how far back the data goes."""
        out: dict[str, Any] = {
            "channel_id": self.channel_id,
            "configured": self.configured,
        }
        if not self.configured:
            out["endpoints"] = {}
            return out

        results: dict[str, Any] = {}
        with httpx.Client(follow_redirects=True) as client:
            try:
                token = self.access_token(client)
            except RuntimeError as exc:
                out["endpoints"] = {"token": {"ok": False, "message": str(exc)}}
                return out
            results["token"] = {"ok": True, "status": 200}
            headers = {"Authorization": f"Bearer {token}"}

            response = client.get(
                f"{DATA_URL}/channels",
                params={"part": "contentDetails,statistics,snippet", "mine": "true"},
                headers=headers,
                timeout=self.timeout,
            )
            entry: dict[str, Any] = {
                "ok": response.is_success,
                "status": response.status_code,
            }
            if response.is_success:
                items = response.json().get("items") or []
                if items:
                    stats = items[0].get("statistics") or {}
                    entry["sample"] = {
                        "title": (items[0].get("snippet") or {}).get("title"),
                        "subscribers_public": stats.get("subscriberCount"),
                        "videos": stats.get("videoCount"),
                        "views_total": stats.get("viewCount"),
                    }
            else:
                entry["message"] = _error(response)
            results["channel"] = entry

            end = _settled_end()
            response = client.get(
                ANALYTICS_URL,
                params={
                    "ids": "channel==MINE",
                    "startDate": (end - timedelta(days=30)).isoformat(),
                    "endDate": end.isoformat(),
                    "metrics": METRICS,
                    "dimensions": "day",
                },
                headers=headers,
                timeout=self.timeout,
            )
            entry = {"ok": response.is_success, "status": response.status_code}
            if response.is_success:
                rows = response.json().get("rows") or []
                entry["sample"] = {
                    "days_returned": len(rows),
                    "metrics": response.json().get("columnHeaders"),
                }
                if rows:
                    entry["sample"]["latest_day"] = rows[-1][0]
            else:
                entry["message"] = _error(response)
            results["analytics_daily"] = entry

        out["endpoints"] = results
        return out

    # --- collection ---------------------------------------------------------

    def analytics(self, start: date | None = None) -> Iterator[dict[str, Any]]:
        """Exact per-day reception, for days old enough to have settled."""
        end = _settled_end()
        begin = start or EARLIEST
        if begin > end:
            return
        with httpx.Client(follow_redirects=True) as client:
            token = self.access_token(client)
            response = client.get(
                ANALYTICS_URL,
                params={
                    "ids": "channel==MINE",
                    "startDate": begin.isoformat(),
                    "endDate": end.isoformat(),
                    "metrics": METRICS,
                    "dimensions": "day",
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout,
            )
            if not response.is_success:
                raise RuntimeError(f"YouTube analytics failed: {_error(response)}")
            payload = response.json()

        headers = [h["name"] for h in payload.get("columnHeaders") or []]
        for row in payload.get("rows") or []:
            # strict: a row shorter than the header list would silently drop a
            # metric — minutes watched quietly becoming absent rather than zero.
            record = dict(zip(headers, row, strict=True))
            day = record.get("day")
            if not day:
                continue
            yield {
                "id": f"youtube:day:{day}",
                "tier": TIER_RECEPTION,
                "source": "youtube",
                "kind": "analytics_day",
                "channel_id": self.channel_id,
                "day": day,
                "created_at": f"{day}T12:00:00+00:00",
                "views": record.get("views"),
                "minutes_watched": record.get("estimatedMinutesWatched"),
                "subscribers_gained": record.get("subscribersGained"),
                "subscribers_lost": record.get("subscribersLost"),
            }

    def uploads(self) -> Iterator[dict[str, Any]]:
        """Public publish events — production, not reception.

        Only `privacyStatus == "public"` counts. The uploads playlist also carries
        unlisted and private videos, and those did not leave the building: a
        private video is not a Reveal artefact, however much work went into it.
        """
        with httpx.Client(follow_redirects=True) as client:
            token = self.access_token(client)
            headers = {"Authorization": f"Bearer {token}"}
            response = client.get(
                f"{DATA_URL}/channels",
                params={"part": "contentDetails", "mine": "true"},
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            items = response.json().get("items") or []
            if not items:
                return
            playlist = (
                (items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}
            ).get("uploads")
            if not playlist:
                return

            page: str | None = None
            for _ in range(40):  # 2,000 videos, a hard stop
                params: dict[str, Any] = {
                    "part": "snippet,status",
                    "playlistId": playlist,
                    "maxResults": 50,
                }
                if page:
                    params["pageToken"] = page
                response = client.get(
                    f"{DATA_URL}/playlistItems",
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                for item in payload.get("items") or []:
                    snippet = item.get("snippet") or {}
                    privacy = (item.get("status") or {}).get("privacyStatus")
                    if privacy != "public":
                        continue
                    resource = (snippet.get("resourceId") or {}).get("videoId")
                    published = snippet.get("publishedAt")
                    if not resource or not published:
                        continue
                    yield {
                        "id": f"youtube:video:{resource}",
                        "tier": TIER_PRODUCTION,
                        "source": "youtube",
                        "kind": "upload",
                        "channel_id": self.channel_id,
                        "created_at": published,
                        "video_id": resource,
                        "title": snippet.get("title"),
                        "privacy": privacy,
                    }
                page = payload.get("nextPageToken")
                if not page:
                    break

    def rows(self) -> Iterator[dict[str, Any]]:
        """Both streams, tiered as they go: uploads production, analytics reception."""
        yield from self.uploads()
        yield from self.analytics()


def _settled_end() -> date:
    return datetime.now(UTC).date() - timedelta(days=SETTLE_DAYS)


def _error(response: httpx.Response) -> str:
    try:
        payload = response.json() or {}
    except ValueError:
        return response.text[:200]
    error = payload.get("error")
    if isinstance(error, dict):
        return error.get("message") or str(error)
    return str(error or response.text[:200])


def source_from_config(cfg: Config) -> YouTubeSource | None:
    """Read the `signals.youtube` block, if configured."""
    from ..config import env_value

    block = ((cfg.intent.get("signals") or {}).get("youtube")) or {}
    channel = block.get("channel_id")
    if not channel:
        return None
    return YouTubeSource(
        channel_id=channel,
        client_id=env_value("YOUTUBE_CLIENT_ID"),
        client_secret=env_value("YOUTUBE_CLIENT_SECRET"),
        refresh_token=env_value("YOUTUBE_REFRESH_TOKEN"),
    )
