"""The archive behind Dagster — dispatch, dedupe, and write ordering.

No network and no real `data/`: every test redirects the store into tmp_path.
"""

from __future__ import annotations

import json

import pytest
from dagster import OutputContext, build_input_context, build_output_context

from flow_analysis import store
from flow_analysis.io import JsonlIOManager, RawStream


@pytest.fixture
def archive(tmp_path):
    with store.redirect(tmp_path):
        yield tmp_path


def _output(stream: str) -> OutputContext:
    return build_output_context(definition_metadata={"jsonl_stream": stream})


def test_rows_land_in_the_stream_the_asset_declared(archive):
    JsonlIOManager().handle_output(
        _output("signals"),
        RawStream(rows=[{"id": "forum:post:1", "created_at": "2026-08-17T09:00:00Z"}]),
    )

    written = (archive / "signals.jsonl").read_text().splitlines()
    assert len(written) == 1
    assert json.loads(written[0])["id"] == "forum:post:1"
    assert not (archive / "actions.jsonl").exists()


def test_appending_the_same_rows_twice_adds_nothing(archive):
    rows = [{"id": "a", "date": "2026-08-17T09:00:00Z"}]
    manager = JsonlIOManager()

    manager.handle_output(_output("actions"), RawStream(rows=rows))
    manager.handle_output(_output("actions"), RawStream(rows=rows))

    assert len((archive / "actions.jsonl").read_text().splitlines()) == 1


def test_the_watermark_is_saved_only_after_the_rows(archive, monkeypatch):
    """Reversing this would let a failed write claim coverage that is not there.

    `sync.integrity()` reads the watermark, so state running ahead of the archive
    reports a gap as OK — the one failure mode this whole check exists to catch.
    """
    order: list[str] = []
    real_append = store.append_actions
    real_save = store.save_state

    def spy_append(rows, known) -> int:
        order.append("rows")
        return real_append(rows, known)

    def spy_save(state) -> None:
        order.append("state")
        return real_save(state)

    monkeypatch.setattr(store, "append_actions", spy_append)
    monkeypatch.setattr(store, "save_state", spy_save)

    JsonlIOManager().handle_output(
        _output("actions"),
        RawStream(rows=[{"id": "a", "date": "x"}], state={"newest_action_id": "a"}),
    )

    assert order == ["rows", "state"]
    assert store.load_state()["newest_action_id"] == "a"


def test_no_watermark_means_no_state_write(archive):
    """Only the action walk has a watermark; the others must not touch state."""
    JsonlIOManager().handle_output(_output("cards"), RawStream(rows=[{"id": "c"}]))
    assert store.load_state() == {}


def test_an_unknown_stream_fails_loudly(archive):
    """A typo must not default to a file — that would cross two streams' rows."""
    with pytest.raises(ValueError, match="jsonl_stream"):
        JsonlIOManager().handle_output(
            _output("signalz"), RawStream(rows=[{"id": "x"}])
        )


def test_a_missing_stream_declaration_fails_loudly(archive):
    context = build_output_context(definition_metadata={})
    with pytest.raises(ValueError, match="jsonl_stream"):
        JsonlIOManager().handle_output(context, RawStream(rows=[{"id": "x"}]))


def test_reading_back_returns_the_whole_stream(archive):
    """Downstream layers model history, not just what this run happened to add."""
    manager = JsonlIOManager()
    manager.handle_output(_output("signals"), RawStream(rows=[{"id": "one"}]))
    manager.handle_output(_output("signals"), RawStream(rows=[{"id": "two"}]))

    context = build_input_context(
        upstream_output=build_output_context(
            definition_metadata={"jsonl_stream": "signals"}
        )
    )
    assert [row["id"] for row in manager.load_input(context)] == ["one", "two"]


def test_output_metadata_reports_what_landed(archive):
    """The CLI reads these counts back rather than counting for itself."""
    context = _output("signals")
    JsonlIOManager().handle_output(
        context, RawStream(rows=[{"id": "one"}, {"id": "two"}, {"id": "one"}])
    )

    recorded = dict(context.get_logged_metadata())
    assert recorded["rows_fetched"].value == 3
    assert recorded["rows_appended"].value == 2
