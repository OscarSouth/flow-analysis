"""Embodiment: what was actually done, in a body. Not an impact metric.

`Train` is **one lane** — discipline-based embodiment — and nothing here splits
it. The distinction between strength work and instrumental practice matters when
*troubleshooting an output*, never when scoring a day.

Two honest jobs:

1. **A second observer of Train.** The board records that a card moved; the watch
   records that a body did something. Where they disagree, that is worth knowing.
2. **A slow state variable.** Body mass responds to months, not to Tuesdays, so
   it is smoothed and read at monthly cadence — which is also the cadence Oscar
   asked for.

The one thing this module must never do is present a *measurement* gap as a
*behaviour* gap. Silence from the watch means the watch was silent; it does not
mean nothing happened.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from ..tiers import TIER_EMBODIMENT, row_tier

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ..config import Config

# Beyond this, the watch has been quiet long enough that the series should be
# treated as stale rather than as a run of rest days.
STALE_AFTER_DAYS = 21

# Body mass moves a kilo on water alone, so a single reading is noise.
SMOOTH_DAYS = 28

# --- workout intensity (provisional, by design) -------------------------------
#
# Oscar's measure, operationalised 2026-08-21 (devproposal:2026-08-21:
# workout-intensity): active span = first to last sample at or above a working
# threshold, judged against that session's own max so it survives his varied
# workout patterns. Both constants are PROVISIONAL — the raw series is archived
# precisely so these can be revised in dialogue without a fresh export.
WORKING_HR_FRACTION = 0.70

# A sample's dwell is the gap to the next sample, capped so sparse background
# sampling cannot inflate time-in-zone. In-workout cadence is ~5 s; a gap past
# the cap means the watch was not really watching.
DWELL_CAP_S = 60

# Features are refused below this many samples, and below this sampling
# density. Measured on the 2026-08-21 export the real distribution splits
# cleanly: watch-tracked sessions sample every ~5 s, background readings
# minutes apart — and rendering the first cut of this surface showed why count
# alone is not enough: a forgotten-running 34-hour "hike" carried 85
# background samples and drew a 2,058-minute active span. A span drawn through
# background samples is a confident answer to a question the series cannot
# carry. The session statistics on the same row still speak for refused
# workouts.
MIN_SERIES_SAMPLES = 30
MAX_MEDIAN_GAP_S = 60

# Per-session intensity lines shown on the surface.
RECENT_SESSIONS = 5


def _embodiment(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if row_tier(r) == TIER_EMBODIMENT]


def workouts_by_month(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Sessions per month, split by kind for context but never scored separately."""
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"strength": 0, "cardio": 0})
    for row in _embodiment(rows):
        if row.get("kind") != "workout" or not row.get("created_at"):
            continue
        month = out[row["created_at"][:7]]
        month["strength" if row.get("strength") else "cardio"] += 1
    return dict(sorted(out.items()))


def workout_coverage(
    rows: Sequence[dict[str, Any]], today: date | None = None
) -> dict[str, Any]:
    """When the watch last logged anything, and whether that is stale.

    The distinction this exists to protect: a long silence is a gap in
    *measurement*, and reading it as a gap in *training* would be an accusation
    the data cannot support.
    """
    stamps = sorted(
        row["created_at"]
        for row in _embodiment(rows)
        if row.get("kind") == "workout" and row.get("created_at")
    )
    now = today or datetime.now(UTC).date()
    if not stamps:
        return {
            "total": 0,
            "first": None,
            "last": None,
            "days_since": None,
            "stale": True,
        }
    last = date.fromisoformat(stamps[-1][:10])
    days_since = (now - last).days
    return {
        "total": len(stamps),
        "first": stamps[0][:10],
        "last": stamps[-1][:10],
        "days_since": days_since,
        "stale": days_since > STALE_AFTER_DAYS,
    }


def intensity(offsets_s: Sequence[int], bpm: Sequence[int]) -> dict[str, Any] | None:
    """Per-session intensity features from one workout's heart-rate series.

    Active span runs from the first to the last sample at or above the working
    threshold (70% of this session's max — self-calibrating, so a heavy short
    session and a long light one are each judged against themselves), measured
    as *observed* time: the sum of capped inter-sample dwells between the
    endpoints, not their raw difference. A dense burst followed by hours of
    background silence — the forgotten-running hike again — would otherwise
    stretch the span across time the watch never watched. Mean and min are
    taken across *every* sample inside the span: the rests between sets are
    exactly what the measure exists to see.

    `elevated_minutes` is time-in-zone across the whole session, each sample
    dwelling until the next (capped, so sparse sampling cannot inflate it; the
    final sample contributes nothing rather than a guess).

    Returns None below `MIN_SERIES_SAMPLES` samples or above a median
    inter-sample gap of `MAX_MEDIAN_GAP_S` — sparse background readings are a
    real series but not a *usable* one, and refusing is the honest output.
    """
    n = len(bpm)
    if n < MIN_SERIES_SAMPLES or len(offsets_s) != n:
        return None
    gaps = sorted(offsets_s[i + 1] - offsets_s[i] for i in range(n - 1))
    if gaps[len(gaps) // 2] > MAX_MEDIAN_GAP_S:
        return None
    peak = max(bpm)
    threshold = peak * WORKING_HR_FRACTION
    above = [i for i, v in enumerate(bpm) if v >= threshold]
    first, last = above[0], above[-1]
    in_span = bpm[first : last + 1]
    elevated_s = sum(
        min(offsets_s[i + 1] - offsets_s[i], DWELL_CAP_S)
        for i in range(n - 1)
        if bpm[i] >= threshold
    )
    active_s = sum(
        min(offsets_s[i + 1] - offsets_s[i], DWELL_CAP_S) for i in range(first, last)
    )
    return {
        "samples": n,
        "threshold_bpm": round(threshold),
        "peak_bpm": peak,
        "active_minutes": round(active_s / 60, 1),
        "hr_mean_active": round(sum(in_span) / len(in_span), 1),
        "hr_min_active": min(in_span),
        "elevated_minutes": round(elevated_s / 60, 1),
    }


def intensity_sessions(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chronological per-session intensity, from the archived HR series.

    Sessions whose series was pruned from the export still appear when Apple's
    embedded session statistics survived — features are None there, the
    statistics carry what is known.
    """
    out = []
    for row in _embodiment(rows):
        if row.get("kind") != "workout_hr" or not row.get("created_at"):
            continue
        features = intensity(row.get("hr_offsets_s") or [], row.get("hr_bpm") or [])
        out.append(
            {
                "day": row["created_at"][:10],
                "activity": row.get("activity"),
                "strength": bool(row.get("strength")),
                "features": features,
                "hr_avg_session": row.get("hr_avg_session"),
                "hr_max_session": row.get("hr_max_session"),
                "avg_mets": row.get("avg_mets"),
            }
        )
    return sorted(out, key=lambda r: r["day"])


def intensity_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Coverage plus the most recent sessions — visibility, never a trend.

    Coverage is stated against the total workout count so the absence of a
    series stays a fact about the export's retention, not about the body.
    """
    sessions = intensity_sessions(rows)
    workouts = sum(1 for r in _embodiment(rows) if r.get("kind") == "workout")
    with_features = [s for s in sessions if s["features"]]
    return {
        "workouts": workouts,
        "with_stats": len(sessions),
        "with_features": len(with_features),
        # The recent *usable* sessions: a surface line per background-sampled
        # workout would be noise wearing a number.
        "recent": with_features[-RECENT_SESSIONS:],
    }


def body_series(
    rows: Sequence[dict[str, Any]], metric: str = "body_mass"
) -> list[dict[str, Any]]:
    """Chronological readings for one body metric."""
    series = [
        {"day": row["created_at"][:10], "value": row["value"], "unit": row.get("unit")}
        for row in _embodiment(rows)
        if row.get("kind") == "body"
        and row.get("metric") == metric
        and row.get("created_at")
        and row.get("value") is not None
    ]
    return sorted(series, key=lambda r: r["day"])


def body_trend(
    rows: Sequence[dict[str, Any]], metric: str = "body_mass"
) -> dict[str, Any] | None:
    """Latest reading against a smoothed recent average.

    Smoothed because body mass swings a kilo on hydration alone: a single reading
    against a single earlier reading would manufacture a trend out of water.
    """
    series = body_series(rows, metric)
    if not series:
        return None
    latest = series[-1]
    last_day = date.fromisoformat(latest["day"])
    recent = [
        r["value"]
        for r in series
        if (last_day - date.fromisoformat(r["day"])).days < SMOOTH_DAYS
    ]
    earlier = [
        r["value"]
        for r in series
        if SMOOTH_DAYS
        <= (last_day - date.fromisoformat(r["day"])).days
        < SMOOTH_DAYS * 2
    ]
    recent_mean = sum(recent) / len(recent) if recent else None
    earlier_mean = sum(earlier) / len(earlier) if earlier else None
    return {
        "metric": metric,
        "latest": latest["value"],
        "latest_day": latest["day"],
        "unit": latest.get("unit"),
        "readings": len(series),
        "recent_mean": round(recent_mean, 2) if recent_mean is not None else None,
        "recent_n": len(recent),
        "earlier_mean": round(earlier_mean, 2) if earlier_mean is not None else None,
        "earlier_n": len(earlier),
        "change": (
            round(recent_mean - earlier_mean, 2)
            if recent_mean is not None and earlier_mean is not None
            else None
        ),
    }


def since_epoch(rows: Sequence[dict[str, Any]], epoch: date) -> dict[str, Any]:
    """Embodiment since the practice began — the same ground zero as reception.

    Everything before the epoch was earned under a different regime: ad-hoc
    training, and — as it happens — unreliable measurement after a phone change.
    It is context, not the practice's record.

    Body mass is the exception that proves the rule. It is a *level*, not an
    accumulation, so the epoch value is a genuine starting line rather than
    something to be discounted: the question is how far it has moved since.
    """
    cutoff = epoch.isoformat()
    workouts = [
        row
        for row in _embodiment(rows)
        if row.get("kind") == "workout" and (row.get("created_at") or "")[:10] >= cutoff
    ]
    body = [
        row
        for row in _embodiment(rows)
        if row.get("kind") == "body" and (row.get("created_at") or "")[:10] >= cutoff
    ]

    mass = body_series(rows, "body_mass")
    at_epoch = [r for r in mass if r["day"] <= cutoff]
    since = [r for r in mass if r["day"] >= cutoff]
    baseline = at_epoch[-1] if at_epoch else None
    latest = since[-1] if since else None

    return {
        "workouts": len(workouts),
        "strength": sum(1 for r in workouts if r.get("strength")),
        "body_readings": len(body),
        "mass_at_epoch": baseline["value"] if baseline else None,
        "mass_at_epoch_day": baseline["day"] if baseline else None,
        "mass_now": latest["value"] if latest else None,
        "mass_change": (
            round(latest["value"] - baseline["value"], 2)
            if baseline and latest
            else None
        ),
    }


def summarise(cfg: Config, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The embodiment surface: what the body did, as a second observer.

    Not an impact metric and not a score. Silence here is a gap in *measurement*
    — the watch is worn while exercising or out of the house — so a quiet stretch
    is reported as unobserved rather than as nothing having happened.

    `rows` is passed in rather than loaded: Layer B never reaches into the store.
    """
    all_rows = list(rows)
    return {
        "epoch": cfg.start_date.isoformat() if cfg.start_date else None,
        "since_epoch": since_epoch(all_rows, cfg.start_date)
        if cfg.start_date
        else None,
        "by_month": workouts_by_month(all_rows),
        "coverage": workout_coverage(all_rows),
        "intensity": intensity_summary(all_rows),
        "mass": body_trend(all_rows, "body_mass"),
        "fat": body_trend(all_rows, "body_fat"),
    }


def render(summary: dict[str, Any]) -> str:
    """Monthly cadence. Never a weekly score."""
    coverage = summary["coverage"]
    if not coverage["total"] and not summary["mass"]:
        return ""

    lines = ["Embodiment — a second observer of Train, not a score", ""]

    era = summary.get("since_epoch")
    if era:
        lines.append(
            f"  Since flow began ({summary['epoch']}): {era['workouts']} workout(s), "
            f"{era['body_readings']} body reading(s)"
        )
        if era.get("mass_at_epoch") is not None:
            if era.get("mass_change") is not None:
                lines.append(
                    f"    Body mass {era['mass_now']} kg, from {era['mass_at_epoch']} "
                    f"kg "
                    f"at the epoch ({era['mass_at_epoch_day']}) — "
                    f"{era['mass_change']:+} kg"
                )
            else:
                lines.append(
                    f"    Body mass at the epoch: {era['mass_at_epoch']} kg "
                    f"({era['mass_at_epoch_day']}) — the starting line"
                )

    if coverage["total"]:
        lines.append(
            f"  Watch: {coverage['total']} sessions, {coverage['first']} .. "
            f"{coverage['last']}"
        )
        if coverage["stale"]:
            lines += [
                f"  **No workout logged for {coverage['days_since']} days.** That is a "
                "gap in measurement,",
                "  not evidence of a gap in training — the watch has been "
                "silent, which is not",
                "  the same as the body having been. Treat the series as stale "
                "until it resumes.",
            ]

    intense = summary.get("intensity") or {}
    if intense.get("with_stats"):
        lines += [
            "",
            f"  Intensity — usable HR series on {intense['with_features']} of "
            f"{intense['workouts']} sessions (dense only where",
            "  the watch itself tracked the session; the rest carry background "
            "samples and per-session",
            "  statistics). Active span = first to last sample at "
            f"≥{int(WORKING_HR_FRACTION * 100)}% of that session's max —",
            "  a provisional definition, revisable from the archived series.",
        ]
        for s in intense["recent"]:
            f = s["features"]
            detail = (
                f"span {f['active_minutes']}m, avg {f['hr_mean_active']}"
                f" / min {f['hr_min_active']} bpm, peak {f['peak_bpm']}"
            )
            if not s["strength"]:
                detail += f", elevated {f['elevated_minutes']}m"
            mets = f", {s['avg_mets']:.1f} METs" if s.get("avg_mets") else ""
            lines.append(f"    {s['day']}  {s['activity']}: {detail}{mets}")

    months = summary["by_month"]
    if months:
        recent = list(months.items())[-6:]
        lines += ["", "  Sessions by month (strength / other) — pre-epoch context:"]
        for month, stat in recent:
            bar = "#" * stat["strength"]
            lines.append(
                f"    {month}  {stat['strength']:2} / {stat['cardio']:<2} {bar}"
            )

    mass = summary["mass"]
    if mass:
        lines += [
            "",
            f"  Body mass: {mass['latest']} {mass['unit']} on {mass['latest_day']}",
        ]
        if mass["change"] is not None:
            direction = "up" if mass["change"] > 0 else "down"
            lines.append(
                f"    {SMOOTH_DAYS}-day mean {mass['recent_mean']} vs "
                f"{mass['earlier_mean']} "
                f"the {SMOOTH_DAYS} days before — {direction} {abs(mass['change'])} "
                f"(n={mass['recent_n']} vs {mass['earlier_n']})"
            )
        else:
            lines.append(
                f"    only {mass['recent_n']} reading(s) in the last "
                f"{SMOOTH_DAYS} days — "
                "not enough to smooth against a prior window"
            )

    lines += [
        "",
        "  Everything before the epoch is ground zero, the same as reception: earned",
        "  under a different regime, and after a phone change that made the "
        "measurement",
        "  unreliable. Body mass is the exception — a level, not an "
        "accumulation, so its",
        "  epoch value is a genuine starting line rather than something to discount.",
        "",
        "  Read monthly, never weekly. Body mass answers to months; a single reading",
        "  moves a kilo on hydration alone.",
    ]
    return "\n".join(lines)
