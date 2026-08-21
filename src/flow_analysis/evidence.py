"""The evidence pack: everything a review needs, and nothing it should invent.

`flow evidence --window 28` emits a compact brief that a prepared prompt reads.
The split is deliberate — **deterministic work happens here, in Python, and
judgement happens in the prompt**. Nothing downstream should be recomputing a
rate or eyeballing a trend from raw rows.

Two things the pack does that a bare metrics dump would not:

1. It evaluates the diagnostic table in `docs/06-diagnostics.md` and reports
   which rows *fire*, with the numbers that fired them. A pattern is not a
   verdict, but naming the CSF mode and the component at fault is the whole
   point of that table — "transform T" and "transform R" are opposite actions.
2. It states its own adequacy. Every section carries N and the threshold it had
   to clear, so a review can never quietly conclude from four days.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .metrics import diagnostics as dx
from .metrics.contracts import PERSISTENCE_DAYS, REGISTRY, Contract
from .metrics.grid import (
    ABANDONED,
    COMPLETED,
    NEVER_APPEARED,
    NEVER_STARTED,
    FlowRow,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .config import Config

# A pattern must clear this margin between the two modes it compares before it
# fires. Two rates differing by a couple of points is noise at this sample size,
# and a diagnostic that fires on noise prescribes a transformation on noise.
MARGIN = 0.30

# And the window must be at least this long, matching the rate gate elsewhere.
MIN_DAYS_PATTERN = dx.MIN_DAYS_RATE


@dataclass(frozen=True)
class Pattern:
    """One row of the diagnostic table, in computable form.

    `high` completes far more often than `low`. Where `high` is None the row is
    about a single channel simply being missed.
    """

    key: str
    high: str | None
    low: str
    imbalance: str
    csf_mode: str
    at_fault: str
    prescription: str


# Rows 1-5 of the table in docs/06-diagnostics.md, in order. The remaining rows
# (dormancy, adherence-without-production, aberration) are full measures in
# diagnostics.py and arrive through `run_all`.
PATTERNS: tuple[Pattern, ...] = (
    Pattern(
        key="ideas_without_execution",
        high="Express",
        low="Train",
        imbalance="ideas, none executable",
        csf_mode="generative uninspiration",
        at_fault="T",
        prescription="do the boring drills",
    ),
    Pattern(
        key="correct_and_dead",
        high="Train",
        low="Express",
        imbalance="correct and dead",
        csf_mode="conceptual uninspiration",
        at_fault="R",
        prescription="new material, not more practice",
    ),
    Pattern(
        key="perpetual_student",
        high="Absorb",
        low="Reveal",
        imbalance="perpetual student",
        csf_mode="generative uninspiration on Reveal",
        at_fault="T",
        prescription="ship something unfinished",
    ),
    Pattern(
        key="well_running_dry",
        high="Reveal",
        low="Absorb",
        imbalance="well running dry",
        csf_mode="approaching conceptual uninspiration",
        at_fault="R/E",
        prescription="stop producing, refill",
    ),
    Pattern(
        key="write_missed",
        high=None,
        low="Write",
        imbalance="reactive; ideas don't survive the day",
        csf_mode="traversal degradation across all modes",
        at_fault="T",
        prescription="offload to text",
    ),
)


def window_rows(rows: Sequence[FlowRow], window: int) -> list[FlowRow]:
    """The last `window` flow days.

    Days, not rows: a day with a failed refill still occupies a day, so counting
    rows would quietly stretch the window across the gap.
    """
    days = sorted({r.day for r in rows})
    keep = set(days[-window:])
    return [r for r in rows if r.day in keep]


def rates(
    rows: Sequence[FlowRow], activities: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Per-mode outcome counts and completion rate over whatever rows are given."""
    observed = [r for r in rows if r.outcome != NEVER_APPEARED]
    by_activity: dict[str, list[FlowRow]] = defaultdict(list)
    for row in observed:
        by_activity[row.activity].append(row)

    out: dict[str, dict[str, Any]] = {}
    for activity in activities:
        mine = by_activity.get(activity, [])
        counts = Counter(r.outcome for r in mine)
        latencies = [r.minutes_to_start for r in mine if r.minutes_to_start is not None]
        out[activity] = {
            "days": len(mine),
            "completed": counts[COMPLETED],
            "never_started": counts[NEVER_STARTED],
            "abandoned": counts[ABANDONED],
            "rate": round(counts[COMPLETED] / len(mine), 3) if mine else None,
            "median_minutes_to_start": _median(latencies),
        }
    return out


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 1)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 1)


def firings(
    rate_table: dict[str, dict[str, Any]], n_days: int, activities: Sequence[str]
) -> dict[str, Any]:
    """Which rows of the diagnostic table fire, and on what numbers.

    Refuses wholesale below the rate gate rather than firing weakly — a
    prescription to transform R deserves more than a fortnight of evidence.
    """
    if n_days < MIN_DAYS_PATTERN:
        return {
            "ok": False,
            "n": n_days,
            "needs": MIN_DAYS_PATTERN,
            "fired": [],
        }

    known = set(activities)
    fired = []
    for pattern in PATTERNS:
        if pattern.low not in known or (pattern.high and pattern.high not in known):
            continue  # the activities were renamed; the row no longer applies
        low = rate_table[pattern.low]["rate"]
        if low is None:
            continue

        if pattern.high is None:
            # Single-channel row: Write is missed more often than it is kept.
            if low >= 0.5:
                continue
            evidence = f"{pattern.low} completed {low:.0%} of days"
            gap = None
        else:
            high = rate_table[pattern.high]["rate"]
            if high is None or high - low < MARGIN:
                continue
            gap = round(high - low, 3)
            evidence = (
                f"{pattern.high} {high:.0%} vs {pattern.low} {low:.0%}"
                f" — a {gap:.0%} gap"
            )

        fired.append(
            {
                "key": pattern.key,
                "imbalance": pattern.imbalance,
                "csf_mode": pattern.csf_mode,
                "at_fault": pattern.at_fault,
                "prescription": pattern.prescription,
                "evidence": evidence,
                "gap": gap,
            }
        )
    return {"ok": True, "n": n_days, "needs": MIN_DAYS_PATTERN, "fired": fired}


def build(
    cfg: Config,
    rows: Sequence[FlowRow],
    production: dict[str, int],
    signal_rows: Sequence[dict[str, Any]],
    posterior_rows: Sequence[dict[str, Any]] = (),
    window: int = 28,
    contract_history: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """The pack. Windowed where a window makes sense, full-history where it does not."""
    activities = list(cfg.activities)
    windowed = window_rows(rows, window)
    days = sorted({r.day for r in windowed})
    prior = window_rows([r for r in rows if r.day not in set(days)], window)

    rate_table = rates(windowed, activities)
    prior_table = rates(prior, activities) if prior else {}

    # Diagnostics run on the whole history: dormancy and coupling are about the
    # long shape, and re-gating them to a 28-day window would throw away the
    # only evidence that clears their thresholds.
    diag = dx.run_all(cfg, rows, production)

    # Reception is deliberately *not* windowed: it answers to work shipped long
    # ago, so a 28-day slice of it would be meaningless.
    from .metrics import reception as reception_mod

    output = sum(production.get(day, 0) for day in days)
    completions = sum(1 for r in windowed if r.outcome == COMPLETED)

    return {
        "window": window,
        "span": [days[0], days[-1]] if days else None,
        "n_days_window": len(days),
        "n_days_total": diag["days"],
        "activities": activities,
        "rates": rate_table,
        "prior_rates": prior_table,
        "patterns": firings(rate_table, len(days), activities),
        "diagnostics": diag,
        "output_in_window": output,
        "completions_in_window": completions,
        "reception": reception_mod.summarise(cfg, signal_rows),
        "posteriors": posterior_rows,
        "contract_history": contract_history,
        "underpowered": diag["underpowered"],
    }


# --- rendering --------------------------------------------------------------


def _standing_run(history: Sequence[dict[str, Any]], measure: str) -> int:
    """Consecutive latest snapshot days carrying the same verdict.

    The anti-flapping input: a rolling verdict is *standing* only once the
    run reaches PERSISTENCE_DAYS. Computed from posterior history at render
    time, never stored.
    """
    mine = sorted(
        (r for r in history if r.get("measure") == measure and r.get("verdict")),
        key=lambda r: r["day"],
        reverse=True,
    )
    if not mine:
        return 0
    latest = mine[0]["verdict"]
    run = 0
    for row in mine:
        if row["verdict"] != latest:
            break
        run += 1
    return run


def _contract_lines(measures: dict[str, dx.Measure], pack: dict[str, Any]) -> list[str]:
    """The contracts, grouped by the CSF component each one implicates.

    A supported failure-positive contract is a diagnosis with a Wiggins
    prescription attached; the healthy state is the claim staying refuted.
    Prescription language appears only once a verdict is standing.
    """
    posterior_by_measure = {r.get("measure"): r for r in pack.get("posteriors") or []}
    history = pack.get("contract_history") or []

    lines = ["", "## The contracts — the registry, judged", ""]
    by_component: dict[str, list[Contract]] = {}
    for contract in REGISTRY:
        by_component.setdefault(contract.component, []).append(contract)

    for component in sorted(by_component):
        lines.append(f"### {component}")
        lines.append("")
        for contract in by_component[component]:
            verdict, detail = _contract_state(contract, measures, posterior_by_measure)
            healthy = verdict == contract.healthy_verdict
            run = _standing_run(history, contract.measure)
            standing = (
                verdict in {"supported", "not supported"} and run >= PERSISTENCE_DAYS
            )
            marker = "healthy" if healthy else "attention"
            line = f"- **{contract.title}** ({contract.csf_mode}): **{verdict}**"
            if verdict != "not testable yet":
                line += f" [{marker}]"
                if standing:
                    line += f" — standing ({run} consecutive days)"
                elif run:
                    line += f" — {run} day(s) at this verdict, standing at "
                    line += f"{PERSISTENCE_DAYS}"
            if detail:
                line += f" — {detail}"
            lines.append(line)
            if standing and not healthy:
                lines.append(f"  - prescription: {contract.prescription}")
        lines.append("")
    return lines[:-1]


def _contract_state(
    contract: Contract,
    measures: dict[str, dx.Measure],
    posterior_by_measure: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    """One contract's current verdict and a short detail string."""
    if contract.kind == "posterior":
        row = posterior_by_measure.get(contract.measure)
        if row is None:
            measure = measures.get(contract.key)
            gate = (
                f"N={measure.n}, needs {measure.needs}"
                if measure is not None
                else "no snapshot"
            )
            return "not testable yet", gate
        probability = row.get("probability")
        prob = f"P={probability:.2f}" if probability is not None else ""
        return str(row.get("verdict") or "not testable yet"), (
            f"{prob} against {contract.bar}" if prob else contract.bar
        )
    measure = measures.get(contract.key)
    if measure is None or not measure.ok:
        gate = (
            f"N={measure.n}, needs {measure.needs}"
            if measure is not None
            else "missing"
        )
        return "not testable yet", gate
    value = measure.value or {}
    return str(value.get("verdict") or "not testable yet"), contract.bar


def _short(measure: dx.Measure, bare: bool = False) -> str:
    text = f"insufficient data — N={measure.n}, needs {measure.needs}"
    return text if bare else f"Not evaluated: {text}."


def _delta(current: float | None, previous: float | None) -> str:
    if current is None or previous is None:
        return "—"
    change = current - previous
    if abs(change) < 0.05:
        return "flat"
    return f"{change:+.0%}"


def render(pack: dict[str, Any]) -> str:
    """Markdown, compact, meant to be read by a prepared prompt."""
    lines: list[str] = []
    span = pack["span"]
    lines.append(f"# Flow evidence — {pack['window']}-day window")
    if span:
        lines.append(
            f"{span[0]} .. {span[1]}  ({pack['n_days_window']} days in window, "
            f"{pack['n_days_total']} total observed)"
        )
    else:
        lines.append("No flow days observed yet.")
        return "\n".join(lines)

    lines += [
        "",
        "## Per mode",
        "",
        "| mode | rate | vs prior window | completed | never started | abandoned | "
        "median mins to start |",
        "|---|---|---|---|---|---|---|",
    ]
    for activity in pack["activities"]:
        stat = pack["rates"][activity]
        prior = pack["prior_rates"].get(activity, {}).get("rate")
        rate = "—" if stat["rate"] is None else f"{stat['rate']:.0%}"
        latency = (
            "—"
            if stat["median_minutes_to_start"] is None
            else stat["median_minutes_to_start"]
        )
        lines.append(
            f"| {activity} | {rate} | {_delta(stat['rate'], prior)} | "
            f"{stat['completed']} "
            f"| {stat['never_started']} | {stat['abandoned']} | {latency} |"
        )

    lines += ["", "## Diagnostic table — which rows fire", ""]
    patterns = pack["patterns"]
    if not patterns["ok"]:
        lines.append(
            f"Not evaluated: {patterns['n']} of {patterns['needs']} days needed. "
            "A prescription to transform R or T deserves more than this."
        )
    elif not patterns["fired"]:
        lines.append(
            f"No row fires: no compared pair differs by the {MARGIN:.0%} margin a "
            "prescription requires, and Write is kept more often than it is missed. "
            "The five are within a normal spread of each other."
        )
    else:
        lines += [
            "| imbalance | CSF mode | at fault | prescription | evidence |",
            "|---|---|---|---|---|",
        ]
        for fire in patterns["fired"]:
            lines.append(
                f"| {fire['imbalance']} | {fire['csf_mode']} | **{fire['at_fault']}** "
                f"| {fire['prescription']} | {fire['evidence']} |"
            )

    measures = pack["diagnostics"]["measures"]
    lines += ["", "## Failure kind — allocation wants time, capacity wants drills", ""]
    alloc = measures["allocation_vs_capacity"]
    if not alloc.ok:
        lines.append(_short(alloc))
    else:
        lines += [
            "| mode | dominant | never started | abandoned |",
            "|---|---|---|---|",
        ]
        for activity, stat in alloc.value.items():
            lines.append(
                f"| {activity} | {stat['dominant'] or '—'} | {stat['allocation']} "
                f"| {stat['capacity']} |"
            )

    lines += ["", "## Dormancy", ""]
    dorm = measures["dormancy"]
    if not dorm.ok:
        lines.append(_short(dorm))
    else:
        closed = {a: v for a, v in dorm.value.items() if v["status"] != "open"}
        if closed:
            for activity, stat in closed.items():
                lines.append(
                    f"- **{activity}** closed {stat['current']} days — "
                    f"`{stat['status']}`"
                )
        else:
            longest = max(dorm.value.items(), key=lambda kv: kv[1]["longest"])
            lines.append(
                f"- Nothing closed right now. Longest run so far: {longest[0]} at "
                f"{longest[1]['longest']} days."
            )

    lines += ["", "## Other measures", ""]
    charge = measures["charge"]
    lines.append(
        "- **Charge** (spread of attention across the five): "
        + (
            f"{charge.value:.2f} — 0 is even, 1 is one mode thriving while another is "
            f"dead"
            if charge.ok
            else _short(charge, bare=True)
        )
    )
    coup = measures["coupling"]
    if coup.ok and coup.value:
        best = coup.value
        when = "the same day" if best["lag"] == 0 else f"{best['lag']} days later"
        lines.append(
            f"- **Coupling to output**: strongest at lag {best['lag']}d, "
            f"r={best['r']:+.2f} "
            f"over {best['n']} pairs (adherence today, output {when}). "
            "Confounded — see caveats."
        )
    else:
        lines.append(f"- **Coupling to output**: {_short(coup, bare=True)}")
    awp = measures["adherence_without_production"]
    if awp.ok:
        lines.append(
            f"- **Adherence without production**: adherence "
            f"{awp.value['adherence']:.0%}, "
            f"output {awp.value['output']} — "
            + (
                "**flagged**: the board reads as success while nothing comes of it"
                if awp.value["flagged"]
                else "not flagged"
            )
        )
    else:
        lines.append(f"- **Adherence without production**: {_short(awp, bare=True)}")
    ab = measures["aberration"]
    if ab.ok:
        share = ab.value["share_of_producing_days"]
        if ab.value["days"] == 0:
            lines.append(
                f"- **Productive aberration**: none — output never arrived on a day "
                f"{ab.value['channel']} went uncompleted"
            )
        else:
            lines.append(
                f"- **Productive aberration**: {ab.value['days']} day(s) produced "
                f"output "
                f"without completing {ab.value['channel']}"
                + (f" ({share:.0%} of producing days)" if share is not None else "")
                + " — work outside R that was valued anyway, and the trigger for "
                "asking whether R itself is wrong"
            )
    else:
        lines.append(f"- **Productive aberration**: {_short(ab, bare=True)}")

    lines += _contract_lines(measures, pack)

    lines += [
        "",
        "## Output",
        "",
        f"- Forum posts in window: {pack['output_in_window']}",
        f"- Card completions in window: {pack['completions_in_window']}",
    ]

    reception = pack.get("reception")
    if reception:
        lines += ["", "## Reception — what came back", ""]

        era = reception.get("flow_era")
        if era:
            lines += [
                f"**Since flow began ({reception['epoch']})** — everything else on "
                "this page is inherited baseline, earned before the practice existed "
                "and not attributable to it.",
                "",
                "| signal | since flow | baseline before |",
                "|---|---|---|",
            ]
            labels = {
                "youtube_subscribers": "YouTube subscribers, net",
                "youtube_views": "YouTube views",
                "youtube_minutes": "YouTube minutes watched",
                "github_stars": "GitHub stars",
                "forum_outsiders": "Forum posts by outsiders",
            }
            for metric, label in labels.items():
                stat = era.get(metric)
                if stat is None:
                    continue
                lines.append(
                    f"| {label} | **{stat['since']:+}** | {stat['baseline']:,} |"
                )
            lines += ["", "### Inherited baseline, for context only", ""]

        counts = reception["counters"]
        if counts:
            lines.append(
                "- GitHub: "
                + ", ".join(f"{m} **{c['value']}**" for m, c in sorted(counts.items()))
            )
        stars = reception["stars"]
        if stars["total"]:
            recent = list(stars["by_year"].items())[-3:]
            lines.append(
                f"- Stars: {stars['total']} total since {stars['first']}, peak "
                f"{stars['peak_year']}; recent years "
                + ", ".join(f"{y} {n}" for y, n in recent)
            )
        views = reception["views_window"]
        if views:
            coverage = reception["views_coverage"]
            note = (
                f" (day-level coverage {coverage['observed']}/{coverage['of']})"
                if coverage["fraction"] < 1.0
                else ""
            )
            lines.append(
                f"- Traffic, last {views['window_days']}d: {views['count']} views "
                f"from {views['uniques']} unique visitors{note}"
            )
        clones = reception["clones_window"]
        if clones:
            lines.append(
                f"- Clones, last {clones['window_days']}d: {clones['count']} from "
                f"{clones['uniques']} uniques — **infrastructure, not attention**; "
                "mirrors and CI dominate this and it must not be read as reach"
            )
        if reception["referrers"]:
            lines.append(
                "- Referrers: "
                + ", ".join(
                    f"{r['referrer']} ({r['count']})"
                    for r in reception["referrers"][:5]
                )
            )
        lines.append(
            f"- Forum posts by outsiders: {reception['external_posts']['total']}"
        )

        trend = reception["trend"]
        lines += [
            "",
            "**Read these as levels, not rates.** "
            + (
                "The observed span now supports a trend claim."
                if trend["open"]
                else f"A trend is not supportable yet — {trend['observed_days']} of "
                f"{trend['needs']} days observed. The totals above are facts; a "
                "rate is not yet one."
            ),
            "",
            "Reception is **never** coupled to recent practice, at any lag. It answers "
            "to promotion and to work shipped long ago, so the governing question is "
            "cumulative reward on sustained commitment — not the impact of a given "
            "week.",
        ]

    lines += [
        "",
        "## Adequacy",
        "",
    ]
    if pack["underpowered"]:
        lines.append(
            "Still underpowered, and must not be concluded from: "
            + ", ".join(pack["underpowered"])
        )
    else:
        lines.append("Every measure has cleared its threshold.")

    lines += [
        "",
        "## Standing caveats",
        "",
        "- Nothing here is causal. There is no randomisation by design, so a good "
        "day plausibly raises both completions and output.",
        "- Hypotheses are pre-registered in `docs/06-diagnostics.md`. A pattern "
        "noticed in this pack is a candidate for next period, not a finding.",
        "- A missed day is data, not debt. There is no backlog to make up.",
    ]
    return "\n".join(lines)
