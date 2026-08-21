"""The durability contract: archive as truth, working set as fast store.

Pinned here after the 2026-08-19 audit: the graph derives from the archive,
so the archive must capture every state (including reverts), fold
deterministically, restore the working set losslessly, and carry posterior
snapshots so a purge cannot destroy history.
"""

from __future__ import annotations

import json

import pytest
from dagster import build_asset_context

from flow_analysis import store
from flow_analysis.assets import raw as raw_assets


@pytest.fixture
def memory_file(tmp_path, monkeypatch):
    path = tmp_path / "memory.jsonl"
    monkeypatch.setattr(raw_assets, "MEMORY_FILE", path)
    return path


def _entity(window: str) -> dict[str, object]:
    return {
        "type": "entity",
        "name": "review:2026-08-18:weekly",
        "entityType": "Review",
        "observations": ["day: 2026-08-18", "cadence: weekly", f"window: {window}"],
    }


def _write_memory(path, items) -> None:
    path.write_text("\n".join(json.dumps(item) for item in items) + "\n")


def _snapshot(memory_file) -> int:
    rows = raw_assets.raw_agent_memory(context=build_asset_context()).rows
    return store.append_notes(rows, store.note_state())


# --- edit-then-revert ---------------------------------------------------------


def test_a_revert_lands_as_a_new_row_and_wins(memory_file, tmp_path):
    """A→B→A must leave the graph holding A, not B.

    Regression: content-hash dedupe against all-history ids skipped the
    reverted state, so the archive's last word stayed B forever.
    """
    with store.redirect(tmp_path / "data"):
        _write_memory(memory_file, [_entity("7")])
        assert _snapshot(memory_file) == 1
        _write_memory(memory_file, [_entity("9")])
        assert _snapshot(memory_file) == 1
        _write_memory(memory_file, [_entity("7")])  # the revert
        assert _snapshot(memory_file) == 1, "the revert must land"

        latest = store.latest_notes(store.load_notes())
        assert latest["review:2026-08-18:weekly"]["window"] == "7"
        # And an unchanged re-snapshot still adds nothing.
        assert _snapshot(memory_file) == 0


# --- deterministic fold ---------------------------------------------------------


def test_latest_notes_orders_by_captured_at_not_file_order():
    rows = [
        {
            "note_kind": "entity",
            "name": "x",
            "captured_at": "2026-08-19T10:00:00+00:00",
            "state": "late",
        },
        {
            "note_kind": "entity",
            "name": "x",
            "captured_at": "2026-08-18T10:00:00+00:00",
            "state": "early",
        },
    ]
    assert store.latest_notes(rows)["x"]["state"] == "late"


# --- restore -------------------------------------------------------------------


def test_restore_round_trip_is_lossless(memory_file, tmp_path):
    """Snapshot → lose the file → restore → re-snapshot appends nothing."""
    with store.redirect(tmp_path / "data"):
        _write_memory(memory_file, [_entity("7")])
        _snapshot(memory_file)
        memory_file.unlink()

        entities, relations = raw_assets.restore_working_set()
        assert (entities, relations) == (1, 0)
        assert memory_file.exists()
        assert _snapshot(memory_file) == 0, "restore must be lossless"


def test_restore_refuses_a_non_empty_working_set(memory_file, tmp_path):
    with store.redirect(tmp_path / "data"):
        _write_memory(memory_file, [_entity("7")])
        _snapshot(memory_file)
        with pytest.raises(RuntimeError, match="--force"):
            raw_assets.restore_working_set()
        # forced, it proceeds
        entities, _ = raw_assets.restore_working_set(force=True)
        assert entities == 1


def test_working_set_names_tolerate_missing_and_corrupt_files(memory_file):
    assert raw_assets.working_set_entity_names() == set()
    memory_file.write_text('not json\n{"type": "entity", "name": "a"}\n')
    assert raw_assets.working_set_entity_names() == {"a"}


def test_mcp_config_and_snapshot_agree_on_the_memory_path():
    """The MCP server and the snapshot asset are coupled by convention only."""
    from pathlib import Path

    mcp = json.loads((Path(__file__).resolve().parents[1] / ".mcp.json").read_text())
    configured = mcp["mcpServers"]["memory"]["env"]["MEMORY_FILE_PATH"]
    # Compare the real asset constant, not the monkeypatched fixture.
    import importlib

    actual = importlib.import_module("flow_analysis.assets.raw").MEMORY_FILE
    assert str(actual) == configured


# --- posterior archive ----------------------------------------------------------


def _posterior_row(measure: str, day: str, mean: float) -> dict[str, object]:
    return {
        "measure": measure,
        "day": day,
        "model": "poisson_rate",
        "mean": mean,
        "median": mean,
        "ci_low": mean - 0.1,
        "ci_high": mean + 0.1,
        "probability": 0.5,
        "verdict": "not testable yet",
        "rhat_max": 1.0,
        "ess_min": 1000.0,
        "divergences": 0,
        "trusted": True,
        "extra_json": None,
    }


def test_posterior_states_dedupe_and_accumulate(tmp_path):
    with store.redirect(tmp_path / "data"):
        row = _posterior_row("contract:c9_publication_rate", "2026-08-19", 0.5)
        stamped = {"id": store.posterior_id(row), "captured_at": "t1", **row}
        assert store.append_posteriors([stamped], store.known_posterior_ids()) == 1
        # identical state again — nothing lands
        again = {"id": store.posterior_id(row), "captured_at": "t2", **row}
        assert store.append_posteriors([again], store.known_posterior_ids()) == 0
        # a same-day re-fit on new data is a new state
        refit = _posterior_row("contract:c9_publication_rate", "2026-08-19", 0.7)
        refit = {"id": store.posterior_id(refit), "captured_at": "t3", **refit}
        assert store.append_posteriors([refit], store.known_posterior_ids()) == 1

        latest = store.latest_posteriors(store.load_posteriors())
        assert len(latest) == 1
        assert latest[0]["mean"] == 0.7


def test_latest_posteriors_keeps_one_state_per_measure_day():
    rows = [
        _posterior_row("m", "2026-08-18", 0.1),
        _posterior_row("m", "2026-08-19", 0.2),
        _posterior_row("m", "2026-08-19", 0.3),  # later state wins
    ]
    latest = store.latest_posteriors(rows)
    by_day = {r["day"]: r["mean"] for r in latest}
    assert by_day == {"2026-08-18": 0.1, "2026-08-19": 0.3}


def test_posteriors_stream_is_registered():
    from flow_analysis.io.streams import STREAMS

    assert "posteriors" in STREAMS
    assert STREAMS["posteriors"].path() == store.POSTERIORS_PATH


def test_snapshot_asset_declares_the_posteriors_stream():
    from flow_analysis.assets.posteriors import raw_posterior_snapshots

    for _key, metadata in raw_posterior_snapshots.metadata_by_key.items():
        assert metadata.get("jsonl_stream") == "posteriors"
