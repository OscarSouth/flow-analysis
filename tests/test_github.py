"""GitHub reception source — row shapes, and the partial-day trap.

No network. The response shapes are fixed from the live probe of
OscarSouth/theHarmonicAlgorithm on 2026-08-17, so a change in GitHub's surface
fails here rather than silently recording nothing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from flow_analysis.sources import github as gh
from flow_analysis.tiers import TIER_RECEPTION

REPO = {
    "stargazers_count": 118,
    "forks_count": 8,
    "subscribers_count": 9,
    "created_at": "2018-02-25T17:59:52Z",
}

VIEWS = {
    "count": 40,
    "uniques": 12,
    "views": [
        {"timestamp": "2026-08-15T00:00:00Z", "count": 10, "uniques": 4},
        {"timestamp": "2026-08-16T00:00:00Z", "count": 25, "uniques": 7},
        # Today: still accumulating, and must not be frozen into the store.
        {"timestamp": "2026-08-17T00:00:00Z", "count": 5, "uniques": 1},
    ],
}

CLONES = {
    "count": 3,
    "uniques": 2,
    "clones": [{"timestamp": "2026-08-16T00:00:00Z", "count": 3, "uniques": 2}],
}

STARGAZERS = [
    {"starred_at": "2026-08-10T09:00:00Z", "user": {"login": "alice"}},
    {"starred_at": "2026-08-12T11:30:00Z", "user": {"login": "bob"}},
]

REFERRERS = [
    {"referrer": "news.ycombinator.com", "count": 30, "uniques": 20},
    {"referrer": "Google", "count": 9, "uniques": 7},
]


class _Response:
    def __init__(self, payload, status=200, text_body=None) -> None:
        self._payload = payload
        self.status_code = status
        self.headers = {"x-ratelimit-remaining": "4999"}
        self.reason_phrase = "OK" if status == 200 else "Error"
        self._text_body = text_body

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def raise_for_status(self) -> None:
        if not self.is_success:
            raise AssertionError(f"status {self.status_code}")

    def json(self) -> Any:  # noqa: ANN401 - stands in for the HTTP boundary
        if self._text_body is not None:
            raise ValueError("not json")
        return self._payload


class _Client:
    """Routes on path substring, so tests state intent rather than call order."""

    def __init__(self, routes) -> None:
        self.routes = routes
        self.calls = []

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def get(self, url, params=None, headers=None, timeout=None) -> Any:  # noqa: ANN401 - stands in for the HTTP boundary
        self.calls.append((url, params, (headers or {}).get("Accept")))
        for fragment, response in self.routes.items():
            if fragment in url:
                return response
        return _Response({}, status=404)


@pytest.fixture
def source():
    return gh.GitHubSource(owner="OscarSouth", repo="theHarmonicAlgorithm", token="x")


def _patch(monkeypatch, routes) -> Any:  # noqa: ANN401 - stands in for the HTTP boundary
    client = _Client(routes)
    monkeypatch.setattr(gh.httpx, "Client", lambda **kw: client)
    return client


def test_counters_are_cumulative_totals(monkeypatch, source):
    _patch(monkeypatch, {"/repos/OscarSouth/theHarmonicAlgorithm": _Response(REPO)})
    moment = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)

    rows = list(source.counters(observed=moment))

    assert [r["metric"] for r in rows] == ["stars", "forks", "watchers"]
    assert [r["value"] for r in rows] == [118, 8, 9]
    assert all(r["tier"] == TIER_RECEPTION for r in rows)
    # One row per metric per day: a second sync the same day dedupes away.
    assert rows[0]["id"] == "github:stars:2026-08-17"


def test_traffic_skips_the_current_day(monkeypatch, source):
    """Today's counts are still accumulating.

    The store dedupes on id and never updates, so writing today's partial figure
    would freeze it permanently — the day would be recorded as quieter than it
    was. Skipping it lets a later sync pick up the completed day.
    """
    _patch(
        monkeypatch,
        {"/traffic/views": _Response(VIEWS), "/traffic/clones": _Response(CLONES)},
    )

    rows = list(source.traffic(today=date(2026, 8, 17)))
    days = [r["day"] for r in rows if r["metric"] == "views"]

    assert days == ["2026-08-15", "2026-08-16"]
    assert "2026-08-17" not in days
    views = [r for r in rows if r["metric"] == "views"]
    assert views[1]["count"] == 25
    assert views[1]["uniques"] == 7
    assert rows[0]["id"] == "github:views:2026-08-15"


def test_traffic_day_is_stable_across_syncs(monkeypatch, source):
    """The same completed day yields the same id, so re-syncing costs nothing."""
    _patch(
        monkeypatch,
        {"/traffic/views": _Response(VIEWS), "/traffic/clones": _Response(CLONES)},
    )
    first = {r["id"] for r in source.traffic(today=date(2026, 8, 17))}
    _patch(
        monkeypatch,
        {"/traffic/views": _Response(VIEWS), "/traffic/clones": _Response(CLONES)},
    )
    second = {r["id"] for r in source.traffic(today=date(2026, 8, 17))}
    assert first == second


def test_stars_key_on_the_starrer(monkeypatch, source):
    """An unstar-then-restar must not count twice."""
    _patch(monkeypatch, {"/stargazers": _Response(STARGAZERS)})

    rows = list(source.stars())

    assert [r["id"] for r in rows] == ["github:star:alice", "github:star:bob"]
    assert rows[0]["created_at"] == "2026-08-10T09:00:00Z"
    assert all(r["tier"] == TIER_RECEPTION for r in rows)


def test_stars_request_the_timestamp_media_type(monkeypatch, source):
    """Without this Accept header GitHub returns users but no `starred_at`."""
    client = _patch(monkeypatch, {"/stargazers": _Response(STARGAZERS)})
    list(source.stars())
    assert client.calls[0][2] == "application/vnd.github.star+json"


def test_referrers_record_the_window_they_describe(monkeypatch, source):
    _patch(monkeypatch, {"/traffic/popular/referrers": _Response(REFERRERS)})
    moment = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)

    rows = list(source.referrers(observed=moment))

    assert rows[0]["referrer"] == "news.ycombinator.com"
    assert rows[0]["window_days"] == gh.TRAFFIC_RETENTION_DAYS
    assert rows[0]["id"] == "github:referrer:2026-08-17:news.ycombinator.com"


def test_unauthenticated_source_collects_only_counters(monkeypatch):
    """Without a token the traffic endpoints 401, so don't pretend otherwise."""
    source = gh.GitHubSource(owner="o", repo="r", token=None)
    _patch(monkeypatch, {"/repos/o/r": _Response(REPO)})

    kinds = {r["kind"] for r in source.rows()}

    assert kinds == {"counter"}


def test_probe_survives_a_body_that_is_not_json(monkeypatch, source):
    """A probe reports capability; it must never itself blow up.

    Some gateway errors return HTML rather than GitHub's JSON error shape.
    """
    monkeypatch.setattr(gh.time, "sleep", lambda _: None)
    _patch(monkeypatch, {"": _Response(None, status=504, text_body="<html>504</html>")})

    result = source.probe()

    assert all(not e["ok"] for e in result["endpoints"].values())
    assert result["endpoints"]["repo"]["status"] == 504


def test_gateway_errors_are_retried_but_permission_errors_are_not(monkeypatch, source):
    """A 504 from an intermediary is not an answer about permissions; a 401 is."""
    monkeypatch.setattr(gh.time, "sleep", lambda _: None)

    flaky = _Client({"": _Response(None, status=504, text_body="<html/>")})
    monkeypatch.setattr(gh.httpx, "Client", lambda **kw: flaky)
    source.probe()
    # Six endpoints, three attempts each.
    assert len(flaky.calls) == 18

    denied = _Client(
        {"": _Response({"message": "Requires authentication"}, status=401)}
    )
    monkeypatch.setattr(gh.httpx, "Client", lambda **kw: denied)
    source.probe()
    assert len(denied.calls) == 6
