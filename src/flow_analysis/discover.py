"""Inspect the Trello account: which boards exist, and what's on the chosen one."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .config import Config, save_resolved

if TYPE_CHECKING:
    from .client import TrelloClient


def list_boards(client: TrelloClient) -> list[dict[str, Any]]:
    """Open boards, most recently active first — the likely one is at the top."""
    boards = client.my_boards()
    return sorted(boards, key=lambda b: b.get("dateLastActivity") or "", reverse=True)


def describe_board(client: TrelloClient, board_id: str) -> dict[str, Any]:
    """Board, lists and labels in one shape, for both selecting and reporting."""
    board = client.board(board_id)
    lists = client.lists(board_id)
    labels = client.labels(board_id)
    open_cards = client.cards(board_id, "open")

    per_list: dict[str, int] = {}
    for card in open_cards:
        per_list[card["idList"]] = per_list.get(card["idList"], 0) + 1

    return {
        "board": board,
        "lists": [{**lst, "open_cards": per_list.get(lst["id"], 0)} for lst in lists],
        "labels": labels,
        "open_card_count": len(open_cards),
    }


def render_boards(boards: list[dict[str, Any]]) -> str:
    """The board list as a table, with the id needed to select one."""
    lines = [f"{len(boards)} open board(s):", ""]
    for board in boards:
        last = (board.get("dateLastActivity") or "")[:10]
        lines.append(
            f"  {board['id']}  {board['name']}   (last activity {last or '?'})"
        )
    lines += ["", "Select one with:  flow discover --select <board-id>"]
    return "\n".join(lines)


def render_board(detail: dict[str, Any], cfg: Config) -> str:
    """The selected board against what the config expects.

    Shows the board's own timezone alongside the configured one: they disagree
    silently, and every flow-day boundary depends on getting that right.
    """
    board = detail["board"]
    tz = (board.get("prefs") or {}).get("timezone")
    lines = [
        f"Board: {board['name']}  ({board['id']})",
        f"  {board.get('url', '')}",
        f"  open cards: {detail['open_card_count']}",
    ]
    if tz:
        lines.append(f"  board timezone: {tz}")
    lines += ["", "Lists:"]
    for lst in detail["lists"]:
        lines.append(
            f"  {lst['id']}  {lst['name']:<24} {lst['open_cards']:>4} open cards"
        )

    lines += ["", "Labels:"]
    for label in detail["labels"]:
        name = label.get("name") or "(unnamed)"
        lines.append(f"  {label['id']}  {name:<24} {label.get('color')}")

    wanted = {role: lr.name for role, lr in cfg.lists.items()}
    have = {lst["name"]: lst["id"] for lst in detail["lists"]}
    lines += ["", "Role mapping against config/board.yaml:"]
    for role, name in wanted.items():
        status = "found" if name in have else "MISSING -> would be created"
        lines.append(f"  {role:<12} -> {name!r}: {status}")
    label_names = {(lb.get("name") or "") for lb in detail["labels"]}
    status = "found" if cfg.label_name in label_names else "MISSING -> would be created"
    lines.append(f"  {'label':<12} -> {cfg.label_name!r}: {status}")
    lines += ["", "Apply with:  flow bootstrap --apply"]
    return "\n".join(lines)


def select_board(client: TrelloClient, cfg: Config, board_id: str) -> dict[str, Any]:
    """Record the chosen board (and any already-matching list/label ids)."""
    detail = describe_board(client, board_id)
    board = detail["board"]

    cfg.resolved["board_id"] = board["id"]
    cfg.resolved["board_name"] = board["name"]
    cfg.resolved["board_url"] = board.get("url")
    cfg.resolved["board_timezone"] = (board.get("prefs") or {}).get("timezone")

    by_name = {lst["name"]: lst["id"] for lst in detail["lists"]}
    for lr in cfg.lists.values():
        if lr.name in by_name:
            lr.id = by_name[lr.name]

    for label in detail["labels"]:
        if (label.get("name") or "") == cfg.label_name:
            cfg.resolved["label_id"] = label["id"]
            break

    save_resolved(cfg)
    return detail
