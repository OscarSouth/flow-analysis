"""The forum source — parsing, classification, and what it refuses to filter.

No network: the Flarum response shape is fixed here from a live capture made on
2026-08-17, so a change in their API surfaces as a test failure rather than as
silently missing production.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from flow_analysis.fixtures import fixture_config
from flow_analysis.sources import forum
from flow_analysis.tiers import (
    TIER_INTERNAL_OTHER,
    TIER_PRODUCTION,
    TIER_RECEPTION,
)

# Shape captured live from forum.udaganuniverse.com.
LIVE_PAGE = {
    "data": [
        {
            "type": "posts",
            "id": "13",
            "attributes": {"createdAt": "2026-07-11T10:09:28+00:00", "number": 1},
            "relationships": {
                "discussion": {"data": {"type": "discussions", "id": "9"}},
                "user": {"data": {"type": "users", "id": "3"}},
            },
        },
        {
            "type": "posts",
            "id": "2",
            "attributes": {"createdAt": "2026-07-05T16:14:39+00:00", "number": 2},
            "relationships": {
                "discussion": {"data": {"type": "discussions", "id": "1"}},
                # The one genuinely external post in the whole forum, as of
                # 2026-08-17. The external baseline really is this thin.
                "user": {"data": {"type": "users", "id": "4"}},
            },
        },
    ],
    "included": [
        {
            "type": "discussions",
            "id": "9",
            "attributes": {"title": "The Harmonic Algorithm 1"},
        },
        {"type": "discussions", "id": "1", "attributes": {"title": "First post"}},
        {"type": "users", "id": "3", "attributes": {"username": "Oscar-UDAGAN"}},
        {"type": "users", "id": "4", "attributes": {"username": "cvsouth"}},
    ],
    "links": {},
}


class _FakeResponse:
    def __init__(self, payload) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:  # noqa: ANN401 - stands in for the HTTP boundary
        return self._payload


class _FakeClient:
    def __init__(self, pages) -> None:
        self._pages = list(pages)
        self.calls = []

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def get(self, url, params=None, headers=None, timeout=None) -> Any:  # noqa: ANN401 - stands in for the HTTP boundary
        self.calls.append((url, params))
        return _FakeResponse(
            self._pages.pop(0) if self._pages else {"data": [], "links": {}}
        )


"""The store fixture lives in test_production.py — nothing here touches disk."""


def test_posts_are_parsed_with_titles_and_thread_flag(monkeypatch):
    client = _FakeClient([LIVE_PAGE])
    monkeypatch.setattr(forum.httpx, "Client", lambda **kw: client)

    posts = list(
        forum.ForumSource(
            "https://forum.example", self_authors=["Oscar-UDAGAN"]
        ).posts()
    )

    assert [p["id"] for p in posts] == ["forum:post:13", "forum:post:2"]
    assert posts[0]["discussion_title"] == "The Harmonic Algorithm 1"
    assert posts[0]["opens_thread"] is True
    assert posts[1]["opens_thread"] is False
    assert posts[0]["source"] == "forum"


def test_posts_are_split_into_your_own_and_everyone_elses(monkeypatch):
    """The number that was invisible before: whether anybody else is here."""
    client = _FakeClient([LIVE_PAGE])
    monkeypatch.setattr(forum.httpx, "Client", lambda **kw: client)

    posts = list(
        forum.ForumSource(
            "https://forum.example", self_authors=["Oscar-UDAGAN"]
        ).posts()
    )

    own, external = posts[0], posts[1]
    assert own["author"] == "Oscar-UDAGAN"
    assert own["internal"] is True
    assert own["tier"] == TIER_PRODUCTION

    assert external["author"] == "cvsouth"
    assert external["internal"] is False
    assert external["tier"] == TIER_RECEPTION
    assert external["kind"] == "external_post"


def test_no_author_filter_is_sent_and_users_are_included(monkeypatch):
    """Everything is fetched and classified locally.

    A username that does not match the suffix rule can never silently vanish
    from the record.
    """
    client = _FakeClient([LIVE_PAGE])
    monkeypatch.setattr(forum.httpx, "Client", lambda **kw: client)

    list(
        forum.ForumSource(
            "https://forum.example", self_authors=["Oscar-UDAGAN"]
        ).posts()
    )
    _, params = client.calls[0]
    assert "filter[author]" not in params
    assert params["include"] == "user,discussion"


@pytest.mark.parametrize(
    ("username", "internal"),
    [
        ("Oscar-UDAGAN", True),
        ("Saydyy-UDAGAN", True),
        ("UDAGAN", True),
        ("udagan", True),  # the rule is case-insensitive
        ("someone-udagan", True),
        ("cvsouth", False),
        ("", False),
        (None, False),  # unknown author is never counted as yours
    ],
)
def test_internal_classification(username, internal):
    source = forum.ForumSource("https://forum.example", self_authors=["Oscar-UDAGAN"])
    assert source.is_internal(username) is internal


@pytest.mark.parametrize(
    ("username", "tier"),
    [
        ("Oscar-UDAGAN", TIER_PRODUCTION),
        # An org-mate: internal, so not reception — but not your output either.
        ("Saydyy-UDAGAN", TIER_INTERNAL_OTHER),
        ("UDAGAN", TIER_INTERNAL_OTHER),
        ("cvsouth", TIER_RECEPTION),
        (None, TIER_RECEPTION),
    ],
)
def test_three_way_classification(username, tier):
    source = forum.ForumSource("https://forum.example", self_authors=["Oscar-UDAGAN"])
    assert source.classify(username) == tier


def test_extra_internal_catches_an_org_member_without_the_suffix():
    source = forum.ForumSource("https://forum.example", extra_internal=["Cvsouth"])
    assert source.is_internal("cvsouth") is True


def test_legacy_authors_config_becomes_self_authors():
    """An older config keeps working: those names were your own accounts."""
    cfg = fixture_config(date(2026, 7, 1))
    cfg.intent["signals"] = {
        "forum": {"url": "https://f.example", "authors": ["Oscar-UDAGAN", "someone"]}
    }
    source = forum.source_from_config(cfg)
    assert source is not None
    assert source.is_internal("someone") is True


def test_pagination_stops_without_a_next_link(monkeypatch):
    client = _FakeClient([LIVE_PAGE])
    monkeypatch.setattr(forum.httpx, "Client", lambda **kw: client)
    list(
        forum.ForumSource(
            "https://forum.example", self_authors=["Oscar-UDAGAN"]
        ).posts()
    )
    assert len(client.calls) == 1


def test_every_forum_row_declares_its_tier(monkeypatch):
    """New sources must set `tier` explicitly rather than lean on the default."""
    client = _FakeClient([LIVE_PAGE])
    monkeypatch.setattr(forum.httpx, "Client", lambda **kw: client)
    posts = list(
        forum.ForumSource(
            "https://forum.example", self_authors=["Oscar-UDAGAN"]
        ).posts()
    )
    assert posts
    assert all("tier" in post for post in posts)


def test_source_from_config_requires_url_and_authors():
    cfg = fixture_config(date(2026, 7, 1))
    assert forum.source_from_config(cfg) is None
