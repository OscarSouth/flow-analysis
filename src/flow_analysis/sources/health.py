"""Apple Health: embodiment, which is not an impact metric.

`Train` is **one lane** — discipline-based embodiment — and stays one lane. What
this source adds is not a score but a second observer: the board can only record
that a card moved, while the watch records that a body did something. Whether a
given day's Train was strength work or instrumental practice matters when
*troubleshooting an output*, never when scoring a day.

Three kinds of row, all `embodiment`:

  workout     an explicit session: type, start, duration
  body        mass, body fat, lean mass — arriving from the Renpho scale via Health
  workout_hr  the heart-rate series inside one workout's window, plus the
              per-session statistics Apple embeds in the Workout element

**Only explicit workouts are trusted.** Step counts, stand hours and activity
rings are excluded on purpose: the watch is worn while exercising or out of the
house, so daily totals are missing-not-at-random and not comparable across days.
A workout session, by contrast, means what it says.

`workout_hr` exists because workout *quality* is the leading indicator the grid
cannot see (belief:2026-08-21:health-hidden-layer): regularity survives
slippage, intensity does not. The raw series is archived rather than features,
so the (provisional) feature definitions in `metrics/embodiment.py` can be
revised without a fresh export. Measured on the 2026-08-21 export:

  - HR records are instantaneous samples (~5 s cadence during workouts,
    `startDate == endDate`, unit `count/min`), top-level in the XML, matched
    to workouts purely by time window.
  - The series is *dense* (~5 s cadence, 1,000+ samples) only for sessions
    the watch itself tracked; other workouts carry a handful of background
    readings. The `WorkoutStatistics` child on the Workout element (session
    average/min/max HR) speaks for those, so a `workout_hr` row is emitted
    whenever either is present and the feature layer refuses thin series.
  - HR records precede Workouts in document order, so the parse is two-pass:
    windows first, then the series. Buffering the series until windows are
    known would hold millions of samples.

The export is a ~750 MB XML inside a zip, so it is streamed with `iterparse` and
cleared element by element — loading it whole is not an option. The one
exception to clear-on-end: elements *inside* a Workout are left for the
Workout's own clear, because clearing a child wipes it before the parent's end
event can read the per-session statistics.

Measured on the first real export, 2026-08-17 (272 workouts):

  FunctionalStrengthTraining  208     <- strength training is *Functional* here
  Walking                      35
  Cycling                      24
  Running                       3
  Hiking                        2

That first line is the trap. The obvious constant to reach for is
`TraditionalStrengthTraining`, which appears **zero** times in this export — a
filter on it would match nothing and report that no strength training had ever
happened, which is both wrong and plausible-looking.
"""

from __future__ import annotations

import hashlib
import zipfile
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any
from xml.etree import ElementTree as ET

from ..tiers import TIER_EMBODIMENT

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ..config import Config

EXPORT_MEMBER = "apple_health_export/export.xml"

# Workout types that count as embodiment. Both strength spellings are accepted so
# that a change of device or watchOS version cannot silently empty the series.
STRENGTH_TYPES = frozenset(
    {
        "HKWorkoutActivityTypeFunctionalStrengthTraining",
        "HKWorkoutActivityTypeTraditionalStrengthTraining",
    }
)
CARDIO_TYPES = frozenset(
    {
        "HKWorkoutActivityTypeWalking",
        "HKWorkoutActivityTypeRunning",
        "HKWorkoutActivityTypeCycling",
        "HKWorkoutActivityTypeHiking",
    }
)

BODY_METRICS = {
    "HKQuantityTypeIdentifierBodyMass": "body_mass",
    "HKQuantityTypeIdentifierBodyFatPercentage": "body_fat",
    "HKQuantityTypeIdentifierLeanBodyMass": "lean_mass",
}

HR_TYPE = "HKQuantityTypeIdentifierHeartRate"


def _fingerprint(*parts: Any) -> str:  # noqa: ANN401 - mixed id material
    """A deterministic id.

    The export exposes no stable UUID, so re-importing an overlapping export must
    produce identical ids or the store would accumulate duplicates of the same
    session.
    """
    material = "|".join(str(p) for p in parts)
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def _parse_stamp(value: str | None) -> str | None:
    """Apple writes `2026-08-17 09:30:00 +0100`; normalise to ISO 8601."""
    parsed = _parse_dt(value)
    return parsed.isoformat() if parsed else None


def _parse_dt(value: str | None) -> datetime | None:
    """The same stamp as `_parse_stamp`, kept as a datetime for window maths."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return None


def _leading_float(value: str | None) -> float | None:
    """The number at the front of values like `4.44915 kcal/hr·kg`."""
    if not value:
        return None
    try:
        return float(value.split()[0])
    except (ValueError, IndexError):
        return None


@dataclass
class HealthSource:
    """An Apple Health export, read for workouts and body measurements only.

    `path` is the dropped zip or the directory holding it. The export is
    consumed and then purged: it is 35 MB of personal data in a working
    directory, and everything read from it is already in the archive.
    """

    path: Path
    strength_types: frozenset[str] = field(default_factory=lambda: STRENGTH_TYPES)
    cardio_types: frozenset[str] = field(default_factory=lambda: CARDIO_TYPES)

    @property
    def archive_path(self) -> Path:
        """The zip itself, whether a file or a directory was configured.

        A configured directory prefers the canonical `export.zip`, but accepts
        exactly one `export*.zip` otherwise — Finder-style duplicates arrive as
        `export 2.zip`, and a silent miss here would report a healthy sync with
        the dropped data untouched. Two candidates is ambiguity, and ambiguity
        fails loudly rather than guessing which export is current.
        """
        if not self.path.is_dir():
            return self.path
        canonical = self.path / "export.zip"
        if canonical.exists():
            return canonical
        candidates = sorted(self.path.glob("export*.zip"))
        if len(candidates) > 1:
            names = ", ".join(c.name for c in candidates)
            msg = f"Multiple Apple Health exports in {self.path}: {names}"
            raise FileExistsError(msg)
        return candidates[0] if candidates else canonical

    def _open(self) -> tuple[zipfile.ZipFile, IO[bytes]]:
        candidate = self.archive_path
        if not candidate.exists():
            raise FileNotFoundError(f"No Apple Health export at {candidate}")
        archive = zipfile.ZipFile(candidate)
        return archive, archive.open(EXPORT_MEMBER)

    def purge(self) -> list[str]:
        """Delete the consumed export.

        An export is a delivery mechanism, not a store. Once its workouts and
        body readings are in `data/signals.jsonl` the 35 MB zip is dead weight,
        it is personal data sitting in a working directory, and it is easy to
        commit by accident.

        **The tradeoff, stated once:** the export contains more than is
        extracted — sleep, distance, energy series, and much else. Purging
        means a future metric needs a *fresh* export rather than a re-parse of
        this one. Heart rate crossed to the extracted side on 2026-08-21
        (devproposal:2026-08-21:workout-intensity); the trade stands for the
        rest, and remains worth revisiting if that changes.

        Only ever called after a successful import, and only for files this
        source actually consumed.
        """
        removed: list[str] = []
        target = self.archive_path
        if target.exists() and target.is_file():
            size_mb = target.stat().st_size / 1e6
            target.unlink()
            removed.append(f"{target.name} ({size_mb:.0f} MB)")
        return removed

    def rows(self) -> Iterator[dict[str, Any]]:
        """Workouts, body measurements and per-workout heart rate, streamed.

        Two passes over the same zip: HR records precede Workouts in document
        order, so the windows must exist before the series can be assigned.
        Pass 1 yields the workout and body rows while collecting windows; pass
        2 re-opens the archive and yields one `workout_hr` row per window.
        """
        wanted = self.strength_types | self.cardio_types
        windows: list[dict[str, Any]] = []
        archive, handle = self._open()
        try:
            inside_workout = False
            for event, el in ET.iterparse(handle, events=("start", "end")):
                if event == "start":
                    if el.tag == "Workout":
                        inside_workout = True
                    continue
                if el.tag == "Workout":
                    inside_workout = False
                    row = self._workout(el, wanted)
                    if row:
                        yield row
                        window = self._window(el, row)
                        if window:
                            windows.append(window)
                    el.clear()
                elif not inside_workout:
                    # Children of a Workout stay attached until the Workout's
                    # own clear — _window reads them at the parent's end event.
                    if el.tag == "Record":
                        body = self._body(el)
                        if body:
                            yield body
                    el.clear()
        finally:
            handle.close()
            archive.close()
        yield from self._hr_rows(windows)

    def _workout(self, el: ET.Element, wanted: frozenset[str]) -> dict[str, Any] | None:
        kind = el.get("workoutActivityType") or ""
        if kind not in wanted:
            return None
        start = _parse_stamp(el.get("startDate"))
        if not start:
            return None
        duration = el.get("duration")
        short = kind.replace("HKWorkoutActivityType", "")
        return {
            "id": f"health:workout:{_fingerprint(kind, start, duration)}",
            "tier": TIER_EMBODIMENT,
            "source": "apple_health",
            "kind": "workout",
            "activity": short,
            "strength": kind in self.strength_types,
            "created_at": start,
            "duration_minutes": round(float(duration), 1) if duration else None,
            "device": el.get("sourceName"),
        }

    def _window(self, el: ET.Element, row: dict[str, Any]) -> dict[str, Any] | None:
        """The workout's time window plus the statistics Apple embeds in it.

        Read at the Workout's end event, which is why children must not have
        been cleared. Session HR statistics outlive the HR record series in
        the export, so they are captured even when pass 2 will find no
        samples.
        """
        start_dt = _parse_dt(el.get("startDate"))
        end_dt = _parse_dt(el.get("endDate"))
        if start_dt is None or end_dt is None or end_dt <= start_dt:
            return None
        hr_avg = hr_min = hr_max = kcal = mets = None
        for child in el:
            if child.tag == "WorkoutStatistics":
                stat = child.get("type")
                if stat == HR_TYPE:
                    hr_avg = _leading_float(child.get("average"))
                    hr_min = _leading_float(child.get("minimum"))
                    hr_max = _leading_float(child.get("maximum"))
                elif stat == "HKQuantityTypeIdentifierActiveEnergyBurned":
                    kcal = _leading_float(child.get("sum"))
            elif child.tag == "MetadataEntry" and child.get("key") == "HKAverageMETs":
                mets = _leading_float(child.get("value"))
        return {
            "start_dt": start_dt,
            "end_dt": end_dt,
            "fingerprint": row["id"].rsplit(":", 1)[1],
            "activity": row["activity"],
            "strength": row["strength"],
            "created_at": row["created_at"],
            "ended_at": end_dt.isoformat(),
            "device": row["device"],
            "hr_avg_session": hr_avg,
            "hr_min_session": hr_min,
            "hr_max_session": hr_max,
            "active_kcal": kcal,
            "avg_mets": mets,
        }

    def _hr_rows(self, windows: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
        """Pass 2: assign the heart-rate series to workout windows.

        A `workout_hr` row is emitted for a window holding samples *or*
        session statistics — many workouts carry only sparse background
        samples while the statistics survive with the workout. A window with
        neither emits nothing: absence stays a fact about measurement, not a
        zero.
        """
        if not windows:
            return
        windows.sort(key=lambda w: w["start_dt"])
        starts = [w["start_dt"] for w in windows]
        max_span = max(w["end_dt"] - w["start_dt"] for w in windows)
        # Cheap prefilter: strptime only for records on a date any window
        # touches — the export holds hundreds of thousands of HR records and
        # most are background samples outside any workout.
        dates = {w["start_dt"].date().isoformat() for w in windows} | {
            w["end_dt"].date().isoformat() for w in windows
        }
        samples: dict[int, list[tuple[datetime, int]]] = {}
        archive, handle = self._open()
        try:
            for _, el in ET.iterparse(handle, events=("end",)):
                if el.tag == "Record" and el.get("type") == HR_TYPE:
                    stamp = el.get("startDate") or ""
                    if stamp[:10] in dates:
                        at = _parse_dt(stamp)
                        value = el.get("value")
                        if at is not None and value is not None:
                            bpm = round(float(value))
                            # Overlapping windows are rare but real (a paused
                            # workout beside a new one); the sample lands in
                            # every window containing it.
                            idx = bisect_right(starts, at) - 1
                            while idx >= 0 and starts[idx] >= at - max_span:
                                if at <= windows[idx]["end_dt"]:
                                    samples.setdefault(idx, []).append((at, bpm))
                                idx -= 1
                el.clear()
        finally:
            handle.close()
            archive.close()
        for idx, window in enumerate(windows):
            series = sorted(samples.get(idx, []))
            if not series and window["hr_avg_session"] is None:
                continue
            start = window["start_dt"]
            yield {
                "id": f"health:workout_hr:{window['fingerprint']}",
                "tier": TIER_EMBODIMENT,
                "source": "apple_health",
                "kind": "workout_hr",
                "workout_id": f"health:workout:{window['fingerprint']}",
                "activity": window["activity"],
                "strength": window["strength"],
                "created_at": window["created_at"],
                "ended_at": window["ended_at"],
                "device": window["device"],
                "hr_offsets_s": [int((at - start).total_seconds()) for at, _ in series],
                "hr_bpm": [bpm for _, bpm in series],
                "hr_avg_session": window["hr_avg_session"],
                "hr_min_session": window["hr_min_session"],
                "hr_max_session": window["hr_max_session"],
                "active_kcal": window["active_kcal"],
                "avg_mets": window["avg_mets"],
            }

    def _body(self, el: ET.Element) -> dict[str, Any] | None:
        metric = BODY_METRICS.get(el.get("type") or "")
        if not metric:
            return None
        start = _parse_stamp(el.get("startDate"))
        value = el.get("value")
        if not start or value is None:
            return None
        try:
            numeric = float(value)
        except ValueError:
            return None
        return {
            "id": f"health:{metric}:{_fingerprint(metric, start, value)}",
            "tier": TIER_EMBODIMENT,
            "source": "apple_health",
            "kind": "body",
            "metric": metric,
            "created_at": start,
            "value": numeric,
            "unit": el.get("unit"),
            "device": el.get("sourceName"),
        }


def source_from_config(cfg: Config) -> HealthSource | None:
    """Read the `signals.health` block, if configured."""
    from ..config import REPO_ROOT

    block = ((cfg.intent.get("signals") or {}).get("health")) or {}
    directory = block.get("directory")
    if not directory:
        return None
    path = Path(directory)
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.exists():
        return None
    return HealthSource(path=path)
