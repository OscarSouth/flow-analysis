"""The capture taxonomy and the memory-to-archive pipeline.

Consistency of the knowledge layer rests on two mechanisms: a closed vocabulary
that refuses at capture, and content-hash snapshots that keep the archive
append-only over a mutable working set. Both are pinned here, offline.
"""

from __future__ import annotations

import json

import pytest
from dagster import build_asset_context

from flow_analysis import store
from flow_analysis.assets import raw as raw_assets
from flow_analysis.taxonomy import (
    TaxonomyError,
    parse_fields,
    validate_entity,
    validate_relation,
)


def _entity(**overrides: object) -> dict[str, object]:
    base = {
        "type": "entity",
        "name": "review:2026-08-18:weekly",
        "entityType": "Review",
        "observations": ["day: 2026-08-18", "cadence: weekly", "window: 7"],
    }
    return {**base, **overrides}


# --- taxonomy ----------------------------------------------------------------


def test_a_valid_entity_parses_with_fields_promoted():
    parsed = validate_entity(_entity())
    assert parsed["labels"] == ["Meta", "Review"]
    assert parsed["cadence"] == "weekly"
    assert parsed["day"] == "2026-08-18"


def test_an_unknown_entity_type_is_refused():
    """The vocabulary is closed: adding a type is a platform transformation."""
    with pytest.raises(TaxonomyError, match="closed taxonomy"):
        validate_entity(_entity(entityType="Musing"))


def test_a_missing_required_field_is_refused():
    with pytest.raises(TaxonomyError, match="cadence"):
        validate_entity(_entity(observations=["day: 2026-08-18", "window: 7"]))


def test_a_malformed_day_is_refused():
    with pytest.raises(TaxonomyError, match="ISO date"):
        validate_entity(
            _entity(observations=["day: yesterday", "cadence: weekly", "window: 7"])
        )


def test_r_membership_transformations_do_not_exist():
    """The five modes are fixed by decision — only R-semantics can change."""
    bad = _entity(
        entityType="Transformation",
        observations=[
            "day: 2026-08-18",
            "kind: R-membership",
            "what: swap Express for Perform",
            "confirmed: yes",
        ],
    )
    with pytest.raises(TaxonomyError, match="fixed by decision"):
        validate_entity(bad)


def test_relations_outside_the_closed_set_are_refused():
    with pytest.raises(TaxonomyError, match="relationType"):
        validate_relation({"from": "a", "to": "b", "relationType": "vibes_with"})


def test_a_valid_belief_parses_under_meta_labels():
    """Beliefs ride the Meta label so they propagate with zero Cypher changes."""
    parsed = validate_entity(
        _entity(
            name="belief:2026-08-18:all-belief-is-provisional",
            entityType="Belief",
            observations=[
                "day: 2026-08-18",
                "claim: all belief is provisional",
                "status: held",
            ],
        )
    )
    assert parsed["labels"] == ["Meta", "Belief"]
    assert parsed["claim"] == "all belief is provisional"
    assert parsed["status"] == "held"


def test_a_belief_status_outside_the_lifecycle_is_refused():
    """All belief is provisional — `final` is exactly the status that cannot exist."""
    bad = _entity(
        name="belief:2026-08-18:settled",
        entityType="Belief",
        observations=[
            "day: 2026-08-18",
            "claim: this one is settled",
            "status: final",
        ],
    )
    with pytest.raises(TaxonomyError, match="provisional"):
        validate_entity(bad)


def test_a_belief_without_a_claim_is_refused():
    with pytest.raises(TaxonomyError, match="claim"):
        validate_entity(
            _entity(
                name="belief:2026-08-18:empty",
                entityType="Belief",
                observations=["day: 2026-08-18", "status: held"],
            )
        )


def test_a_valid_reference_parses_with_its_source():
    parsed = validate_entity(
        _entity(
            name="reference:2026-08-18:padesky-2019",
            entityType="Reference",
            observations=[
                "day: 2026-08-18",
                "title: Action, Dialogue & Discovery",
                "source: https://www.padesky.com/clinical-corner/publications/",
            ],
        )
    )
    assert parsed["labels"] == ["Meta", "Reference"]
    assert parsed["title"] == "Action, Dialogue & Discovery"


def test_socratic_relations_map_to_graph_types():
    """The revises chain is provisionality made structural."""
    revised = validate_relation(
        {
            "from": "belief:2026-09-01:successor",
            "to": "belief:2026-08-18:original",
            "relationType": "revises",
        }
    )
    assert revised["rel_type"] == "REVISES"
    for relation, rel_type in [
        ("challenges", "CHALLENGES"),
        ("supports", "SUPPORTS"),
        ("cites", "CITES"),
    ]:
        mapped = validate_relation({"from": "a", "to": "b", "relationType": relation})
        assert mapped["rel_type"] == rel_type


def test_every_entity_label_is_covered_by_the_knowledge_cypher():
    """A first label outside {Meta, Fct, Stg} silently misses every filter.

    The knowledge Cypher matches on `n:Meta OR n:Interpretation OR n:Note`, and
    the schema constrains exactly those labels — so a taxonomy entry with a new
    top label would be written and then invisible. Pin the invariant here
    because no runtime path checks it.
    """
    from flow_analysis.taxonomy import ENTITY_TYPES

    for entity_type, spec in ENTITY_TYPES.items():
        assert spec.labels[0] in {"Meta", "Fct", "Stg"}, entity_type


def test_every_relation_type_is_readable_back_from_the_graph():
    """A relation in the taxonomy but not LINKS_LOAD is written, then lost.

    LINKS_CYPHER writes any mapped type, but LINKS_LOAD enumerates readable
    types literally — the one place a new relation does not propagate on its
    own. ON_DAY is structural (derived in post-cypher, deliberately excluded).
    """
    from flow_analysis.assets.knowledge import LINKS_LOAD
    from flow_analysis.taxonomy import RELATION_TYPES

    for relation, rel_type in RELATION_TYPES.items():
        if relation == "on_day":
            continue
        assert f"'{rel_type}'" in LINKS_LOAD, rel_type


def test_free_text_observations_survive_beside_fields():
    parsed = validate_entity(
        _entity(
            observations=[
                "day: 2026-08-18",
                "cadence: weekly",
                "window: 7",
                "A sentence of context, with a colon: kept whole, not parsed.",
            ]
        )
    )
    assert len(parsed["observations"]) == 4
    fields = parse_fields(parsed["observations"])
    assert "a_sentence_of_context,_with_a_colon" not in fields


# --- the snapshot pipeline -----------------------------------------------------


@pytest.fixture
def memory_file(tmp_path, monkeypatch):
    path = tmp_path / "memory.jsonl"
    monkeypatch.setattr(raw_assets, "MEMORY_FILE", path)
    return path


def _write_memory(path, items) -> None:
    path.write_text("\n".join(json.dumps(item) for item in items) + "\n")


def test_snapshot_ids_are_stable_and_dedupe(memory_file, tmp_path):
    """Re-snapshotting an unchanged memory must add nothing to the archive."""
    _write_memory(memory_file, [_entity()])
    with store.redirect(tmp_path / "data"):
        first = raw_assets.raw_agent_memory(context=build_asset_context())
        again = raw_assets.raw_agent_memory(context=build_asset_context())
        assert [r["id"] for r in first.rows] == [r["id"] for r in again.rows]

        added = store.append_notes(first.rows, store.known_note_ids())
        added_again = store.append_notes(again.rows, store.known_note_ids())
    assert added == 1
    assert added_again == 0


def test_an_edited_entity_lands_as_a_new_row(memory_file, tmp_path):
    """The archive keeps every state an entity has passed through."""
    _write_memory(memory_file, [_entity()])
    with store.redirect(tmp_path / "data"):
        store.append_notes(
            raw_assets.raw_agent_memory(context=build_asset_context()).rows,
            store.known_note_ids(),
        )
        _write_memory(
            memory_file,
            [
                _entity(
                    observations=[
                        "day: 2026-08-18",
                        "cadence: weekly",
                        "window: 7",
                        "Amended after reflection.",
                    ]
                )
            ],
        )
        store.append_notes(
            raw_assets.raw_agent_memory(context=build_asset_context()).rows,
            store.known_note_ids(),
        )
        assert len(store.load_notes()) == 2


def test_an_invalid_entity_blocks_the_snapshot_loudly(memory_file):
    """Nothing lands until the working set is fixed — permanence demands it."""
    _write_memory(memory_file, [_entity(entityType="Musing")])
    with pytest.raises(TaxonomyError):
        raw_assets.raw_agent_memory(context=build_asset_context())


def test_latest_state_wins_in_the_graph_frame(memory_file, tmp_path):
    """stg_knowledge places the current state; history stays in the archive."""
    import polars as pl

    from flow_analysis.assets.knowledge import stg_knowledge

    memory_rows = [
        {
            "id": "note:aaa",
            "captured_at": "t1",
            "note_kind": "entity",
            "name": "review:2026-08-18:weekly",
            "entity_type": "Review",
            "labels": ["Meta", "Review"],
            "observations": ["day: 2026-08-18"],
            "day": "2026-08-18",
            "cadence": "weekly",
            "window": "7",
        },
        {
            "id": "note:bbb",
            "captured_at": "t2",
            "note_kind": "entity",
            "name": "review:2026-08-18:weekly",
            "entity_type": "Review",
            "labels": ["Meta", "Review"],
            "observations": ["day: 2026-08-18"],
            "day": "2026-08-18",
            "cadence": "weekly",
            "window": "9",
        },
    ]
    frame = stg_knowledge(
        context=build_asset_context(),
        raw_agent_memory=memory_rows,
        dim_day=pl.DataFrame(),
        fct_measures=pl.DataFrame(),
    )
    assert frame.height == 1
    assert frame["props"][0]["window"] == "9"
