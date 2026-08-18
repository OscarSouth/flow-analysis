"""Credential capture, without the shell in the way.

Pasting a secret into a shell command is error-prone in ways that are nobody's
fault: the quoting differs between bash and zsh, an interactive prompt reads as
a placeholder, and whatever you type lands in shell history. So the value is
never typed as part of a command here — it is read with `getpass`, which does
not echo and does not touch history, then written straight to `.env`.

`.env` is the only place credentials live: chmod 600, gitignored, never in
`config/` and never in the repo.
"""

from __future__ import annotations

import os
import stat
from getpass import getpass
from typing import TYPE_CHECKING, Any

from .config import ENV_PATH
from .util import json_object

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def set_env_value(name: str, value: str, path: Path = ENV_PATH) -> str:
    """Add or replace one key in .env, leaving every other line untouched.

    Returns "added" or "replaced" so the caller can say which happened without
    ever printing the value.
    """
    lines = path.read_text().splitlines() if path.exists() else []
    outcome = "added"
    for index, line in enumerate(lines):
        if line.strip().startswith(f"{name}="):
            lines[index] = f"{name}={value}"
            outcome = "replaced"
            break
    else:
        lines.append(f"{name}={value}")

    path.write_text("\n".join(lines) + "\n")
    # Belt and braces: a fresh file would otherwise inherit the umask.
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return outcome


def prompt_secret(label: str) -> str:
    """Read a secret without echoing it. Empty input aborts."""
    return getpass(f"{label} (input is hidden, press Enter to cancel): ").strip()


def oauth_loopback(
    auth_url: str,
    token_url: str,
    client_id: str,
    client_secret: str,
    scopes: Sequence[str],
    timeout: float = 300.0,
) -> str:
    """Run the OAuth authorisation-code flow against a loopback redirect.

    A Desktop-app client redirects to 127.0.0.1, so the code arrives directly and
    nothing has to be copied out of a browser by hand. You approve in your own
    browser session; the password never touches this process.

    Returns the refresh token. `access_type=offline` with `prompt=consent` is what
    makes Google issue one — without both, a re-authorisation returns only a
    short-lived access token and the next sync fails days later.
    """
    import http.server
    import socket
    import threading
    import urllib.parse
    import webbrowser

    import httpx

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    redirect_uri = f"http://127.0.0.1:{port}"

    received: dict[str, str] = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        # Name set by BaseHTTPRequestHandler, not by us.
        def do_GET(self) -> None:
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            for key in ("code", "error"):
                if key in params:
                    received[key] = params[key][0]
            body = (
                "<h2>Authorised.</h2><p>You can close this tab and return to the "
                "terminal.</p>"
                if "code" in received
                else f"<h2>Authorisation "
                f"failed.</h2><p>{received.get('error', 'unknown')}</p>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())
            done.set()

        # Signature is BaseHTTPRequestHandler's; `Any` is what it passes.
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: ANN401
            """Silence the per-request log line; the console belongs to the prompt."""
            return

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    url = f"{auth_url}?{query}"
    print("\nOpening your browser to approve access.")
    print("If it does not open, paste this into your browser:\n")
    print(f"  {url}\n")
    webbrowser.open(url)

    try:
        if not done.wait(timeout):
            raise RuntimeError("Timed out waiting for authorisation.")
    finally:
        server.shutdown()

    if "code" not in received:
        raise RuntimeError(
            f"Authorisation failed: {received.get('error', 'no code returned')}"
        )

    response = httpx.post(
        token_url,
        data={
            "code": received["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30.0,
    )
    if not response.is_success:
        detail = (response.json() or {}).get("error_description") or response.text
        raise RuntimeError(f"Token exchange failed ({response.status_code}): {detail}")

    payload = json_object(response.json(), "Google token exchange")
    refresh = payload.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        raise RuntimeError(
            "Google returned no refresh token. This happens when the app was "
            "already authorised — revoke it at myaccount.google.com/permissions "
            "and run this again."
        )
    return refresh
