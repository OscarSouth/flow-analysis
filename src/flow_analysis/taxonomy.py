"""The capture taxonomy — what the agent may write, and in what shape.

The knowledge layer accumulates the practice's own record of itself: reviews,
interpretations, prescriptions, transformations, hypotheses, opened gates,
platform proposals, observations, beliefs, references, journal entries.
Consistency comes from this vocabulary being **closed** and validated at
capture — an entity outside it is refused loudly, never silently stored.

In CSF terms (docs/08): Review and Prescription are T_L events, Interpretation
and Hypothesis are E_L, Transformation records a change to the practice or the
platform, DevProposal is a proposed meta-transformation of the platform itself.
Belief and Reference are the socratic layer (docs/10): a Belief exists as a
node *because* all belief is provisional — it carries a status, never finality,
and revision arrives as a `revises` edge from its successor rather than as an
edit that forgets the belief was ever held.

Memory-MCP entities carry only a name, an entityType and free-text observation
lines, so required fields travel as `key: value` observation lines — parsed
here into node properties, with every original line kept verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

VALID_KINDS = frozenset({"R-semantics", "T", "E", "platform"})

# A belief is never final: `held` is current, `revised` means a successor
# exists (linked by `revises`), `retired` means abandoned without one.
VALID_BELIEF_STATUS = frozenset({"held", "revised", "retired"})


@dataclass(frozen=True)
class EntitySpec:
    """One entity type: where it lands in the graph, and what it must carry."""

    labels: tuple[str, ...]
    required: tuple[str, ...]


# The closed set. Adding a type here is itself a platform transformation and
# should arrive with a DevProposal.
ENTITY_TYPES: dict[str, EntitySpec] = {
    "Review": EntitySpec(("Meta", "Review"), ("day", "cadence", "window")),
    "Interpretation": EntitySpec(
        ("Fct", "Interpretation"), ("day", "measure", "reading")
    ),
    "Prescription": EntitySpec(("Meta", "Prescription"), ("day", "change", "review")),
    "Transformation": EntitySpec(
        ("Meta", "Transformation"), ("day", "kind", "what", "confirmed")
    ),
    "Hypothesis": EntitySpec(("Meta", "Hypothesis"), ("day", "claim", "bar", "prior")),
    "GateOpened": EntitySpec(("Meta", "GateOpened"), ("day", "measure", "n")),
    "DevProposal": EntitySpec(
        ("Meta", "DevProposal"), ("day", "motivation", "proposal", "gate", "status")
    ),
    "Observation": EntitySpec(("Stg", "Note"), ("day", "note")),
    # The socratic layer, added by the socratic-engagement transformation
    # (2026-08-18). Meta as first label is load-bearing: it is what carries
    # these through the knowledge Cypher filters and the meta_name constraint
    # without touching knowledge.py or schema.py.
    "Belief": EntitySpec(("Meta", "Belief"), ("day", "claim", "status")),
    "Reference": EntitySpec(("Meta", "Reference"), ("day", "title", "source")),
    # Interactive journalling (2026-08-19): a first-person reflection on the
    # day's practice. An optional `activities: Train, Express` line (comma-
    # separated mode names) earns structural REFLECTS_ON edges to the day's
    # (:Stg:FlowRow) state rows; an optional `measure:` line earns CONCERNS.
    "Journal": EntitySpec(("Meta", "Journal"), ("day", "note")),
}

# The closed relation set, memory relationType -> graph relationship type.
RELATION_TYPES: dict[str, str] = {
    "concerns": "CONCERNS",
    "on_day": "ON_DAY",
    "follows_from": "FOLLOWS_FROM",
    "tests": "TESTS",
    "prescribed_by": "PRESCRIBED_BY",
    "outcome_of": "OUTCOME_OF",
    "enabled_by": "ENABLED_BY",
    # Socratic relations: the revises chain is provisionality made structural.
    # A new value here must also join LINKS_LOAD in assets/knowledge.py, or it
    # is written to the graph but invisible on read-back — pinned by
    # tests/test_knowledge.py.
    "revises": "REVISES",
    "challenges": "CHALLENGES",
    "supports": "SUPPORTS",
    "cites": "CITES",
}


class TaxonomyError(ValueError):
    """A captured entity or relation falls outside the closed vocabulary.

    Raised at capture time, before anything reaches the archive: a taxonomy
    mistake is cheap to fix in the memory working set and permanent everywhere
    after it.
    """


def parse_fields(observations: list[str]) -> dict[str, str]:
    """Extract `key: value` lines into fields; free-text lines are left alone.

    Only the first colon splits, so values may contain colons. Keys are
    lower-snake by convention and normalised here.
    """
    fields: dict[str, str] = {}
    for line in observations:
        head, sep, tail = line.partition(":")
        key = head.strip().lower().replace(" ", "_")
        if sep and tail.strip() and " " not in key and key.isidentifier():
            fields.setdefault(key, tail.strip())
    return fields


def validate_entity(entity: dict[str, Any]) -> dict[str, Any]:
    """Check one memory entity against the taxonomy; return its parsed form.

    Refuses loudly on: unknown entityType, missing required fields, an
    unparseable `day`, a Transformation whose `kind` is outside the closed
    kind set (the five modes are fixed by decision — `R-semantics` is the only
    R-shaped change that exists), or a Belief whose `status` is outside the
    closed status set (a belief is provisional by construction, so its status
    must say where in the revision lifecycle it stands).
    """
    name = entity.get("name") or ""
    kind = entity.get("entityType") or ""
    spec = ENTITY_TYPES.get(kind)
    if spec is None:
        raise TaxonomyError(
            f"{name!r}: entityType {kind!r} is outside the closed taxonomy "
            f"{sorted(ENTITY_TYPES)}. Fix or delete the memory entity."
        )
    observations = [str(line) for line in entity.get("observations") or []]
    fields = parse_fields(observations)
    missing = [field for field in spec.required if field not in fields]
    if missing:
        raise TaxonomyError(
            f"{name!r} ({kind}): missing required field(s) {missing} — add "
            f"`field: value` observation line(s)."
        )
    try:
        date.fromisoformat(fields["day"])
    except ValueError as exc:
        raise TaxonomyError(
            f"{name!r} ({kind}): day {fields['day']!r} is not an ISO date."
        ) from exc
    if kind == "Transformation" and fields["kind"] not in VALID_KINDS:
        raise TaxonomyError(
            f"{name!r}: Transformation kind {fields['kind']!r} not in "
            f"{sorted(VALID_KINDS)} — the five modes are fixed by decision, so "
            "there is no R-membership kind."
        )
    if kind == "Belief" and fields["status"] not in VALID_BELIEF_STATUS:
        raise TaxonomyError(
            f"{name!r}: Belief status {fields['status']!r} not in "
            f"{sorted(VALID_BELIEF_STATUS)} — all belief is provisional, so a "
            "belief is `held`, `revised` (successor linked by `revises`) or "
            "`retired`, never final. Fix the status line."
        )
    return {
        "name": name,
        "entity_type": kind,
        "labels": list(spec.labels),
        "observations": observations,
        **fields,
    }


def validate_relation(relation: dict[str, Any]) -> dict[str, Any]:
    """Check one memory relation; return it with the graph relationship type."""
    rel = relation.get("relationType") or ""
    mapped = RELATION_TYPES.get(rel)
    if mapped is None:
        raise TaxonomyError(
            f"relation {relation.get('from')!r} -> {relation.get('to')!r}: "
            f"relationType {rel!r} not in {sorted(RELATION_TYPES)}."
        )
    return {
        "from_name": relation["from"],
        "to_name": relation["to"],
        "rel_type": mapped,
    }
