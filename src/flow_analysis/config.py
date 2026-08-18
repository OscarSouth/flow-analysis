"""Config and credential loading.

Two files, deliberately separated:

  config/board.yaml     hand-authored intent   (names, activities, schedule, start date)
  config/resolved.json  machine-written facts  (Trello ids discovered from the API)

Keeping them apart means tooling never has to rewrite the YAML, so its comments
survive, and a re-discovery can never clobber a human decision.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path
from typing import Any

import yaml

from .util import json_object

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "board.yaml"
RESOLVED_PATH = REPO_ROOT / "config" / "resolved.json"
# Overridable so tests (and any throwaway experiment) never touch the real store.
DATA_DIR = Path(os.environ.get("FLOW_ANALYSIS_DATA_DIR") or REPO_ROOT / "data")
ENV_PATH = REPO_ROOT / ".env"

# "drain" is a staging list, empty except for the instant at 04:00 when the purge
# rule sweeps into it. It exists because Trello offers no "archive cards in list X
# with label Y" action — see docs/02-butler-rules.md.
LIST_ROLES = ("future", "present", "past", "drain")


class ConfigError(RuntimeError):
    """Configuration that cannot be worked around, only fixed.

    Every message names the command that fixes it — these surface to someone at
    a terminal, and a config error that does not say what to run next is only
    half a message.
    """


def read_env() -> dict[str, str]:
    """Every key in .env, with the process environment winning.

    Credentials live here and nowhere else: `.env` is chmod 600 and gitignored,
    so nothing secret reaches `config/` or the repo.
    """
    values: dict[str, str] = {}
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
    for key in [
        *values,
        "GITHUB_TOKEN",
        "YOUTUBE_CLIENT_ID",
        "YOUTUBE_CLIENT_SECRET",
        "YOUTUBE_REFRESH_TOKEN",
    ]:
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def env_value(name: str) -> str | None:
    """One credential, or None. Empty string reads as absent, not as set."""
    return read_env().get(name) or None


def load_env() -> tuple[str, str]:
    """Return (api_key, token). Process env wins over .env so one-off overrides work."""
    values: dict[str, str] = {}
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("'\"")

    key = os.environ.get("TRELLO_API_KEY") or values.get("TRELLO_API_KEY", "")
    token = os.environ.get("TRELLO_TOKEN") or values.get("TRELLO_TOKEN", "")
    if not key or not token:
        raise ConfigError(
            "Missing TRELLO_API_KEY / TRELLO_TOKEN.\n"
            "Copy .env.example to .env and fill it in (see docs/01-setup.md), "
            "or export them in your shell."
        )
    return key, token


@dataclass
class ListRole:
    """One of the four board lists, by role rather than by Trello id.

    The role is what the code reasons about; the name is what Butler binds to
    and what a person sees; the id is what the API needs. Keeping the three
    together is what makes a rename in Trello visible here.
    """

    role: str
    name: str
    id: str | None = None


@dataclass
class Config:
    """Hand-authored intent plus machine-resolved ids, as one object.

    `intent` comes from config/board.yaml and is safe to edit; `resolved`
    comes from config/resolved.json and is written by discover/bootstrap.
    They stay separate so re-discovery can never clobber a human decision,
    and so tooling never rewrites the YAML and loses its comments.
    """

    intent: dict[str, Any]
    resolved: dict[str, Any]
    lists: dict[str, ListRole]
    activities: list[str]
    descriptions: dict[str, str]
    label_name: str
    label_colour: str
    timezone: str
    drain_at: time
    refill_at: time
    start_date: date | None

    # --- resolved ids ------------------------------------------------------

    @property
    def board_id(self) -> str | None:
        """The selected board, or None before `flow discover` has run."""
        return self.resolved.get("board_id")

    @property
    def board_name(self) -> str | None:
        """The board's name as Trello last reported it."""
        return self.resolved.get("board_name")

    @property
    def label_id(self) -> str | None:
        """The `Flow` label id — what the drain keys off entirely."""
        return self.resolved.get("label_id")

    @property
    def list_id_to_role(self) -> dict[str, str]:
        """Reverse lookup for reading actions back, which carry ids only."""
        return {lr.id: role for role, lr in self.lists.items() if lr.id}

    def list_id(self, role: str) -> str | None:
        """The id for a role, or None if it has not been resolved yet."""
        return self.lists[role].id

    def require_board(self) -> str:
        """The board id, or the instruction to select one."""
        if not self.board_id:
            raise ConfigError("No board selected yet. Run: flow discover")
        return self.board_id

    def require_lists(self) -> dict[str, ListRole]:
        """All four lists with ids resolved, or the instruction to resolve them.

        Fails on the whole set rather than one at a time: a half-resolved board
        breaks the drain in ways that look like missing data rather than a
        missing id.
        """
        missing = [role for role, lr in self.lists.items() if not lr.id]
        if missing:
            raise ConfigError(
                f"List ids unresolved for: {', '.join(missing)}. "
                "Run: flow bootstrap --apply"
            )
        return self.lists

    def require_list_id(self, role: str) -> str:
        """The resolved id for one role, or the instruction to resolve it.

        `require_lists()` already raises on unresolved ids, but it hands back
        `ListRole` whose `id` stays optional, so every caller was re-deriving
        that guarantee. This states it once.
        """
        list_id = self.require_lists()[role].id
        if list_id is None:  # pragma: no cover - require_lists raises first
            raise ConfigError(
                f"List id unresolved for {role}. Run: flow bootstrap --apply"
            )
        return list_id

    def require_label(self) -> str:
        """The `Flow` label id, or the instruction to resolve it."""
        if not self.label_id:
            raise ConfigError("Flow label unresolved. Run: flow bootstrap --apply")
        return self.label_id


def _parse_time(value: str, field_name: str) -> time:
    try:
        hh, mm = str(value).split(":")
        return time(int(hh), int(mm))
    # Config surface: the message is the point. Whatever went wrong in there —
    # unpacking, int(), time() — the caller needs to be told what to type, not
    # which builtin objected.
    except Exception as exc:
        raise ConfigError(
            f"schedule.{field_name} must be HH:MM, got {value!r}"
        ) from exc


def _load_resolved(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json_object(json.loads(path.read_text()), str(path))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc


def load_config(
    path: Path = CONFIG_PATH, resolved_path: Path = RESOLVED_PATH
) -> Config:
    """Read intent and resolved ids into one Config.

    Neither file is required to be complete: a fresh checkout has no
    resolved.json at all, and every consumer that needs an id asks for it
    through a `require_*` method that says how to obtain it.
    """
    if not path.exists():
        raise ConfigError(f"Config not found: {path}")
    intent = yaml.safe_load(path.read_text()) or {}
    resolved = _load_resolved(resolved_path)

    lists_raw = intent.get("lists") or {}
    resolved_lists = resolved.get("lists") or {}
    lists: dict[str, ListRole] = {}
    for role in LIST_ROLES:
        entry = lists_raw.get(role) or {}
        r_entry = resolved_lists.get(role) or {}
        lists[role] = ListRole(
            role=role,
            # A resolved name is the list's real name on the board and wins, so a
            # rename in Trello shows up here rather than silently diverging.
            name=r_entry.get("name") or entry.get("name") or role,
            id=r_entry.get("id"),
        )

    # Activities are either bare names or {name, description} mappings; both are
    # accepted so a description can be added without reshaping the whole file.
    activities: list[str] = []
    descriptions: dict[str, str] = {}
    for entry in intent.get("activities") or []:
        if isinstance(entry, str):
            activities.append(entry)
        elif isinstance(entry, dict) and entry.get("name"):
            activities.append(entry["name"])
            if entry.get("description"):
                descriptions[entry["name"]] = entry["description"]
        else:
            raise ConfigError(
                f"activities entry is neither a name nor a mapping: {entry!r}"
            )
    if not activities:
        raise ConfigError("config/board.yaml lists no activities")

    label = intent.get("label") or {}
    schedule = intent.get("schedule") or {}
    history = intent.get("history") or {}

    purge = _parse_time(schedule.get("drain_at", "04:00"), "drain_at")
    spawn = _parse_time(schedule.get("refill_at", "06:00"), "refill_at")
    if purge >= spawn:
        raise ConfigError(
            f"schedule.drain_at ({purge}) must be earlier than refill_at ({spawn}), "
            "or the purge would archive the cards the spawn just created."
        )

    start_raw = history.get("start_date")
    if isinstance(start_raw, date):
        start = start_raw
    elif start_raw:
        start = date.fromisoformat(str(start_raw))
    else:
        start = None

    return Config(
        intent=intent,
        resolved=resolved,
        lists=lists,
        activities=activities,
        descriptions=descriptions,
        label_name=label.get("name") or "Flow",
        label_colour=label.get("colour") or "green",
        timezone=schedule.get("timezone") or "Europe/London",
        drain_at=purge,
        refill_at=spawn,
        start_date=start,
    )


def save_resolved(cfg: Config, path: Path = RESOLVED_PATH) -> None:
    """Write the discovered ids back, and update the live Config to match.

    Never hand-edited — this file is machine-written, which is exactly why the
    hand-authored intent lives in a different file.
    """
    payload = dict(cfg.resolved)
    payload["lists"] = {
        role: {"id": lr.id, "name": lr.name} for role, lr in cfg.lists.items()
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    cfg.resolved = payload
