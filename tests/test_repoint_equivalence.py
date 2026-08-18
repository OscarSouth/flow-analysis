"""The archive path and the graph path must say exactly the same thing.

The graph is the sole analysis source by decision (2026-08-18) precisely
because two paths over the same data eventually disagree. The fold-from-archive
code still exists (the fixture path uses it), so this test holds both up to the
light on identical data — every surface, canonical JSON, no tolerance.

Integration-marked: needs Neo4j populated by `flow sync`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from flow_analysis import evidence as ev
from flow_analysis import report as report_mod
from flow_analysis import store
from flow_analysis.config import load_config
from flow_analysis.graph import loaders
from flow_analysis.metrics import diagnostics as dx
from flow_analysis.metrics import embodiment, reception
from flow_analysis.metrics.grid import fold_rows, to_dicts
from flow_analysis.metrics.production import production_by_day

pytestmark = pytest.mark.integration


def _canon(value: Any) -> str:  # noqa: ANN401 - canonicalises any summary shape
    return json.dumps(value, default=str, sort_keys=True)


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def archive_rows(cfg):
    return fold_rows(cfg, store.load_cards_latest(), store.load_actions())


@pytest.fixture(scope="module")
def graph_rows():
    return loaders.flow_rows()


def test_grid_is_identical(archive_rows, graph_rows):
    key = lambda r: (r["day"], r["activity"])  # noqa: E731
    assert sorted(to_dicts(archive_rows), key=key) == sorted(
        to_dicts(graph_rows), key=key
    )


def test_production_buckets_are_identical(cfg):
    assert production_by_day(cfg, store.load_signals()) == loaders.production_by_day()


def test_signal_payloads_are_identical_including_types(cfg):
    """116 stars must stay an int — Float64 coercion once rendered it 116.0."""
    old = {r["id"]: r for r in store.load_signals()}
    new = {r["id"]: r for r in loaders.signal_dicts()}
    assert set(old) == set(new)
    sample = next(r for r in new.values() if r.get("metric") == "stars")
    assert isinstance(sample["value"], int)


def test_report_summary_is_identical(cfg, archive_rows, graph_rows):
    assert _canon(report_mod.summarise(cfg, archive_rows)) == _canon(
        report_mod.summarise(cfg, graph_rows)
    )


def test_diagnostics_are_identical(cfg, archive_rows, graph_rows):
    assert _canon(
        dx.run_all(cfg, archive_rows, production_by_day(cfg, store.load_signals()))
    ) == _canon(dx.run_all(cfg, graph_rows, loaders.production_by_day()))


def test_reception_and_embodiment_are_identical(cfg):
    assert _canon(reception.summarise(cfg, store.load_signals())) == _canon(
        reception.summarise(cfg, loaders.signal_dicts())
    )
    assert _canon(embodiment.summarise(cfg, store.load_signals())) == _canon(
        embodiment.summarise(cfg, loaders.signal_dicts())
    )


def test_evidence_pack_is_identical(cfg, archive_rows, graph_rows):
    assert _canon(
        ev.build(
            cfg,
            archive_rows,
            production_by_day(cfg, store.load_signals()),
            store.load_signals(),
        )
    ) == _canon(
        ev.build(cfg, graph_rows, loaders.production_by_day(), loaders.signal_dicts())
    )
