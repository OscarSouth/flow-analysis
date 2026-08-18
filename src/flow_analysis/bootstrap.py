"""Idempotent, non-destructive board preparation.

The target board already holds real work, so this only ever *adds*: it never
renames, moves, or archives anything that exists. Running it twice is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .config import Config, save_resolved

if TYPE_CHECKING:
    from .client import TrelloClient


@dataclass
class Action:
    """One change bootstrap would make, or found already in place.

    The same object serves the dry run and the real run — `applied` is the only
    difference — so what you are shown is literally what will be done.
    """

    kind: str  # "create_list" | "create_label" | "reuse"
    target: str
    detail: str
    applied: bool = False

    def __str__(self) -> str:
        """One aligned line per action, marked + created, ~ renamed, = reused."""
        mark = {"create_list": "+", "create_label": "+", "rename_label": "~"}.get(
            self.kind, "="
        )
        state = "" if self.applied or self.kind == "reuse" else "  (dry run)"
        return f"  {mark} {self.target:<28} {self.detail}{state}"


def _find_adoptable(
    labels: list[dict[str, Any]], adopt: str | None
) -> dict[str, Any] | None:
    """An existing label to name, rather than adding another one.

    `adopt` is either a label id or a colour. Only *unnamed* labels are eligible:
    renaming a label you already use would silently relabel every card carrying it.
    """
    if not adopt:
        return None
    for label in labels:
        if (label.get("name") or "").strip():
            continue
        if label["id"] == adopt or label.get("color") == adopt:
            return label
    return None


def plan(client: TrelloClient, cfg: Config, adopt: str | None = None) -> list[Action]:
    """What would need creating or adopting, changing nothing.

    `adopt` takes over an existing label by name instead of creating a second
    one — two labels both called Flow is a silent disaster, because Butler binds
    by name and would match whichever it found first.
    """
    board_id = cfg.require_board()
    existing_lists = {lst["name"]: lst for lst in client.lists(board_id)}
    existing_labels = client.labels(board_id)

    actions: list[Action] = []
    for role, lr in cfg.lists.items():
        if lr.name in existing_lists:
            actions.append(
                Action("reuse", f"list {lr.name!r}", f"exists, role {role!r}")
            )
        else:
            actions.append(
                Action("create_list", f"list {lr.name!r}", f"create for role {role!r}")
            )

    if any((lb.get("name") or "") == cfg.label_name for lb in existing_labels):
        actions.append(Action("reuse", f"label {cfg.label_name!r}", "exists"))
    else:
        adoptable = _find_adoptable(existing_labels, adopt)
        if adoptable:
            actions.append(
                Action(
                    "rename_label",
                    f"label {cfg.label_name!r}",
                    f"name the unnamed {adoptable.get('color')} label "
                    f"{adoptable['id']}",
                )
            )
        else:
            actions.append(
                Action(
                    "create_label",
                    f"label {cfg.label_name!r}",
                    f"create ({cfg.label_colour})",
                )
            )
    return actions


def apply(client: TrelloClient, cfg: Config, adopt: str | None = None) -> list[Action]:
    """Do what `plan` described, then write the resolved ids.

    One of only two write paths this repo has into Trello. Re-running is safe:
    anything already present is reused rather than duplicated.
    """
    board_id = cfg.require_board()
    existing_lists = {lst["name"]: lst for lst in client.lists(board_id)}
    existing_labels = client.labels(board_id)

    actions: list[Action] = []

    for role, lr in cfg.lists.items():
        found = existing_lists.get(lr.name)
        if found:
            lr.id = found["id"]
            actions.append(
                Action(
                    "reuse", f"list {lr.name!r}", f"{found['id']} (role {role!r})", True
                )
            )
        else:
            created = client.create_list(board_id, lr.name)
            lr.id = created["id"]
            actions.append(
                Action(
                    "create_list",
                    f"list {lr.name!r}",
                    f"{created['id']} (role {role!r})",
                    True,
                )
            )

    label = next(
        (lb for lb in existing_labels if (lb.get("name") or "") == cfg.label_name), None
    )
    if label is not None:
        actions.append(Action("reuse", f"label {cfg.label_name!r}", label["id"], True))
    else:
        adoptable = _find_adoptable(existing_labels, adopt)
        if adoptable:
            label = client.rename_label(adoptable["id"], cfg.label_name)
            actions.append(
                Action(
                    "rename_label",
                    f"label {cfg.label_name!r}",
                    f"{label['id']} (was unnamed {label.get('color')})",
                    True,
                )
            )
        else:
            label = client.create_label(board_id, cfg.label_name, cfg.label_colour)
            actions.append(
                Action("create_label", f"label {cfg.label_name!r}", label["id"], True)
            )
    cfg.resolved["label_id"] = label["id"]

    save_resolved(cfg)
    return actions


def safety_check(client: TrelloClient, cfg: Config) -> dict[str, Any]:
    """Report what the purge rule would touch right now.

    The purge archives cards in In/Progressing *carrying the Flow label*. This
    lists them, and — more importantly — lists the unlabelled cards in those same
    lists that must survive. Read this before enabling the rule.
    """
    board_id = cfg.require_board()
    label_id = cfg.require_label()
    lists = cfg.require_lists()
    watched = {lists["future"].id: "future", lists["present"].id: "present"}

    would_archive: list[dict[str, Any]] = []
    would_survive: list[dict[str, Any]] = []
    for card in client.cards(board_id, "open"):
        role = watched.get(card["idList"])
        if role is None:
            continue
        entry = {"name": card["name"], "id": card["id"], "list": role}
        if any(lb["id"] == label_id for lb in card.get("labels", [])):
            would_archive.append(entry)
        else:
            would_survive.append(entry)
    return {"would_archive": would_archive, "would_survive": would_survive}


def render_safety(report: dict[str, Any]) -> str:
    """Print the drain's blast radius: what it would archive, what survives.

    Read both lists before touching anything that affects which cards carry the
    `Flow` label. Long-running cards must appear under "would survive" — the
    drain is destructive by design, and this is the check that it is aimed right.
    """
    lines = [
        "Drain impact, as of now",
        "(04:00 sweeps these to 'drain'; 04:05 archives that list):",
        "",
        "  WOULD BE SWEPT AND ARCHIVED (labelled Flow):",
    ]
    if report["would_archive"]:
        lines += [f"    - [{c['list']}] {c['name']}" for c in report["would_archive"]]
    else:
        lines.append("    (none)")
    lines += ["", "  WOULD SURVIVE (no Flow label — your long-running work):"]
    if report["would_survive"]:
        lines += [f"    - [{c['list']}] {c['name']}" for c in report["would_survive"]]
    else:
        lines.append("    (none)")
    lines += [
        "",
        "  If anything you care about appears in the first group, remove the Flow",
        "  label from it before 04:00.",
    ]
    return "\n".join(lines)
