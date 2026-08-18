"""YouTube source — tier boundaries and the unsettled-data trap.

No network. The shapes follow the Analytics v2 and Data v3 documented responses.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from flow_analysis.sources import youtube as yt
from flow_analysis.tiers import TIER_PRODUCTION, TIER_RECEPTION

ANALYTICS = {
    "columnHeaders": [
        {"name": "day"},
        {"name": "views"},
        {"name": "estimatedMinutesWatched"},
        {"name": "subscribersGained"},
        {"name": "subscribersLost"},
    ],
    "rows": [
        ["2026-08-10", 120, 340, 4, 1],
        ["2026-08-11", 95, 210, 2, 0],
    ],
}

CHANNELS = {
    "items": [
        {
            "snippet": {"title": "Oscar South"},
            "statistics": {
                "subscriberCount": "58",
                "videoCount": "37",
                "viewCount": "10758",
            },
            "contentDetails": {"relatedPlaylists": {"uploads": "UUxxxx"}},
        }
    ]
}

PLAYLIST = {
    "items": [
        {
            "snippet": {
                "title": "Some original music",
                "publishedAt": "2026-07-08T18:00:00Z",
                "resourceId": {"videoId": "vid123"},
            },
            "status": {"privacyStatus": "public"},
        },
        {
            "snippet": {
                "title": "Rough take, not shared",
                "publishedAt": "2026-07-09T18:00:00Z",
                "resourceId": {"videoId": "vid_private"},
            },
            "status": {"privacyStatus": "private"},
        },
        {
            "snippet": {
                "title": "Unlisted demo",
                "publishedAt": "2026-07-10T18:00:00Z",
                "resourceId": {"videoId": "vid_unlisted"},
            },
            "status": {"privacyStatus": "unlisted"},
        },
    ]
}


class _Response:
    def __init__(self, payload, status=200) -> None:
        self._payload = payload
        self.status_code = status
        self.text = ""

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def raise_for_status(self) -> None:
        if not self.is_success:
            raise AssertionError(self.status_code)

    def json(self) -> Any:  # noqa: ANN401 - stands in for the HTTP boundary
        return self._payload


class _Client:
    def __init__(self, routes) -> None:
        self.routes = routes
        self.calls = []

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def post(self, url, data=None, timeout=None) -> Any:  # noqa: ANN401 - stands in for the HTTP boundary
        self.calls.append(("POST", url, data))
        return _Response({"access_token": "at"})

    def get(self, url, params=None, headers=None, timeout=None) -> Any:  # noqa: ANN401 - stands in for the HTTP boundary
        self.calls.append(("GET", url, params))
        for fragment, response in self.routes.items():
            if fragment in url:
                return response
        return _Response({}, status=404)


@pytest.fixture
def source():
    return yt.YouTubeSource(
        channel_id="UCtest",
        client_id="cid",
        client_secret="sec",
        refresh_token="rt",
    )


def _patch(monkeypatch, routes) -> Any:  # noqa: ANN401 - stands in for the HTTP boundary
    client = _Client(routes)
    monkeypatch.setattr(yt.httpx, "Client", lambda **kw: client)
    return client


def test_uploads_are_production_not_reception(monkeypatch, source):
    """An upload is a Reveal artefact — something you put out.

    The views it earns are reception. Conflating them would let the audience's
    response inflate the measure of your own output.
    """
    _patch(
        monkeypatch,
        {"/channels": _Response(CHANNELS), "/playlistItems": _Response(PLAYLIST)},
    )

    rows = list(source.uploads())

    assert len(rows) == 1
    assert rows[0]["tier"] == TIER_PRODUCTION
    assert rows[0]["id"] == "youtube:video:vid123"
    assert rows[0]["created_at"] == "2026-07-08T18:00:00Z"


def test_only_public_uploads_count_as_production(monkeypatch, source):
    """A private or unlisted video did not leave the building.

    However much work went into it, it is not a Reveal artefact — so it is not
    production. The uploads playlist carries all three privacy states, and 22 of
    the 59 on this channel turned out not to be public.
    """
    _patch(
        monkeypatch,
        {"/channels": _Response(CHANNELS), "/playlistItems": _Response(PLAYLIST)},
    )

    ids = [r["video_id"] for r in source.uploads()]

    assert ids == ["vid123"]
    assert "vid_private" not in ids
    assert "vid_unlisted" not in ids


def test_uploads_request_the_status_part(monkeypatch, source):
    """The `status` part is what makes privacy visible.

    Without it, privacyStatus is absent and every video would silently look
    public.
    """
    client = _patch(
        monkeypatch,
        {"/channels": _Response(CHANNELS), "/playlistItems": _Response(PLAYLIST)},
    )
    list(source.uploads())
    playlist_call = next(c for c in client.calls if "playlistItems" in c[1])
    assert "status" in playlist_call[2]["part"]


def test_analytics_days_are_reception(monkeypatch, source):
    _patch(monkeypatch, {"/reports": _Response(ANALYTICS)})

    rows = list(source.analytics())

    assert [r["day"] for r in rows] == ["2026-08-10", "2026-08-11"]
    assert all(r["tier"] == TIER_RECEPTION for r in rows)
    assert rows[0]["views"] == 120
    assert rows[0]["subscribers_gained"] == 4
    assert rows[0]["subscribers_lost"] == 1
    assert rows[0]["id"] == "youtube:day:2026-08-10"


def test_recent_days_are_left_to_settle(monkeypatch, source):
    """YouTube revises the last few days.

    The store dedupes on id and never updates, so a day written too early would
    be frozen at a partial figure — the same trap as GitHub traffic.
    """
    captured = {}

    class _Recorder(_Client):
        def get(self, url, params=None, headers=None, timeout=None) -> Any:  # noqa: ANN401 - stands in for the HTTP boundary
            captured.update(params or {})
            return _Response(ANALYTICS)

    monkeypatch.setattr(yt.httpx, "Client", lambda **kw: _Recorder({}))
    list(source.analytics())

    requested_end = date.fromisoformat(captured["endDate"])
    assert requested_end <= date.today() - timedelta(days=yt.SETTLE_DAYS)


def test_an_unauthorised_source_raises_rather_than_recording_zeros(monkeypatch):
    """A lapsed grant must fail loudly.

    Silently recording zeros would look exactly like a channel nobody watched —
    the worst possible failure mode for a reception metric.
    """
    source = yt.YouTubeSource(channel_id="UCtest")
    assert source.configured is False
    with pytest.raises(RuntimeError, match="flow auth youtube"):
        list(source.analytics())


def test_a_failed_refresh_reports_googles_reason(monkeypatch, source):
    class _Failing(_Client):
        def post(self, url, data=None, timeout=None) -> Any:  # noqa: ANN401 - stands in for the HTTP boundary
            return _Response(
                {"error_description": "Token has been expired or revoked."}, status=400
            )

    monkeypatch.setattr(yt.httpx, "Client", lambda **kw: _Failing({}))
    with pytest.raises(RuntimeError, match="expired or revoked"):
        list(source.analytics())


def test_a_refresh_that_succeeds_without_a_token_fails_at_the_refresh(
    monkeypatch, source
):
    """A 200 carrying no `access_token` must not be carried forward.

    Left alone it becomes a 401 on the *next* call, which blames the credential
    rather than the refresh that actually returned nothing.
    """

    class _Empty(_Client):
        def post(self, url, data=None, timeout=None) -> Any:  # noqa: ANN401 - stands in for the HTTP boundary
            return _Response({"expires_in": 3599})

    monkeypatch.setattr(yt.httpx, "Client", lambda **kw: _Empty({}))
    with pytest.raises(RuntimeError, match="no access_token"):
        list(source.analytics())


def test_a_short_analytics_row_raises_rather_than_dropping_a_metric(
    monkeypatch, source
):
    """Columns are named in `columnHeaders` and the rows must match them.

    Zipping a short row without `strict` would silently drop whichever metric
    fell off the end — minutes watched becoming absent rather than zero, which
    reads as a quiet channel instead of a broken response.
    """
    truncated = {
        "columnHeaders": ANALYTICS["columnHeaders"],
        "rows": [["2026-08-10", 120, 340]],  # missing subs gained/lost
    }
    _patch(monkeypatch, {"/reports": _Response(truncated)})

    with pytest.raises(ValueError, match="shorter"):
        list(source.analytics())


def test_probe_reports_the_public_rounded_count_as_context(monkeypatch, source):
    """The public subscriber count is context only.

    Above 1,000 YouTube rounds it to 3 s.f., and it carries no daily resolution
    at any size — which is why the Analytics API is used instead.
    """
    _patch(
        monkeypatch,
        {"/channels": _Response(CHANNELS), "/reports": _Response(ANALYTICS)},
    )

    result = source.probe()

    assert result["configured"] is True
    assert result["endpoints"]["channel"]["sample"]["subscribers_public"] == "58"
    assert result["endpoints"]["analytics_daily"]["sample"]["days_returned"] == 2


def test_source_is_not_configured_without_a_refresh_token():
    source = yt.YouTubeSource(channel_id="UCtest", client_id="a", client_secret="b")
    assert source.configured is False
