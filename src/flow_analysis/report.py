"""Regularity metrics over the folded flow rows.

Pure stdlib so `flow report` always runs; parquet/CSV export is there for doing
the real analysis elsewhere.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING, Any

from .metrics.contracts import REGISTRY
from .metrics.grid import COMPLETED, FlowRow, to_dicts
from .util import parse_iso, to_local

if TYPE_CHECKING:
    from pathlib import Path

    from .config import Config
    from .metrics.diagnostics import Measure

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _streaks(days_hit: dict[str, bool]) -> tuple[int, int]:
    """(current, longest) run of consecutive True days, walking dates in order."""
    longest = current = running = 0
    for day in sorted(days_hit):
        if days_hit[day]:
            running += 1
            longest = max(longest, running)
        else:
            running = 0
    current = running
    return current, longest


def summarise(cfg: Config, rows: list[FlowRow]) -> dict[str, Any]:
    """Reduce the grid to the numbers the practice surface prints.

    Levels and totals are unconditional — where things stand is a fact and needs
    no N. Anything that reads as a trend is gated before it is shown.
    """
    if not rows:
        return {"empty": True}

    days = sorted({row.day for row in rows})
    by_activity: dict[str, dict[str, bool]] = defaultdict(dict)
    per_day_completed: dict[str, int] = defaultdict(int)
    outcomes: dict[str, int] = defaultdict(int)
    completion_hours: list[int] = []
    start_latencies: list[float] = []
    complete_latencies: list[float] = []
    weekday_hits: dict[str, list[int]] = defaultdict(list)

    for row in rows:
        hit = row.outcome == COMPLETED
        by_activity[row.activity][row.day] = hit
        outcomes[row.outcome] += 1
        if hit:
            per_day_completed[row.day] += 1
            if row.completed_at:
                completion_hours.append(
                    to_local(parse_iso(row.completed_at), cfg.timezone).hour
                )
        if row.minutes_to_start is not None:
            start_latencies.append(row.minutes_to_start)
        if row.minutes_to_complete is not None:
            complete_latencies.append(row.minutes_to_complete)
        weekday = WEEKDAYS[date.fromisoformat(row.day).weekday()]
        weekday_hits[weekday].append(1 if hit else 0)

    n_activities = len(cfg.activities)
    perfect = {day: per_day_completed.get(day, 0) == n_activities for day in days}
    perfect_current, perfect_longest = _streaks(perfect)

    activity_stats = {}
    for activity in cfg.activities:
        hits = by_activity.get(activity, {})
        done = sum(1 for v in hits.values() if v)
        current, longest = _streaks(hits)
        activity_stats[activity] = {
            "days": len(hits),
            "completed": done,
            "rate": round(done / len(hits), 3) if hits else 0.0,
            "current_streak": current,
            "longest_streak": longest,
        }

    rolling = {}
    for window in (7, 28):
        recent = days[-window:]
        if recent:
            done = sum(per_day_completed.get(day, 0) for day in recent)
            rolling[f"rolling_{window}d_rate"] = round(
                done / (len(recent) * n_activities), 3
            )

    return {
        "empty": False,
        "span": [days[0], days[-1]],
        "n_days": len(days),
        "activities": activity_stats,
        "perfect_days": sum(1 for v in perfect.values() if v),
        "perfect_streak_current": perfect_current,
        "perfect_streak_longest": perfect_longest,
        "outcomes": dict(outcomes),
        "rolling": rolling,
        "completion_hour_histogram": _histogram(completion_hours),
        "median_minutes_to_start": _median(start_latencies),
        "median_minutes_to_complete": _median(complete_latencies),
        "weekday_rate": {
            day: round(sum(v) / len(v), 3) for day, v in weekday_hits.items() if v
        },
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 1)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 1)


def _histogram(hours: list[int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for hour in hours:
        out[hour] = out.get(hour, 0) + 1
    return dict(sorted(out.items()))


def render(summary: dict[str, Any], cfg: Config) -> str:
    """The practice surface as text, for a terminal rather than a browser."""
    if summary.get("empty"):
        return "No flow rows yet. Run `flow sync` once the daily rules have fired."

    span = summary["span"]
    lines = [
        f"Flow regularity  {span[0]} .. {span[1]}  ({summary['n_days']} days)",
        f"Day boundary {cfg.drain_at.strftime('%H:%M')} {cfg.timezone}",
        "",
        f"{'activity':<12} {'done':>6} {'days':>6} {'rate':>7} {'streak':>7} "
        f"{'best':>6}",
    ]
    for activity, stat in summary["activities"].items():
        lines.append(
            f"{activity:<12} {stat['completed']:>6} {stat['days']:>6} "
            f"{stat['rate']:>7.1%} {stat['current_streak']:>7} "
            f"{stat['longest_streak']:>6}"
        )

    lines += [
        "",
        f"Perfect days (all {len(cfg.activities)}): {summary['perfect_days']}"
        f"   current streak {summary['perfect_streak_current']}"
        f"   best {summary['perfect_streak_longest']}",
        "",
        "Outcomes: "
        + ", ".join(f"{k}={v}" for k, v in sorted(summary["outcomes"].items())),
    ]

    if summary["rolling"]:
        lines.append(
            "Rolling: "
            + ", ".join(
                f"{k.replace('rolling_', '').replace('_rate', '')}={v:.1%}"
                for k, v in summary["rolling"].items()
            )
        )

    if summary["median_minutes_to_start"] is not None:
        lines.append(
            f"Median minutes spawn->start {summary['median_minutes_to_start']}, "
            f"spawn->done {summary['median_minutes_to_complete']}"
        )

    if summary["weekday_rate"]:
        ordered = [
            (d, summary["weekday_rate"][d])
            for d in WEEKDAYS
            if d in summary["weekday_rate"]
        ]
        lines += ["", "By weekday: " + "  ".join(f"{d} {r:.0%}" for d, r in ordered)]

    hist = summary["completion_hour_histogram"]
    if hist:
        peak = max(hist.values())
        lines += ["", "Completions by local hour:"]
        for hour, count in hist.items():
            bar = "#" * max(1, round(count / peak * 32))
            lines.append(f"  {hour:02d}  {bar} {count}")

    return "\n".join(lines)


def _phrase_charge(measure: Measure) -> str:
    value = measure.value
    if value is None:
        return "no series yet"
    if value < 0.2:
        reading = "even — harmonious, and the quiet precursor to stagnation"
    elif value < 0.6:
        reading = "some tilt between modes"
    else:
        reading = "one mode thriving while another is effectively dead"
    return f"{value:.2f} — {reading}"


def _phrase_coupling(measure: Measure) -> str:
    best = measure.value
    if not best:
        return "no lag could be estimated"
    direction = "higher" if best["r"] > 0 else "lower"
    when = "the same day" if best["lag"] == 0 else f"{best['lag']} days later"
    return (
        f"strongest at lag {best['lag']}d: r={best['r']:+.2f} over {best['n']} pairs "
        f"(adherence today, {direction} output {when})"
    )


def _phrase_aberration(measure: Measure) -> str:
    value = measure.value
    share = value["share_of_producing_days"]
    if value["days"] == 0:
        return (
            f"none — output never arrived on a day {value['channel']} went uncompleted"
        )
    return (
        f"{value['days']} day(s) produced output without completing {value['channel']}"
        + (f", {share:.0%} of producing days" if share is not None else "")
        + " — work outside R that produced value anyway"
    )


def render_posteriors(frame_dicts: list[dict[str, Any]]) -> str:
    """The day's posterior snapshot, as honest interval lines.

    Always shown — a posterior with a wide interval is visibility, not a claim.
    Untrusted rows (the sampler's own diagnostics failed) are named as such and
    never dressed as results. Verdicts arrive gated from the asset.
    """
    if not frame_dicts:
        return ""
    lines = ["Posteriors (90% credible intervals; verdicts gate on N):"]
    for row in frame_dicts:
        measure = row["measure"]
        if not row.get("trusted"):
            lines.append(f"  {measure:<38} untrusted fit — diagnostics failed")
            continue
        span = f"{row['mean']:.2f}  [{row['ci_low']:.2f}, {row['ci_high']:.2f}]"
        verdict = f"  -> {row['verdict']}" if row.get("verdict") else ""
        prob = (
            f"  P={row['probability']:.2f}"
            if row.get("probability") is not None
            else ""
        )
        lines.append(f"  {measure:<38} {span}{prob}{verdict}")
    return "\n".join(lines)


def render_diagnostics(result: dict[str, Any]) -> str:
    """The diagnostic table from docs/06-diagnostics.md, as far as N allows."""
    measures = result["measures"]
    lines = [f"Diagnostics  ({result['days']} days observed)", ""]

    alloc = measures["allocation_vs_capacity"]
    if alloc.ok:
        lines.append("Failure kind — allocation wants time, capacity wants drills:")
        for activity, stat in alloc.value.items():
            if stat["dominant"] is None:
                lines.append(f"  {activity:<10} no failures")
                continue
            lines.append(
                f"  {activity:<10} {stat['dominant']:<10} "
                f"never-started {stat['allocation']:>3}  abandoned "
                f"{stat['capacity']:>3}"
            )
    else:
        lines.append(f"  {alloc}")

    dorm = measures["dormancy"]
    if dorm.ok:
        closed = {a: v for a, v in dorm.value.items() if v["status"] != "open"}
        lines.append("")
        if closed:
            lines.append("Dormancy — channels currently closed:")
            for activity, stat in closed.items():
                lines.append(
                    f"  {activity:<10} {stat['current']} days closed  "
                    f"[{stat['status']}]"
                )
        else:
            longest = max(dorm.value.items(), key=lambda kv: kv[1]["longest"])
            lines.append(
                f"Dormancy: nothing closed right now; longest run so far was "
                f"{longest[0]} at {longest[1]['longest']} days"
            )

    # The contracts: deterministic verdicts inline; posterior contracts show
    # their gate here (the verdicts live on the posterior snapshot, rendered
    # by `flow evidence` and the posterior block below).
    lines += ["", "Contracts (registry in metrics/contracts.py):"]
    for contract in REGISTRY:
        measure = measures.get(contract.key)
        label = f"{contract.title} [{contract.component}]"
        if measure is None or not measure.ok:
            n = measure.n if measure is not None else 0
            needs = measure.needs if measure is not None else contract.needs
            lines.append(f"  {label:<40} not testable yet (N={n}, needs {needs})")
        elif contract.kind == "deterministic":
            lines.append(f"  {label:<40} {measure.value['verdict']}")
        else:
            lines.append(f"  {label:<40} gate met — see posterior snapshot")

    # These three carry structured values. Printing the dict is faster to write
    # and slower to read, and this output exists to be read at a glance.
    for key, label, phrase in (
        ("charge", "Charge (spread of attention)", _phrase_charge),
        ("coupling", "Coupling to output", _phrase_coupling),
        ("aberration", "Aberration (output without Reveal)", _phrase_aberration),
    ):
        measure = measures[key]
        lines.append("")
        lines.append(
            f"{label}: {phrase(measure) if measure.ok else 'insufficient data'}"
        )
        if key == "coupling" and measure.ok:
            lines.append("  association only — no randomisation, so confounded")

    if result["underpowered"]:
        lines += ["", f"Underpowered: {', '.join(result['underpowered'])}"]
    return "\n".join(lines)


def export(rows: list[FlowRow], path: Path) -> str:
    """CSV always; parquet when the analysis extra is installed."""
    records = to_dicts(rows)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.suffix == ".parquet":
        try:
            import polars as pl
        except ImportError as exc:
            raise RuntimeError(
                "Parquet export needs the analysis extra: uv sync --extra analysis"
            ) from exc
        pl.DataFrame(records).write_parquet(path)
        return f"Wrote {len(records)} rows to {path}"

    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
    return f"Wrote {len(records)} rows to {path}"
