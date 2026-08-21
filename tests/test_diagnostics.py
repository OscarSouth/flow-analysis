"""Diagnostics, and — more importantly — their refusal to speak on thin data.

The gating is the point. A measure that produces a confident number from nine
days is the failure mode this whole layer exists to avoid.
"""

from __future__ import annotations

import collections
from typing import TYPE_CHECKING

import pytest

from flow_analysis import fixtures, store
from flow_analysis.metrics import diagnostics as dx
from flow_analysis.metrics import grid
from flow_analysis.metrics.calendar import flow_day
from flow_analysis.util import parse_iso

if TYPE_CHECKING:
    from flow_analysis.config import Config
    from flow_analysis.metrics.grid import FlowRow


def _seed(
    tmp_path, monkeypatch, days: int
) -> tuple[Config, list[FlowRow], dict[str, int]]:
    monkeypatch.setattr(store, "ACTIONS_PATH", tmp_path / "actions.jsonl")
    monkeypatch.setattr(store, "CARDS_PATH", tmp_path / "cards.jsonl")
    monkeypatch.setattr(store, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)

    fx = fixtures.synthesize(days=days, end=fixtures.REFERENCE_END)
    store.append_actions(fx.actions, set())
    store.append_cards(fx.cards, set())
    cfg = fixtures.fixture_config(fx.days[0])
    rows = grid.fold_rows(cfg, store.load_cards_latest(), store.load_actions())

    production: collections.Counter = collections.Counter()
    for post in fx.forum:
        day = flow_day(parse_iso(post["created_at"]), cfg.timezone, cfg.drain_at)
        production[day.isoformat()] += 1
    return cfg, rows, dict(production)


@pytest.fixture
def full(tmp_path, monkeypatch):
    return _seed(tmp_path, monkeypatch, 120)


@pytest.fixture
def thin(tmp_path, monkeypatch):
    return _seed(tmp_path, monkeypatch, 9)


# --- gating -----------------------------------------------------------------


def test_thin_data_refuses_rather_than_guesses(thin):
    cfg, rows, production = thin
    result = dx.run_all(cfg, rows, production)

    for name in ("charge", "coupling", "allocation_vs_capacity"):
        measure = result["measures"][name]
        assert not measure.ok, f"{name} produced a value on 9 days"
        assert measure.needs > measure.n
        assert "insufficient data" in str(measure)

    assert set(result["underpowered"]) >= {"charge", "coupling"}


def test_full_data_answers(full):
    cfg, rows, production = full
    result = dx.run_all(cfg, rows, production)
    assert result["days"] == 120
    assert result["underpowered"] == []


# --- the extensions ---------------------------------------------------------


def test_allocation_and_capacity_are_distinguished(full):
    """The split is only useful if different modes fail differently."""
    cfg, rows, _ = full
    value = dx.allocation_vs_capacity(rows, cfg.activities).value
    dominant = {a: v["dominant"] for a, v in value.items()}
    assert dominant["Train"] == "allocation"
    assert dominant["Express"] == "capacity"


def test_dormancy_finds_the_closed_channel(full):
    cfg, rows, _ = full
    value = dx.dormancy(rows, cfg.activities).value
    # The fixture closes Absorb for 17 consecutive days.
    assert value["Absorb"]["longest"] >= dx.DORMANCY_FLAG
    assert value["Absorb"]["longest"] > value["Write"]["longest"]


def test_charge_is_informative_not_pinned_at_zero(full):
    """Set membership over a fortnight reads 0 forever; normalised spread does not."""
    cfg, rows, _ = full
    measure = dx.charge(rows, cfg.activities)
    series = [point["charge"] for point in measure.detail["series"]]
    assert 0.0 < max(series) <= 1.0
    assert len(set(series)) > 1


def test_aberration_fires_on_output_without_its_channel(full):
    _cfg, rows, production = full
    value = dx.aberration(rows, production).value
    assert value["channel"] == "Reveal"
    assert value["days"] > 0
    assert 0.0 < value["share_of_producing_days"] <= 1.0


def test_aberration_is_empty_without_production(full):
    _cfg, rows, _ = full
    assert dx.aberration(rows, {}).value["days"] == 0


def test_adherence_without_production_flags_only_when_output_is_flat(full):
    _cfg, rows, production = full
    assert dx.adherence_without_production(rows, production).value["flagged"] is False


# --- coupling ---------------------------------------------------------------


def test_coupling_only_pairs_days_inside_the_observed_range(full):
    """Otherwise the tail compares real adherence against assumed zeros."""
    _cfg, rows, production = full
    by_lag = dx.coupling(rows, production).detail["by_lag"]
    counts = [entry["n"] for entry in by_lag]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] > counts[-1]


def test_coupling_declares_itself_confounded(full):
    _cfg, rows, production = full
    assert dx.coupling(rows, production).detail["confounded"] is True


def test_correlating_unequal_series_raises_rather_than_truncating():
    """`coupling` appends to both series in lockstep, so they cannot diverge.

    Pinning it anyway: a silent `zip` would correlate the overlap and report an
    r computed from a pairing nobody chose, which is worse than no number.
    """
    with pytest.raises(ValueError, match="shorter"):
        dx._pearson([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0])


def test_a_flat_series_has_no_correlation_to_report():
    """Zero variance is not r=0, it is no answer — the denominator vanishes."""
    assert dx._pearson([2.0, 2.0, 2.0, 2.0], [1.0, 5.0, 3.0, 9.0]) is None


def test_fewer_than_three_pairs_is_not_a_correlation():
    assert dx._pearson([1.0, 2.0], [3.0, 4.0]) is None


# --- the contracts ------------------------------------------------------------


def test_run_all_carries_every_contract(full):
    """Every registry entry surfaces as a measure.

    Deterministic verdicts inline; posterior contracts as gate-state rows
    pointing at the graph.
    """
    from flow_analysis.metrics.contracts import REGISTRY

    cfg, rows, production = full
    measures = dx.run_all(cfg, rows, production)["measures"]
    for contract in REGISTRY:
        assert contract.key in measures, contract.key
        measure = measures[contract.key]
        if contract.kind == "posterior" and measure.ok:
            assert measure.value["see"] == contract.measure


def test_deterministic_contracts_speak_the_four_way_vocabulary(full):
    cfg, rows, production = full
    measures = dx.run_all(cfg, rows, production)["measures"]
    for key in (
        "c6_dormancy_escalation",
        "c7_harmonious_stagnation",
        "c8_productive_aberration",
    ):
        measure = measures[key]
        if measure.ok:
            assert measure.value["verdict"] in {"supported", "not supported"}


def test_dormancy_escalation_contract_fires_on_a_21_day_closure():
    """c6 is deterministic: a three-week closed channel is a fact."""
    from datetime import date, timedelta

    from flow_analysis.metrics.grid import FlowRow

    start = date(2026, 1, 1)
    rows = []
    for i in range(25):
        day = (start + timedelta(days=i)).isoformat()
        rows.append(FlowRow(day=day, activity="Train", outcome="never_started"))
        rows.append(FlowRow(day=day, activity="Write", outcome="completed"))
    measure = dx.contract_dormancy_escalation(rows, ["Write", "Train"])
    assert measure.ok
    assert measure.value["verdict"] == "supported"
    assert measure.value["escalated"] == ["Train"]


def test_posterior_contract_gates_refuse_on_thin_data(thin):
    cfg, rows, production = thin
    measures = dx.run_all(cfg, rows, production)["measures"]
    gate = measures["c1_allocation_failure"]
    assert not gate.ok
    assert gate.needs > gate.n


# --- pull order -------------------------------------------------------------


def test_pull_rank_is_assigned_in_start_order(full):
    _, rows, _ = full
    by_day: dict[str, list] = {}
    for row in rows:
        if row.pull_rank:
            by_day.setdefault(row.day, []).append(row)
    day = next(rs for rs in by_day.values() if len(rs) >= 3)
    day.sort(key=lambda r: r.pull_rank)
    assert [r.started_at for r in day] == sorted(r.started_at for r in day)
    assert day[0].interleaved == 0


def test_failure_kind_matches_outcome(full):
    _, rows, _ = full
    for row in rows:
        if row.outcome == grid.NEVER_STARTED:
            assert row.failure_kind == "allocation"
        elif row.outcome == grid.ABANDONED:
            assert row.failure_kind == "capacity"
        else:
            assert row.failure_kind is None
