"""Apple Health import and the embodiment surface.

Built against a miniature export rather than the real 750 MB one. The shapes are
taken from the genuine file, including the detail that nearly emptied the series:
strength training is recorded as *Functional*, not *Traditional*.
"""

from __future__ import annotations

import zipfile
from datetime import date
from typing import Any

import pytest

from flow_analysis.fixtures import fixture_config
from flow_analysis.metrics import embodiment
from flow_analysis.sources.health import HealthSource
from flow_analysis.tiers import TIER_EMBODIMENT

EXPORT = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_GB">
  <Workout workoutActivityType="HKWorkoutActivityTypeFunctionalStrengthTraining"
           duration="47.5" sourceName="Oscar's Apple Watch"
           startDate="2026-05-31 18:02:11 +0100" endDate="2026-05-31 18:49:41 +0100"/>
  <Workout workoutActivityType="HKWorkoutActivityTypeTraditionalStrengthTraining"
           duration="30" sourceName="Oscar's Apple Watch"
           startDate="2026-04-02 07:00:00 +0100" endDate="2026-04-02 07:30:00 +0100"/>
  <Workout workoutActivityType="HKWorkoutActivityTypeWalking"
           duration="62" sourceName="Oscar's Apple Watch"
           startDate="2026-04-10 12:00:00 +0100" endDate="2026-04-10 13:02:00 +0100"/>
  <Workout workoutActivityType="HKWorkoutActivityTypeYoga"
           duration="20" sourceName="Oscar's Apple Watch"
           startDate="2026-04-11 12:00:00 +0100" endDate="2026-04-11 12:20:00 +0100"/>
  <Record type="HKQuantityTypeIdentifierBodyMass" unit="kg" value="63.9"
          sourceName="Renpho" startDate="2026-08-12 07:30:00 +0100"/>
  <Record type="HKQuantityTypeIdentifierBodyMass" unit="kg" value="62.4"
          sourceName="Renpho" startDate="2026-08-17 07:30:00 +0100"/>
  <Record type="HKQuantityTypeIdentifierBodyFatPercentage" unit="%" value="0.18"
          sourceName="Renpho" startDate="2026-08-17 07:30:00 +0100"/>
  <Record type="HKQuantityTypeIdentifierStepCount" unit="count" value="8123"
          sourceName="Oscar's iPhone" startDate="2026-08-17 23:00:00 +0100"/>
</HealthData>
"""


@pytest.fixture
def export(tmp_path):
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("apple_health_export/export.xml", EXPORT)
    return path


def test_both_strength_spellings_are_recognised(export):
    """The trap that would have emptied the series.

    The obvious constant is `TraditionalStrengthTraining`, which appears zero
    times in the real export — every one of the 208 sessions is *Functional*. A
    filter on the wrong spelling matches nothing and reports, plausibly and
    wrongly, that no strength training ever happened.
    """
    rows = list(HealthSource(path=export).rows())
    strength = [r for r in rows if r["kind"] == "workout" and r["strength"]]

    assert {r["activity"] for r in strength} == {
        "FunctionalStrengthTraining",
        "TraditionalStrengthTraining",
    }


def test_only_explicit_workouts_and_body_metrics_are_read(export):
    """Step counts are excluded on purpose.

    The watch is worn while exercising or out of the house, so daily totals are
    missing-not-at-random and not comparable across days. A session is not.
    """
    rows = list(HealthSource(path=export).rows())

    kinds = {r["kind"] for r in rows}
    assert kinds == {"workout", "body"}
    assert all(r["tier"] == TIER_EMBODIMENT for r in rows)
    assert not any("Step" in str(r.get("metric")) for r in rows)
    # Yoga is not in the configured set, so it is not counted either.
    assert "Yoga" not in {r.get("activity") for r in rows}


def test_ids_are_stable_so_reimporting_is_free(export):
    """Overlapping exports are the normal case.

    The same session must not land twice, and the file exposes no UUID to key on.
    """
    first = {r["id"] for r in HealthSource(path=export).rows()}
    second = {r["id"] for r in HealthSource(path=export).rows()}
    assert first == second
    assert len(first) == 6  # 3 workouts + 3 body readings


def test_apple_timestamps_become_iso(export):
    rows = list(HealthSource(path=export).rows())
    workout = next(r for r in rows if r["activity"] == "FunctionalStrengthTraining")
    assert workout["created_at"].startswith("2026-05-31T18:02:11")
    assert workout["duration_minutes"] == 47.5


def test_a_directory_resolves_to_its_export_zip(tmp_path):
    folder = tmp_path / "ingest"
    folder.mkdir()
    with zipfile.ZipFile(folder / "export.zip", "w") as z:
        z.writestr("apple_health_export/export.xml", EXPORT)
    assert list(HealthSource(path=folder).rows())


# --- the embodiment surface -------------------------------------------------


def _workout(day, strength=True) -> dict[str, Any]:
    return {
        "id": f"health:workout:{day}",
        "tier": TIER_EMBODIMENT,
        "source": "apple_health",
        "kind": "workout",
        "activity": "FunctionalStrengthTraining" if strength else "Walking",
        "strength": strength,
        "created_at": f"{day}T18:00:00+01:00",
    }


def _mass(day, value) -> dict[str, Any]:
    return {
        "id": f"health:body_mass:{day}",
        "tier": TIER_EMBODIMENT,
        "source": "apple_health",
        "kind": "body",
        "metric": "body_mass",
        "created_at": f"{day}T07:30:00+01:00",
        "value": value,
        "unit": "kg",
    }


def test_silence_from_the_watch_is_a_measurement_gap():
    """The claim this module must never make.

    Oscar trained on the first day of flow and logged the card; he simply wasn't
    wearing the watch. Reading that silence as a gap in training would be an
    accusation the data cannot support.
    """
    rows = [_workout("2026-05-31")]
    coverage = embodiment.workout_coverage(rows, today=date(2026, 8, 17))

    assert coverage["days_since"] == 78
    assert coverage["stale"] is True

    text = embodiment.render(
        {
            "epoch": "2026-08-16",
            "since_epoch": {"workouts": 0, "strength": 0, "body_readings": 3},
            "by_month": embodiment.workouts_by_month(rows),
            "coverage": coverage,
            "mass": None,
            "fat": None,
        }
    )
    assert "gap in measurement" in text
    assert "not evidence of a gap in training" in text


def test_a_recent_workout_is_not_stale():
    rows = [_workout("2026-08-16")]
    assert embodiment.workout_coverage(rows, today=date(2026, 8, 17))["stale"] is False


def test_body_mass_is_smoothed_against_a_prior_window():
    """A single reading against a single earlier one is not a trend.

    At that sample size the change being measured is hydration.
    """
    rows = [_mass(f"2026-07-{day:02d}", 65.0) for day in range(1, 10)]
    rows += [_mass(f"2026-08-{day:02d}", 63.0) for day in range(1, 10)]

    trend = embodiment.body_trend(rows)

    assert trend["latest"] == 63.0
    assert trend["recent_mean"] == 63.0
    assert trend["earlier_mean"] == 65.0
    assert trend["change"] == -2.0
    assert trend["recent_n"] == 9
    assert trend["earlier_n"] == 9


def test_body_trend_refuses_to_compare_without_a_prior_window():
    rows = [_mass("2026-08-17", 62.4)]
    trend = embodiment.body_trend(rows)
    assert trend["change"] is None
    assert trend["earlier_mean"] is None


def test_since_epoch_counts_only_the_flow_era():
    rows = [_workout("2026-05-31"), _workout("2026-08-17"), _mass("2026-08-17", 62.4)]
    era = embodiment.since_epoch(rows, date(2026, 8, 16))
    assert era["workouts"] == 1
    assert era["strength"] == 1
    assert era["body_readings"] == 1


def test_render_is_empty_without_any_embodiment_data():
    cfg = fixture_config(date(2026, 7, 1))
    assert embodiment.render(embodiment.summarise(cfg, [])) == ""


def test_body_mass_is_measured_from_the_epoch_baseline():
    """Mass is a level, not an accumulation.

    So unlike stars or subscribers, the epoch value is not something to discount
    — it is the starting line, and the question is how far it has moved.
    """
    rows = [
        _mass("2026-08-10", 65.0),  # before the epoch
        _mass("2026-08-15", 62.8),  # the last reading at or before it
        _mass("2026-08-17", 62.35),  # since
    ]
    era = embodiment.since_epoch(rows, date(2026, 8, 16))

    assert era["mass_at_epoch"] == 62.8
    assert era["mass_at_epoch_day"] == "2026-08-15"
    assert era["mass_now"] == 62.35
    assert era["mass_change"] == -0.45


def test_no_reading_since_the_epoch_leaves_the_change_unstated():
    rows = [_mass("2026-08-10", 65.0)]
    era = embodiment.since_epoch(rows, date(2026, 8, 16))
    assert era["mass_at_epoch"] == 65.0
    assert era["mass_change"] is None


def test_purge_removes_the_consumed_export(tmp_path):
    """An export is a delivery mechanism, not a store."""
    folder = tmp_path / "ingest"
    folder.mkdir()
    archive = folder / "export.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("apple_health_export/export.xml", EXPORT)

    source = HealthSource(path=folder)
    rows = list(source.rows())
    assert rows  # imported first

    removed = source.purge()

    assert removed
    assert "export.zip" in removed[0]
    assert not archive.exists()
    assert folder.exists()  # the directory stays; only the payload goes


def test_purge_is_silent_when_there_is_nothing_to_remove(tmp_path):
    folder = tmp_path / "ingest"
    folder.mkdir()
    assert HealthSource(path=folder).purge() == []
