"""Apple Health: embodiment, which is not an impact metric.

`Train` is **one lane** — discipline-based embodiment — and stays one lane. What
this source adds is not a score but a second observer: the board can only record
that a card moved, while the watch records that a body did something. Whether a
given day's Train was strength work or instrumental practice matters when
*troubleshooting an output*, never when scoring a day.

Two kinds of row, both `embodiment`:

  workout   an explicit session: type, start, duration
  body      mass, body fat, lean mass — arriving from the Renpho scale via Health

**Only explicit workouts are trusted.** Step counts, stand hours and activity
rings are excluded on purpose: the watch is worn while exercising or out of the
house, so daily totals are missing-not-at-random and not comparable across days.
A workout session, by contrast, means what it says.

The export is a ~750 MB XML inside a zip, so it is streamed with `iterparse` and
cleared element by element — loading it whole is not an option.

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
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z").isoformat()
    except ValueError:
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
        """The zip itself, whether a file or a directory was configured."""
        return self.path / "export.zip" if self.path.is_dir() else self.path

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

        **The tradeoff, stated once:** the export contains far more than is
        extracted — heart rate, energy, distance, and much else. Purging means a
        future metric needs a *fresh* export rather than a re-parse of this one.
        That is the right trade while only workouts and body mass are read, and
        it is the reason this is worth revisiting if that changes.

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
        """Workouts and body measurements, streamed."""
        wanted = self.strength_types | self.cardio_types
        archive, handle = self._open()
        try:
            for _, el in ET.iterparse(handle, events=("end",)):
                if el.tag == "Workout":
                    row = self._workout(el, wanted)
                    if row:
                        yield row
                elif el.tag == "Record":
                    row = self._body(el)
                    if row:
                        yield row
                el.clear()
        finally:
            handle.close()
            archive.close()

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
