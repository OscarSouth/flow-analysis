"""The Neo4j IO manager's contract, without a database.

The driver is stubbed: what is under test is which Cypher runs, in what order,
and what happens when an asset forgets to declare any — not whether Neo4j works.
The real thing is exercised by `tests/test_rebuildable.py` under `-m integration`.
"""

from __future__ import annotations

import contextlib
from typing import Any

import polars as pl
import pytest
from dagster import build_input_context, build_output_context

from flow_analysis.io.neo4j_io_manager import BATCH_SIZE, Neo4jIOManager
from flow_analysis.resources.graph import Neo4jResource


class _Session:
    def __init__(
        self, ran: list[tuple[str, Any]], records: list[dict[str, Any]]
    ) -> None:
        self._ran = ran
        self._records = records

    def run(self, query: str, **params: Any) -> list[dict[str, Any]]:  # noqa: ANN401
        self._ran.append((query.strip(), params.get("rows")))
        return self._records

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _Driver:
    def __init__(
        self, ran: list[tuple[str, Any]], records: list[dict[str, Any]]
    ) -> None:
        self._ran = ran
        self._records = records

    def session(self, **kwargs: Any) -> _Session:  # noqa: ANN401 - as above
        return _Session(self._ran, self._records)


class _Recorder:
    """Captures what the manager ran, in order."""

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self.ran: list[tuple[str, Any]] = []
        self.records = records or []


def _manager(
    monkeypatch: pytest.MonkeyPatch, records: list[dict[str, Any]] | None = None
) -> tuple[Neo4jIOManager, _Recorder]:
    """A real manager and a real resource, with only the driver stubbed.

    Patching `driver` rather than substituting the resource keeps pydantic's own
    validation in the loop — a duck-typed stand-in is rejected, which is the
    framework telling the truth about how it will be wired in production.
    """
    recorder = _Recorder(records)

    @contextlib.contextmanager
    def fake_driver(self: Neo4jResource):  # noqa: ANN202 - mirrors the real signature
        yield _Driver(recorder.ran, recorder.records)

    monkeypatch.setattr(Neo4jResource, "driver", fake_driver)
    return Neo4jIOManager(neo4j=Neo4jResource()), recorder


def test_the_declared_cypher_runs_with_the_frame_as_rows(monkeypatch):
    manager, stub = _manager(monkeypatch)
    context = build_output_context(
        definition_metadata={"cypher_template": "MERGE (x)", "load_cypher": "MATCH (x)"}
    )

    manager.handle_output(context, pl.DataFrame({"a": [1, 2]}))

    assert [query for query, _ in stub.ran] == ["MERGE (x)"]
    assert stub.ran[0][1] == [{"a": 1}, {"a": 2}]


def test_post_cypher_runs_after_the_rows_and_without_them(monkeypatch):
    """The NEXT chain needs every day to exist first, so it is a second pass."""
    manager, stub = _manager(monkeypatch)
    context = build_output_context(
        definition_metadata={
            "cypher_template": "MERGE (d:Day)",
            "post_cypher": "MATCH (a),(b) MERGE (a)-[:NEXT]->(b)",
            "load_cypher": "MATCH (d)",
        }
    )

    manager.handle_output(context, pl.DataFrame({"date": ["2026-08-16"]}))

    assert [query for query, _ in stub.ran] == [
        "MERGE (d:Day)",
        "MATCH (a),(b) MERGE (a)-[:NEXT]->(b)",
    ]
    assert stub.ran[1][1] is None


def test_rows_are_written_in_batches(monkeypatch):
    """Neo4j's transaction memory is finite; a single huge UNWIND is not free."""
    manager, stub = _manager(monkeypatch)
    context = build_output_context(
        definition_metadata={"cypher_template": "MERGE (x)", "load_cypher": "MATCH (x)"}
    )

    manager.handle_output(context, pl.DataFrame({"a": list(range(BATCH_SIZE + 1))}))

    assert len(stub.ran) == 2
    assert len(stub.ran[0][1]) == BATCH_SIZE
    assert len(stub.ran[1][1]) == 1


def test_an_empty_frame_writes_nothing_but_still_succeeds(monkeypatch):
    """A measure with nothing to say yet is a normal state, not a failure."""
    manager, stub = _manager(monkeypatch)
    context = build_output_context(
        definition_metadata={"cypher_template": "MERGE (x)", "load_cypher": "MATCH (x)"}
    )

    manager.handle_output(context, pl.DataFrame())

    assert stub.ran == []
    assert dict(context.get_logged_metadata())["rows_written"].value == 0


def test_an_asset_that_declares_no_write_fails_loudly(monkeypatch):
    """Otherwise it would materialise green and leave the graph empty."""
    manager, _ = _manager(monkeypatch)
    with pytest.raises(ValueError, match="cypher_template"):
        manager.handle_output(
            build_output_context(definition_metadata={}), pl.DataFrame()
        )


def test_reading_back_uses_the_upstream_assets_load_cypher(monkeypatch):
    manager, stub = _manager(
        monkeypatch, records=[{"date": "2026-08-16"}, {"date": "2026-08-17"}]
    )
    context = build_input_context(
        upstream_output=build_output_context(
            definition_metadata={
                "cypher_template": "MERGE (d)",
                "load_cypher": "MATCH (d:Dim:Day) RETURN d.date AS date",
            }
        )
    )

    frame = manager.load_input(context)

    assert stub.ran[0][0] == "MATCH (d:Dim:Day) RETURN d.date AS date"
    assert frame["date"].to_list() == ["2026-08-16", "2026-08-17"]
