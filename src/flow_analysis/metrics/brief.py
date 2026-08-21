"""The brief — what deserves attention, decided from data rather than memory.

`flow brief` is the deterministic entry point of every practice conversation:
the agent runs it after sync and leads from what it says. The same state must
always produce the same brief, so behaviour cannot drift between sessions —
which is why this is a pure Layer B module over gathered inputs, and why the
depth rule is a table rather than a judgement.

It answers five questions:

  stale?             which sources have not landed recently (GitHub traffic is
                     retained 14 days — a day not collected is gone)
  review due?        weekly / monthly / quarterly, against (:Meta:Review)
  changed?           practice deltas since the last time anything was reviewed
  newly answerable?  measures that cleared their gate with no GateOpened record
                     — the moment a question becomes answerable is an event
  open loops?        prescriptions without outcomes, unconfirmed
                     transformations, registered DevProposals
  healthy?           untrusted posteriors, archive-graph drift, failed assets —
                     the platform noticing its own faults (self-healing starts
                     with the brief saying so)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

# Review cadences, in days. A review is "due" one full period after the last
# one of its kind — or immediately, if that kind has never run.
CADENCES: dict[str, int] = {"weekly": 7, "monthly": 28, "quarterly": 90}

# Raw assets whose staleness matters, with the hours after which they are
# worth naming. GitHub leads: traffic not collected is unrecoverable.
STALE_AFTER_HOURS: dict[str, float] = {
    "raw_github_signals": 24.0,
    "raw_trello_actions": 24.0,
    "raw_trello_cards": 24.0,
    "raw_youtube_signals": 48.0,
    "raw_forum_posts": 48.0,
}


@dataclass(frozen=True)
class BriefInputs:
    """Everything the brief reasons over, gathered by Layer C."""

    today: date
    epoch: date | None
    # asset name -> most recent materialisation, UTC
    materialised_at: dict[str, datetime]
    # cadence -> day of the most recent Review of that cadence
    last_reviews: dict[str, date]
    # enriched days: {"day", "completed", "observed", "production"}
    days: list[dict[str, Any]]
    # measures: {"name", "ok", "n", "needs"}
    measures: list[dict[str, Any]]
    # names of measures with a GateOpened record
    gates_recorded: set[str]
    # knowledge entities: {"name", "entity_type", "day", "status"?, "confirmed"?}
    knowledge: list[dict[str, Any]]
    # names of entities with an inbound OUTCOME_OF
    outcomes_recorded: set[str]
    # posterior measures whose latest snapshot the sampler itself distrusts
    untrusted_today: list[str] = field(default_factory=list)
    # archive signal count vs graph signal count — must agree after a sync
    archive_signals: int = 0
    graph_signals: int = 0
    # knowledge entity names: the archive's current state vs the MCP-owned
    # working set. Divergence is legitimate transiently (a deletion before
    # the next sync) but a missing or shrunken working set is silent data
    # loss on the recall side — the archive itself is unaffected.
    archive_entity_names: set[str] = field(default_factory=set)
    working_set_entity_names: set[str] = field(default_factory=set)
    # assets that failed in the most recent sync run
    last_sync_failed: list[str] = field(default_factory=list)
    now: datetime = field(default_factory=lambda: datetime.now().astimezone())


def stale_sources(inputs: BriefInputs) -> list[dict[str, Any]]:
    """Sources past their staleness threshold, most urgent first."""
    out = []
    for asset, limit in STALE_AFTER_HOURS.items():
        seen = inputs.materialised_at.get(asset)
        if seen is None:
            out.append({"asset": asset, "hours": None, "limit": limit})
            continue
        hours = (inputs.now - seen).total_seconds() / 3600
        if hours > limit:
            out.append({"asset": asset, "hours": round(hours, 1), "limit": limit})
    return sorted(out, key=lambda s: -(s["hours"] or 1e9))


def reviews_due(inputs: BriefInputs) -> list[dict[str, Any]]:
    """Cadences at or past due, with how overdue they are."""
    out = []
    for cadence, period in CADENCES.items():
        last = inputs.last_reviews.get(cadence)
        if last is None:
            anchor = inputs.epoch
            if anchor is None:
                continue
            due = anchor + timedelta(days=period)
            never = True
        else:
            due = last + timedelta(days=period)
            never = False
        if inputs.today >= due:
            out.append(
                {
                    "cadence": cadence,
                    "overdue_days": (inputs.today - due).days,
                    "never_run": never,
                }
            )
    return sorted(out, key=lambda r: -CADENCES[r["cadence"]])


def changed_since_last_look(inputs: BriefInputs) -> dict[str, Any]:
    """Practice movement since the most recent review of any cadence."""
    last = max(inputs.last_reviews.values(), default=None)
    if last is None:
        fresh = inputs.days
    else:
        fresh = [d for d in inputs.days if d["day"] > last.isoformat()]
    return {
        "since": last.isoformat() if last else None,
        "new_days": len(fresh),
        "completed": sum(d["completed"] or 0 for d in fresh),
        "production": sum(d["production"] or 0 for d in fresh),
    }


def newly_answerable(inputs: BriefInputs) -> list[dict[str, Any]]:
    """Measures that cleared their gate without a GateOpened record.

    The whole analytics layer refuses questions the data cannot carry; the
    corollary is that the moment a question *becomes* answerable is itself an
    event, surfaced unprompted rather than waiting to be asked again.
    """
    return [
        {"measure": m["name"], "n": m["n"], "needs": m["needs"]}
        for m in inputs.measures
        if m["ok"] and m["name"] not in inputs.gates_recorded
    ]


def open_loops(inputs: BriefInputs) -> dict[str, list[str]]:
    """Captured things awaiting something: outcomes, confirmation, gates."""
    prescriptions = [
        k["name"]
        for k in inputs.knowledge
        if k["entity_type"] == "Prescription"
        and k["name"] not in inputs.outcomes_recorded
    ]
    unconfirmed = [
        k["name"]
        for k in inputs.knowledge
        if k["entity_type"] == "Transformation"
        and str(k.get("confirmed", "")).lower() not in {"yes", "true"}
    ]
    proposals = [
        k["name"]
        for k in inputs.knowledge
        if k["entity_type"] == "DevProposal"
        and str(k.get("status", "")).lower() == "registered"
    ]
    return {
        "prescriptions_without_outcome": sorted(prescriptions),
        "unconfirmed_transformations": sorted(unconfirmed),
        "registered_dev_proposals": sorted(proposals),
    }


def health(inputs: BriefInputs) -> list[str]:
    """The platform's faults, named — the entry point of self-healing.

    An anomaly reported here is expected to be acted on per the incident
    protocol (CLAUDE.md §2, runbook §7), not read past. Untrusted posteriors
    are listed but only *flagged* as unhealthy when persistent — a young
    practice legitimately produces fits the sampler distrusts.
    """
    items: list[str] = []
    if inputs.last_sync_failed:
        items.append(f"last sync failed: {', '.join(sorted(inputs.last_sync_failed))}")
    if inputs.archive_signals != inputs.graph_signals:
        items.append(
            f"archive-graph drift: {inputs.archive_signals} signal(s) archived, "
            f"{inputs.graph_signals} in the graph — resync, then investigate"
        )
    if len(inputs.untrusted_today) > 10:
        items.append(
            f"{len(inputs.untrusted_today)} untrusted posterior(s) today — "
            "expected while N is small; an incident once gates have opened"
        )
    missing = inputs.archive_entity_names - inputs.working_set_entity_names
    if missing:
        items.append(
            f"memory working set missing {len(missing)} archived entit(ies) "
            f"({len(inputs.working_set_entity_names)} present, "
            f"{len(inputs.archive_entity_names)} archived) — deletion before "
            "a sync is sanctioned; loss is not. `flow memory restore` "
            "rebuilds the working set from the archive"
        )
    return items


def decide_depth(
    stale: list[dict[str, Any]],
    due: list[dict[str, Any]],
    changed: dict[str, Any],
    answerable: list[dict[str, Any]],
    health_items: list[str] | None = None,
) -> tuple[str, list[str]]:
    """The depth table. Same state, same depth, every time.

    deep    a monthly/quarterly review is due, or two or more questions just
            became answerable — the conversation should do real analytical work
    review  something is due or newly answerable, or a week of unexamined days
            has accumulated
    glance  nothing demands more than a status line
    """
    because: list[str] = []
    for review in due:
        label = (
            "never run" if review["never_run"] else f"{review['overdue_days']}d overdue"
        )
        because.append(f"{review['cadence']} review due ({label})")
    for measure in answerable:
        because.append(f"{measure['measure']} newly answerable (N={measure['n']})")
    if changed["new_days"] >= 7:
        because.append(f"{changed['new_days']} unexamined day(s)")
    for source in stale[:3]:
        hours = "never" if source["hours"] is None else f"{source['hours']}h"
        because.append(f"{source['asset']} stale ({hours})")

    for item in health_items or []:
        because.append(f"health: {item}")

    heavy_due = any(r["cadence"] in {"monthly", "quarterly"} for r in due)
    if heavy_due or len(answerable) >= 2:
        return "deep", because
    if due or answerable or changed["new_days"] >= 7 or health_items:
        return "review", because
    return "glance", because or ["nothing due, nothing newly answerable"]


def build(inputs: BriefInputs) -> dict[str, Any]:
    """The whole brief, as one JSON-ready structure."""
    stale = stale_sources(inputs)
    due = reviews_due(inputs)
    changed = changed_since_last_look(inputs)
    answerable = newly_answerable(inputs)
    loops = open_loops(inputs)
    health_items = health(inputs)
    depth, because = decide_depth(stale, due, changed, answerable, health_items)
    return {
        "depth": depth,
        "because": because,
        "stale": stale,
        "reviews_due": due,
        "changed": changed,
        "newly_answerable": answerable,
        "open_loops": loops,
        "health": health_items,
        "untrusted_today": inputs.untrusted_today,
    }


def render(brief: dict[str, Any]) -> str:
    """The brief as prose, for a person rather than the agent."""
    lines = [f"Depth: {brief['depth']}"]
    for reason in brief["because"]:
        lines.append(f"  - {reason}")
    changed = brief["changed"]
    lines.append("")
    lines.append(
        f"Since {changed['since'] or 'the epoch'}: {changed['new_days']} day(s), "
        f"{changed['completed']} completion(s), {changed['production']} production "
        "event(s)."
    )
    if brief["newly_answerable"]:
        lines.append("")
        lines.append("Newly answerable:")
        for measure in brief["newly_answerable"]:
            lines.append(
                f"  - {measure['measure']} "
                f"(N={measure['n']}, needed {measure['needs']})"
            )
    if brief["health"]:
        lines.append("")
        lines.append("Health:")
        for item in brief["health"]:
            lines.append(f"  ! {item}")
    loops = brief["open_loops"]
    open_counts = {k: len(v) for k, v in loops.items() if v}
    if open_counts:
        lines.append("")
        lines.append("Open loops:")
        for kind, count in open_counts.items():
            lines.append(f"  - {kind.replace('_', ' ')}: {count}")
    return "\n".join(lines)
