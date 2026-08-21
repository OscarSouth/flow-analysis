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
  <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" value="70"
          sourceName="Oscar's Apple Watch"
          startDate="2026-05-31 17:30:00 +0100" endDate="2026-05-31 17:30:00 +0100"/>
  <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" value="80"
          sourceName="Oscar's Apple Watch"
          startDate="2026-05-31 18:05:00 +0100" endDate="2026-05-31 18:05:00 +0100"/>
  <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" value="120"
          sourceName="Oscar's Apple Watch"
          startDate="2026-05-31 18:10:00 +0100" endDate="2026-05-31 18:10:00 +0100"/>
  <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" value="130.4"
          sourceName="Oscar's Apple Watch"
          startDate="2026-05-31 18:20:00 +0100" endDate="2026-05-31 18:20:00 +0100"/>
  <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" value="125"
          sourceName="Oscar's Apple Watch"
          startDate="2026-05-31 18:40:00 +0100" endDate="2026-05-31 18:40:00 +0100"/>
  <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" value="90"
          sourceName="Oscar's Apple Watch"
          startDate="2026-05-31 18:48:00 +0100" endDate="2026-05-31 18:48:00 +0100"/>
  <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" value="65"
          sourceName="Oscar's Apple Watch"
          startDate="2026-05-31 19:30:00 +0100" endDate="2026-05-31 19:30:00 +0100"/>
  <Workout workoutActivityType="HKWorkoutActivityTypeFunctionalStrengthTraining"
           duration="47.5" sourceName="Oscar's Apple Watch"
           startDate="2026-05-31 18:02:11 +0100" endDate="2026-05-31 18:49:41 +0100">
    <MetadataEntry key="HKAverageMETs" value="4.44915 kcal/hr·kg"/>
    <WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned"
                       sum="332.87" unit="kcal"/>
    <WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate"
                       average="110.5" minimum="70" maximum="130" unit="count/min"/>
  </Workout>
  <Workout workoutActivityType="HKWorkoutActivityTypeTraditionalStrengthTraining"
           duration="30" sourceName="Oscar's Apple Watch"
           startDate="2026-04-02 07:00:00 +0100" endDate="2026-04-02 07:30:00 +0100"/>
  <Workout workoutActivityType="HKWorkoutActivityTypeWalking"
           duration="62" sourceName="Oscar's Apple Watch"
           startDate="2026-04-10 12:00:00 +0100" endDate="2026-04-10 13:02:00 +0100">
    <WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate"
                       average="98.2" minimum="72" maximum="121" unit="count/min"/>
  </Workout>
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
    assert kinds == {"workout", "body", "workout_hr"}
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
    assert len(first) == 8  # 3 workouts + 3 body readings + 2 workout_hr


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


def test_a_finder_renamed_export_is_still_found(tmp_path):
    """`export 2.zip` is how a real drop arrived on 2026-08-21.

    A silent miss would report a healthy sync with the dropped data untouched —
    the lapsed-credential failure mode wearing a different hat.
    """
    folder = tmp_path / "ingest"
    folder.mkdir()
    with zipfile.ZipFile(folder / "export 2.zip", "w") as z:
        z.writestr("apple_health_export/export.xml", EXPORT)
    source = HealthSource(path=folder)
    assert source.archive_path.name == "export 2.zip"
    assert list(source.rows())


def test_two_exports_is_ambiguity_and_fails_loudly(tmp_path):
    folder = tmp_path / "ingest"
    folder.mkdir()
    for name in ("export.zip", "export 2.zip"):
        with zipfile.ZipFile(folder / name, "w") as z:
            z.writestr("apple_health_export/export.xml", EXPORT)
    # The canonical name wins outright when present…
    assert HealthSource(path=folder).archive_path.name == "export.zip"
    (folder / "export.zip").unlink()
    with zipfile.ZipFile(folder / "export 3.zip", "w") as z:
        z.writestr("apple_health_export/export.xml", EXPORT)
    # …but two non-canonical candidates cannot be guessed between.
    with pytest.raises(FileExistsError):
        _ = HealthSource(path=folder).archive_path


# --- the heart-rate series ---------------------------------------------------


def test_hr_series_lands_on_its_workout(export):
    """Samples inside the window, as seconds-from-start; outside, dropped."""
    rows = list(HealthSource(path=export).rows())
    hr = next(
        r
        for r in rows
        if r["kind"] == "workout_hr" and r["activity"] == "FunctionalStrengthTraining"
    )

    # 17:30 (before) and 19:30 (after) are excluded; five samples remain,
    # offset from the 18:02:11 start, values rounded to whole bpm.
    assert hr["hr_offsets_s"] == [169, 469, 1069, 2269, 2749]
    assert hr["hr_bpm"] == [80, 120, 130, 125, 90]
    assert hr["strength"] is True
    assert hr["ended_at"].startswith("2026-05-31T18:49:41")
    # The statistics Apple embeds in the Workout element ride along.
    assert hr["hr_avg_session"] == 110.5
    assert hr["hr_min_session"] == 70
    assert hr["hr_max_session"] == 130
    assert hr["active_kcal"] == 332.87
    assert hr["avg_mets"] == 4.44915


def test_session_stats_survive_without_a_series(export):
    """The export prunes HR records after ~7 months; the stats stay.

    The Walking workout has a WorkoutStatistics child but no HR records in
    its window — the row still lands, carrying the stats and empty arrays.
    """
    rows = list(HealthSource(path=export).rows())
    hr = next(
        r for r in rows if r["kind"] == "workout_hr" and r["activity"] == "Walking"
    )
    assert hr["hr_offsets_s"] == []
    assert hr["hr_bpm"] == []
    assert hr["hr_avg_session"] == 98.2


def test_no_hr_data_means_no_workout_hr_row(export):
    """Absence is a fact about measurement — never an empty row."""
    rows = list(HealthSource(path=export).rows())
    activities = {r["activity"] for r in rows if r["kind"] == "workout_hr"}
    assert "TraditionalStrengthTraining" not in activities


def test_hr_row_pairs_one_to_one_with_its_workout(export):
    """Same fingerprint inputs, different prefix — stable across re-imports."""
    rows = list(HealthSource(path=export).rows())
    workout_ids = {r["id"] for r in rows if r["kind"] == "workout"}
    for hr in (r for r in rows if r["kind"] == "workout_hr"):
        assert hr["workout_id"] in workout_ids
        assert hr["id"] == hr["workout_id"].replace(
            "health:workout:", "health:workout_hr:"
        )


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


# --- intensity features -------------------------------------------------------


def test_intensity_active_span_is_threshold_crossing():
    """Warm-up and cool-down fall outside the span; rests inside count.

    35 samples a minute apart: 5 warm-up at 80, a work block peaking at 130,
    5 cool-down at 90. Threshold is 70% of the session max (130) = 91, so the
    span runs from the first to the last work sample and the mean is taken
    over every sample inside it.
    """
    offsets = [i * 60 for i in range(35)]
    bpm = [80] * 5 + [125] * 12 + [130] + [125] * 12 + [90] * 5
    features = embodiment.intensity(offsets, bpm)
    assert features is not None
    assert features["threshold_bpm"] == 91
    # Samples 5..29 a minute apart: 24 dwells at the 60 s cap.
    assert features["active_minutes"] == 24.0
    assert features["hr_mean_active"] == 125.2
    assert features["hr_min_active"] == 125
    assert features["peak_bpm"] == 130


def test_intensity_dwell_is_capped():
    """A gap in an otherwise dense series cannot inflate time-in-zone.

    Twenty-eight samples at 5 s cadence, one 10-minute hole, two more samples:
    dwelling through the hole would claim 10 minutes in zone the watch never
    saw; the cap holds that gap's contribution to DWELL_CAP_S.
    """
    offsets = [i * 5 for i in range(28)] + [735, 740]
    features = embodiment.intensity(offsets, [120] * 30)
    assert features is not None
    assert features["elevated_minutes"] == 3.3  # 28 x 5s + one capped 60s
    # The active span is observed time too — the hole cannot stretch it.
    assert features["active_minutes"] == 3.3


def test_intensity_refuses_background_density():
    """The forgotten-running hike: 85 samples across 34 hours.

    Enough samples to pass a count floor, sampled minutes apart — the first
    rendered surface drew a 2,058-minute "active span" through it. Density is
    the gate: a median gap above MAX_MEDIAN_GAP_S is background sampling, not
    a tracked session.
    """
    offsets = [i * 1440 for i in range(85)]
    assert embodiment.intensity(offsets, [90] * 85) is None


def test_intensity_refuses_a_sparse_series():
    """Background sampling is a real series but not a usable one.

    The real export splits cleanly: watch-tracked sessions carry ~1,000+
    samples, everything else a handful. An active span drawn through five
    background readings would be a confident answer the data cannot carry.
    """
    assert embodiment.intensity([], []) is None
    assert embodiment.intensity([0], [100]) is None
    thin = list(range(0, 29 * 60, 60))
    assert embodiment.intensity(thin, [120] * 29) is None


def test_intensity_flat_series_spans_everything():
    """A flat series is all above its own 70% threshold — span is the whole."""
    offsets = [i * 60 for i in range(30)]
    features = embodiment.intensity(offsets, [100] * 30)
    assert features is not None
    assert features["active_minutes"] == 29.0
    assert features["hr_min_active"] == 100


def test_intensity_summary_counts_coverage(export):
    """Coverage is stated against ALL workouts.

    The fixture's series is five samples — a real series, below the usable
    floor — so features are refused while the session statistics still speak.
    Absence of features stays a fact about the series, never about the body.
    """
    rows = list(HealthSource(path=export).rows())
    summary = embodiment.intensity_summary(rows)
    assert summary["workouts"] == 3
    assert summary["with_stats"] == 2  # Functional (thin series) + Walking (stats)
    assert summary["with_features"] == 0
    assert summary["recent"] == []
    sessions = embodiment.intensity_sessions(rows)
    walking = next(s for s in sessions if s["activity"] == "Walking")
    assert walking["features"] is None
    assert walking["hr_avg_session"] == 98.2
