"""Thin Trello REST client: auth, retries, and action pagination.

Rate limits are 300 requests / 10s per API key and 100 / 10s per token. This
tool's volume is nowhere near either, but 429 and 5xx are still retried with
backoff so an unattended weekly sync doesn't fail on a transient blip.
"""

from __future__ import annotations

import time as _time
from typing import TYPE_CHECKING, Any

import httpx

from .util import json_array as _as_list
from .util import json_object as _as_dict

if TYPE_CHECKING:
    from collections.abc import Iterator

BASE_URL = "https://api.trello.com/1"
MAX_ATTEMPTS = 5
ACTION_PAGE_SIZE = 1000  # Trello's per-request maximum for the actions endpoint


class TrelloError(RuntimeError):
    """A Trello response that was not a success.

    The status is kept as an attribute rather than only in the message, because
    callers branch on it — a 404 on a card means it was deleted, which is normal
    history, while a 401 means the token lapsed and the sync must stop.
    """

    def __init__(self, status: int, method: str, path: str, body: str) -> None:
        """Build the message eagerly, at the point the failure is understood.

        The body is truncated: a huge HTML error page would otherwise bury the
        status line it arrived with.
        """
        super().__init__(f"{method} {path} -> HTTP {status}: {body[:400]}")
        self.status = status
        self.path = path
        self.body = body


class TrelloClient:
    """The one place Trello is spoken to.

    Every call goes through `request`, so retries, auth and error shape are
    defined once. Auth travels as query parameters because that is what the
    Trello API takes — there is no header form.
    """

    def __init__(self, api_key: str, token: str, timeout: float = 30.0) -> None:
        """Hold the credentials and one pooled HTTP client for the session."""
        self._auth = {"key": api_key, "token": token}
        self._http = httpx.Client(base_url=BASE_URL, timeout=timeout)

    def close(self) -> None:
        """Release the pooled connections. `with` does this for you."""
        self._http.close()

    def __enter__(self) -> TrelloClient:
        """Enter a session; use `with client:` so sockets always close."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close on the way out, whether or not the body raised."""
        self.close()

    # --- transport ---------------------------------------------------------

    def request(
        self, method: str, path: str, params: dict[str, Any] | None = None
    ) -> Any:  # noqa: ANN401 - HTTP boundary: this is whatever JSON arrived
        """One request, with the retry policy that makes an unattended sync safe.

        429 and 5xx are retried with exponential backoff, honouring `Retry-After`
        when Trello sends one. Volume here is nowhere near the rate limit, so a
        429 means something transient rather than something this tool is doing.
        A 4xx that is not 429 is raised immediately: retrying a bad token or a
        deleted card only delays the message.
        """
        merged = {**self._auth, **(params or {})}
        delay = 1.0
        last: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._http.request(method, path, params=merged)
            except httpx.HTTPError as exc:
                last = exc
                if attempt == MAX_ATTEMPTS:
                    raise
                _time.sleep(delay)
                delay *= 2
                continue

            if response.status_code in (429, 500, 502, 503, 504):
                last = TrelloError(response.status_code, method, path, response.text)
                if attempt == MAX_ATTEMPTS:
                    raise last
                retry_after = response.headers.get("Retry-After")
                _time.sleep(float(retry_after) if retry_after else delay)
                delay *= 2
                continue

            if response.status_code >= 400:
                raise TrelloError(response.status_code, method, path, response.text)

            if not response.content:
                return None
            try:
                return response.json()
            except ValueError:
                return response.text

        raise last if last else RuntimeError("unreachable")

    # `Any` is the honest type below this line: it is whatever JSON arrived. The
    # typed methods further down narrow it, checked, at the point of use.
    def get(self, path: str, **params: Any) -> Any:  # noqa: ANN401 - HTTP boundary
        """GET, with auth merged in."""
        return self.request("GET", path, params)

    def post(self, path: str, **params: Any) -> Any:  # noqa: ANN401 - HTTP boundary
        """POST, with auth merged in. Trello takes creates as query params."""
        return self.request("POST", path, params)

    def put(self, path: str, **params: Any) -> Any:  # noqa: ANN401 - HTTP boundary
        """PUT, with auth merged in. Trello uses PUT for edits, not PATCH."""
        return self.request("PUT", path, params)

    # --- reads -------------------------------------------------------------

    def whoami(self) -> dict[str, Any]:
        """Who the token belongs to. The cheapest check that auth works."""
        return _as_dict(
            self.get("/members/me", fields="id,username,fullName,email"), "whoami"
        )

    def my_boards(self) -> list[dict[str, Any]]:
        """Open boards this member can see, for `flow discover` to choose from."""
        return _as_list(
            self.get(
                "/members/me/boards",
                filter="open",
                fields="id,name,url,dateLastActivity,idOrganization",
            ),
            "my_boards",
        )

    def board(self, board_id: str) -> dict[str, Any]:
        """One board's metadata. `prefs` carries the timezone the board runs on."""
        return _as_dict(
            self.get(
                f"/boards/{board_id}", fields="id,name,url,prefs,dateLastActivity"
            ),
            "board",
        )

    def lists(self, board_id: str, list_filter: str = "open") -> list[dict[str, Any]]:
        """The board's lists. Names matter: Butler binds by name, not by id."""
        return _as_list(
            self.get(
                f"/boards/{board_id}/lists",
                filter=list_filter,
                fields="id,name,pos,closed",
            ),
            "lists",
        )

    def labels(self, board_id: str) -> list[dict[str, Any]]:
        """The board's labels, which is how the `Flow` label id is resolved."""
        return _as_list(
            self.get(f"/boards/{board_id}/labels", fields="id,name,color", limit=1000),
            "labels",
        )

    def cards(self, board_id: str, card_filter: str = "open") -> list[dict[str, Any]]:
        """Cards on the board, filtered by state.

        `card_filter` is open | closed | all. 'closed' is how archived flow cards
        are recovered — Trello keeps them indefinitely unless explicitly deleted,
        so the drain is reversible and nothing is lost by it.
        """
        return _as_list(
            self.get(
                f"/boards/{board_id}/cards/{card_filter}",
                fields=(
                    "id,name,idList,closed,dateLastActivity,"
                    "due,dueComplete,labels,shortUrl"
                ),
            ),
            "cards",
        )

    def actions(
        self,
        board_id: str,
        *,
        since: str | None = None,
        before: str | None = None,
        action_types: str | None = None,
        page_size: int = ACTION_PAGE_SIZE,
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield pages of board actions, newest first.

        Trello returns at most `page_size` per call, so older history is walked by
        setting `before` to the oldest id seen so far. `since` (an action id or an
        ISO date) bounds the walk at the newest end and is what makes the weekly
        sync incremental.
        """
        cursor = before
        while True:
            params: dict[str, Any] = {"limit": page_size, "memberCreator": "true"}
            if since:
                params["since"] = since
            if cursor:
                params["before"] = cursor
            if action_types:
                params["filter"] = action_types

            page = _as_list(
                self.get(f"/boards/{board_id}/actions", **params), "actions"
            )
            if not page:
                return
            yield page
            if len(page) < page_size:
                return
            cursor = page[-1]["id"]

    # --- writes ------------------------------------------------------------

    def create_list(
        self, board_id: str, name: str, pos: str = "bottom"
    ) -> dict[str, Any]:
        """Add a list. Used only by `bootstrap`, never by the daily cycle."""
        return _as_dict(
            self.post("/lists", idBoard=board_id, name=name, pos=pos), "create_list"
        )

    def create_label(self, board_id: str, name: str, color: str) -> dict[str, Any]:
        """Add a label. Used only by `bootstrap`, never by the daily cycle."""
        return _as_dict(
            self.post("/labels", idBoard=board_id, name=name, color=color),
            "create_label",
        )

    def rename_label(self, label_id: str, name: str) -> dict[str, Any]:
        """Rename a label — which is a rule rebuild, not a cosmetic edit.

        Butler binds labels by NAME. Renaming the `Flow` label silently breaks
        every rule referencing it: the rules still run, still log success, and
        match nothing. See docs/02-butler-rules.md before calling this.
        """
        return _as_dict(self.put(f"/labels/{label_id}", name=name), "rename_label")

    def create_card(
        self,
        list_id: str,
        name: str,
        label_ids: list[str] | None = None,
        # Top by default: the day's five belong above whatever ad-hoc cards are
        # already sitting in `future`, or they are buried on the phone.
        pos: str = "top",
        desc: str | None = None,
    ) -> dict[str, Any]:
        """Create one card.

        The name is a contract: the refill rule creates cards by literal name and
        the model joins on it, so a title that does not match `activities` in
        config/board.yaml records as `never_appeared` forever.
        """
        params: dict[str, Any] = {"idList": list_id, "name": name, "pos": pos}
        if label_ids:
            params["idLabels"] = ",".join(label_ids)
        if desc:
            params["desc"] = desc
        return _as_dict(self.post("/cards", **params), "create_card")

    def archive_card(self, card_id: str) -> dict[str, Any]:
        """Archive, not delete — recoverable, and what the drain rule does."""
        return _as_dict(self.put(f"/cards/{card_id}", closed="true"), "archive_card")

    def delete_card(self, card_id: str) -> Any:  # noqa: ANN401 - HTTP boundary
        """Permanently delete. Nothing in the daily cycle calls this."""
        return self.request("DELETE", f"/cards/{card_id}")


def client_from_env() -> TrelloClient:
    """A client from the credentials in .env, which is the only place they live."""
    from .config import load_env

    key, token = load_env()
    return TrelloClient(key, token)
