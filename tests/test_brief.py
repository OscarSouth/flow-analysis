"""The brief's depth table — same state, same depth, every time.

Pure Layer B: everything is table-driven over constructed inputs, so these run
offline and pin the determinism the steering depends on.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from flow_analysis.metrics import brief


def _inputs(**overrides: object) -> brief.BriefInputs:
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    base: dict = {
        "today": date(2026, 8, 18),
        "epoch": date(2026, 8, 16),
        "materialised_at": {
            asset: now - timedelta(hours=1) for asset in brief.STALE_AFTER_HOURS
        },
        "last_reviews": {},
        "days": [],
        "measures": [],
        "gates_recorded": set(),
        "knowledge": [],
        "outcomes_recorded": set(),
        "now": now,
    }
    base.update(overrides)
    return brief.BriefInputs(**base)


def test_a_quiet_state_is_a_glance():
    result = brief.build(_inputs())
    assert result["depth"] == "glance"
    assert result["because"] == ["nothing due, nothing newly answerable"]


def test_one_newly_answerable_measure_is_a_review():
    result = brief.build(
        _inputs(measures=[{"name": "charge", "ok": True, "n": 28, "needs": 28}])
    )
    assert result["depth"] == "review"
    assert result["newly_answerable"] == [{"measure": "charge", "n": 28, "needs": 28}]


def test_two_newly_answerable_measures_are_deep():
    result = brief.build(
        _inputs(
            measures=[
                {"name": "charge", "ok": True, "n": 28, "needs": 28},
                {"name": "coupling", "ok": True, "n": 60, "needs": 60},
            ]
        )
    )
    assert result["depth"] == "deep"


def test_a_recorded_gate_stops_reannouncing():
    """GateOpened is the acknowledgement; after it, the event is history."""
    result = brief.build(
        _inputs(
            measures=[{"name": "charge", "ok": True, "n": 30, "needs": 28}],
            gates_recorded={"charge"},
        )
    )
    assert result["newly_answerable"] == []
    assert result["depth"] == "glance"


def test_an_overdue_monthly_review_is_deep():
    result = brief.build(_inputs(last_reviews={"monthly": date(2026, 7, 1)}))
    assert result["depth"] == "deep"
    assert any("monthly review due" in reason for reason in result["because"])


def test_a_due_weekly_review_is_a_review():
    result = brief.build(_inputs(last_reviews={"weekly": date(2026, 8, 10)}))
    assert result["depth"] == "review"


def test_reviews_never_run_anchor_on_the_epoch():
    """With no reviews ever, everything becomes due one period after the epoch."""
    result = brief.build(_inputs(today=date(2026, 11, 20)))
    cadences = {r["cadence"] for r in result["reviews_due"]}
    assert cadences == {"weekly", "monthly", "quarterly"}
    assert all(r["never_run"] for r in result["reviews_due"])


def test_a_week_of_unexamined_days_is_a_review():
    days = [
        {"day": f"2026-08-{d:02d}", "completed": 1, "observed": 5, "production": 0}
        for d in range(10, 18)
    ]
    result = brief.build(_inputs(days=days))
    assert result["depth"] == "review"
    assert result["changed"]["new_days"] == 8


def test_staleness_names_the_source_and_never_seen_is_stalest():
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    result = brief.build(
        _inputs(
            materialised_at={
                "raw_github_signals": now - timedelta(hours=30),
                "raw_trello_actions": now - timedelta(hours=1),
                "raw_trello_cards": now - timedelta(hours=1),
                "raw_youtube_signals": now - timedelta(hours=1),
            }
        )
    )
    stale = result["stale"]
    assert stale[0]["asset"] == "raw_forum_posts"  # never materialised
    assert stale[0]["hours"] is None
    assert any(s["asset"] == "raw_github_signals" for s in stale)


def test_open_loops_track_prescriptions_transformations_and_proposals():
    knowledge = [
        {"name": "prescription:2026-08-17:a", "entity_type": "Prescription"},
        {"name": "prescription:2026-08-10:b", "entity_type": "Prescription"},
        {
            "name": "transformation:2026-08-18:x",
            "entity_type": "Transformation",
            "confirmed": "no",
        },
        {
            "name": "devproposal:2026-08-18:y",
            "entity_type": "DevProposal",
            "status": "registered",
        },
        {
            "name": "devproposal:2026-08-01:z",
            "entity_type": "DevProposal",
            "status": "done",
        },
        # The socratic layer is not a loop: a held belief awaits revision
        # forever by design, so it must never appear as unfinished business.
        {
            "name": "belief:2026-08-18:w",
            "entity_type": "Belief",
            "status": "held",
        },
        {
            "name": "reference:2026-08-18:v",
            "entity_type": "Reference",
        },
    ]
    result = brief.build(
        _inputs(knowledge=knowledge, outcomes_recorded={"prescription:2026-08-10:b"})
    )
    loops = result["open_loops"]
    assert loops["prescriptions_without_outcome"] == ["prescription:2026-08-17:a"]
    assert loops["unconfirmed_transformations"] == ["transformation:2026-08-18:x"]
    assert loops["registered_dev_proposals"] == ["devproposal:2026-08-18:y"]


# --- health: the platform noticing its own faults --------------------------------


def test_a_failed_sync_asset_is_a_health_item_and_forces_review():
    result = brief.build(_inputs(last_sync_failed=["raw_github_signals"]))
    assert result["depth"] == "review"
    assert any("health: last sync failed" in reason for reason in result["because"])


def test_archive_graph_drift_is_named_with_both_counts():
    result = brief.build(_inputs(archive_signals=5178, graph_signals=5170))
    assert result["depth"] == "review"
    assert any("5178" in item and "5170" in item for item in result["health"])


def test_matching_counts_are_silent():
    result = brief.build(_inputs(archive_signals=5178, graph_signals=5178))
    assert result["health"] == []
    assert result["depth"] == "glance"


def test_a_few_untrusted_posteriors_are_reported_but_not_a_fault():
    """A young practice legitimately produces fits the sampler distrusts."""
    result = brief.build(_inputs(untrusted_today=["latency_median:Train"]))
    assert result["untrusted_today"] == ["latency_median:Train"]
    assert result["health"] == []
    assert result["depth"] == "glance"


def test_many_untrusted_posteriors_become_a_health_item():
    untrusted = [f"m{i}" for i in range(11)]
    result = brief.build(_inputs(untrusted_today=untrusted))
    assert result["depth"] == "review"
    assert any("untrusted posterior" in item for item in result["health"])
