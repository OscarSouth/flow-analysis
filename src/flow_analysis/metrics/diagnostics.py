"""Computable form of the diagnostic table in docs/06-diagnostics.md.

Every measure here declares the minimum N it needs and returns `None` — with the
shortfall stated — rather than a number it cannot support. Five binary-ish
outcomes a day is thin, and a confident figure drawn from nine days is worse than
no figure. "Not yet" is a result.

Nothing here is causal. There is no randomisation by design, so any coupling
between practice and output is confounded.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from .grid import ABANDONED, COMPLETED, NEVER_APPEARED, NEVER_STARTED, FlowRow

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ..config import Config

# Minimum observations before each measure will speak. See docs/06-diagnostics.md.
MIN_DAYS_RATE = 14
MIN_DAYS_WEEKDAY = 28
MIN_DAYS_CHARGE = 28
MIN_DAYS_COUPLING = 60
MIN_OBS_LATENCY = 20

DORMANCY_FLAG = 7
DORMANCY_ESCALATE = 21

# Minimum effect sizes for the three pre-registered hypotheses. Without these a
# hypothesis is "supported" the moment its leader is ahead by a single count or
# a single minute, which is not a result — it is a coin landing. Fixed here, in
# advance, for the same reason the hypotheses themselves were: choosing the
# threshold after seeing the gap is how anything gets confirmed.
H1_LEAD_SHARE = 0.20  # leader must beat the runner-up by 20% of its own count
H2_LEAD_SHARE = 0.20  # leader's median must beat the runner-up's by 20%
H3_MIN_GAP = 0.10  # 10 percentage points of completion rate


@dataclass
class Measure:
    """A result, or an honest refusal."""

    name: str
    value: Any = None
    n: int = 0
    needs: int = 0
    detail: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        """Whether this measure has a value, or is an honest refusal."""
        return self.value is not None

    def __str__(self) -> str:
        """The value, or what it is still short of. Never a bare number."""
        if self.ok:
            return f"{self.name}: {self.value}"
        return f"{self.name}: insufficient data — N={self.n}, needs {self.needs}"


def _days(rows: Sequence[FlowRow]) -> list[str]:
    """The distinct flow days present, in order. The N most gates count."""
    return sorted({r.day for r in rows})


def _observed(rows: Iterable[FlowRow]) -> list[FlowRow]:
    """Rows where the card actually appeared.

    `never_appeared` means the refill rule did not fire — a system fault, not a
    behavioural one, and it would otherwise be silently counted as a miss.
    """
    return [r for r in rows if r.outcome != NEVER_APPEARED]


# --- allocation vs capacity -------------------------------------------------


def allocation_vs_capacity(
    rows: Sequence[FlowRow], activities: Sequence[str]
) -> Measure:
    """Split each activity's failures into never-attempted vs attempted-and-lost.

    Wiggins' generative uninspiration covers both. The remedies are opposite:
    allocation failure wants protected time, capacity failure wants drills.
    """
    observed = _observed(rows)
    n = len(_days(observed))
    if n < MIN_DAYS_RATE:
        return Measure("allocation_vs_capacity", n=n, needs=MIN_DAYS_RATE)

    out: dict[str, dict[str, Any]] = {}
    for activity in activities:
        mine = [r for r in observed if r.activity == activity]
        if not mine:
            continue
        allocation = sum(1 for r in mine if r.outcome == NEVER_STARTED)
        capacity = sum(1 for r in mine if r.outcome == ABANDONED)
        failures = allocation + capacity
        out[activity] = {
            "allocation": allocation,
            "capacity": capacity,
            "failures": failures,
            # Which failure dominates, and so which prescription applies.
            "dominant": None
            if failures == 0
            else ("allocation" if allocation > capacity else "capacity"),
            "allocation_share": None
            if failures == 0
            else round(allocation / failures, 3),
        }
    return Measure("allocation_vs_capacity", value=out, n=n, needs=MIN_DAYS_RATE)


# --- dormancy ---------------------------------------------------------------


def dormancy(rows: Sequence[FlowRow], activities: Sequence[str]) -> Measure:
    """Longest and current run of consecutive days a channel was never attempted.

    Not uninspiration: nothing was attempted, so nothing failed to be reached.
    Dormancy masquerades as generative uninspiration and attracts the wrong fix.
    """
    observed = _observed(rows)
    days = _days(observed)
    if not days:
        return Measure("dormancy", n=0, needs=1)

    by_key = {(r.day, r.activity): r for r in observed}
    out: dict[str, dict[str, Any]] = {}
    for activity in activities:
        longest = current = 0
        for day in days:
            row = by_key.get((day, activity))
            if row is not None and row.outcome == NEVER_STARTED:
                current += 1
                longest = max(longest, current)
            else:
                current = 0
        status = "open"
        if current >= DORMANCY_ESCALATE:
            status = "escalate"  # three weeks closed is evidence about R
        elif current >= DORMANCY_FLAG:
            status = "dormant"
        out[activity] = {"current": current, "longest": longest, "status": status}
    return Measure("dormancy", value=out, n=len(days), needs=1)


# --- charge -----------------------------------------------------------------


def charge(
    rows: Sequence[FlowRow], activities: Sequence[str], window: int = 14
) -> Measure:
    """Divergence between what is valid (all five) and what actually completes.

    Single-agent reading of the harmonious/charged distinction. Zero charge means
    you complete everything the rules admit — comfortable, and the precursor to
    stagnation. High charge means persistent tension between rules and practice.
    """
    observed = _observed(rows)
    days = _days(observed)
    if len(days) < MIN_DAYS_CHARGE:
        return Measure("charge", n=len(days), needs=MIN_DAYS_CHARGE)

    by_day: dict[str, set[str]] = defaultdict(set)
    for row in observed:
        if row.outcome == COMPLETED:
            by_day[row.day].add(row.activity)

    # Set membership over a fortnight is too coarse — almost every mode gets
    # touched at least once, so it reads 0 forever. What matters is how *evenly*
    # attention is spread: charge is the normalised spread of per-mode completion
    # rates. 0 means all five run at the same rate (harmonious, and the precursor
    # to stagnation); approaching 1 means one mode is thriving while another is
    # effectively dead.
    series = []
    for i in range(window - 1, len(days)):
        span = days[i - window + 1 : i + 1]
        rates = [
            sum(1 for d in span if activity in by_day[d]) / len(span)
            for activity in activities
        ]
        top = max(rates)
        value = 0.0 if top == 0 else (top - min(rates)) / top
        series.append({"day": days[i], "charge": round(value, 3)})

    latest = series[-1]["charge"] if series else None
    return Measure(
        "charge",
        value=latest,
        n=len(days),
        needs=MIN_DAYS_CHARGE,
        detail={"series": series, "window": window},
    )


# --- pre-registered hypotheses ---------------------------------------------


def _verdict(direction_holds: bool, big_enough: bool) -> str:
    """Three outcomes, not two.

    A hypothesis whose direction holds by a margin too small to mean anything is
    neither supported nor refuted — collapsing that case into "supported" is
    exactly the flattering-pattern failure the discipline exists to prevent.
    """
    if not direction_holds:
        return "not supported"
    return "supported" if big_enough else "inconclusive"


def preregistered(
    rows: Sequence[FlowRow], activities: Sequence[str]
) -> dict[str, Measure]:
    """The three hypotheses committed to publicly in article 05.

    Tested as published — not reworded to whatever the data happens to support.
    """
    observed = _observed(rows)
    days = _days(observed)
    results: dict[str, Measure] = {}

    # H1 — Train is the most frequent never_started.
    if len(days) < MIN_DAYS_RATE:
        results["h1_train_most_never_started"] = Measure(
            "h1_train_most_never_started", n=len(days), needs=MIN_DAYS_RATE
        )
    else:
        counts = Counter(r.activity for r in observed if r.outcome == NEVER_STARTED)
        ranked = counts.most_common()
        top = ranked[0][0] if ranked else None
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        lead = (
            (ranked[0][1] - runner_up) / ranked[0][1]
            if ranked and ranked[0][1]
            else 0.0
        )
        results["h1_train_most_never_started"] = Measure(
            "h1_train_most_never_started",
            value={
                "verdict": _verdict(top == "Train", lead >= H1_LEAD_SHARE),
                "leader": top,
                "lead_over_runner_up": round(lead, 3),
                "min_lead": H1_LEAD_SHARE,
                "counts": dict(counts),
            },
            n=len(days),
            needs=MIN_DAYS_RATE,
        )

    # H2 — Express carries the longest median minutes_to_start.
    medians: dict[str, float] = {}
    thin: list[str] = []
    for activity in activities:
        lat = sorted(
            r.minutes_to_start
            for r in observed
            if r.activity == activity and r.minutes_to_start is not None
        )
        if len(lat) < MIN_OBS_LATENCY:
            thin.append(activity)
            continue
        medians[activity] = round(lat[len(lat) // 2], 1)
    if thin or not medians:
        results["h2_express_slowest_to_start"] = Measure(
            "h2_express_slowest_to_start",
            n=min((len(medians), len(activities))),
            needs=MIN_OBS_LATENCY,
            detail={"underpowered_activities": thin},
        )
    else:
        # Own names rather than reusing H1's `ranked`/`runner_up`: these are
        # medians in minutes, those were completion counts.
        ranked_medians = sorted(medians.items(), key=lambda kv: kv[1], reverse=True)
        leader, top_median = ranked_medians[0]
        median_runner_up = ranked_medians[1][1] if len(ranked_medians) > 1 else 0.0
        lead = (top_median - median_runner_up) / top_median if top_median else 0.0
        results["h2_express_slowest_to_start"] = Measure(
            "h2_express_slowest_to_start",
            value={
                "verdict": _verdict(leader == "Express", lead >= H2_LEAD_SHARE),
                "leader": leader,
                "lead_over_runner_up": round(lead, 3),
                "min_lead": H2_LEAD_SHARE,
                "medians": medians,
            },
            n=len(observed),
            needs=MIN_OBS_LATENCY,
        )

    # H3 — days Write is missed show lower completion across the other four.
    if len(days) < MIN_DAYS_RATE:
        results["h3_write_carries_the_others"] = Measure(
            "h3_write_carries_the_others", n=len(days), needs=MIN_DAYS_RATE
        )
    else:
        by_day: dict[str, dict[str, str]] = defaultdict(dict)
        for row in observed:
            by_day[row.day][row.activity] = row.outcome
        others = [a for a in activities if a != "Write"]
        did: list[float] = []
        missed: list[float] = []
        for outcomes in by_day.values():
            if "Write" not in outcomes:
                continue
            rate = sum(1 for a in others if outcomes.get(a) == COMPLETED) / len(others)
            (did if outcomes["Write"] == COMPLETED else missed).append(rate)
        if not missed or not did:
            results["h3_write_carries_the_others"] = Measure(
                "h3_write_carries_the_others",
                n=len(days),
                needs=MIN_DAYS_RATE,
                detail={
                    "reason": "no contrast — Write was never missed, or never done"
                },
            )
        else:
            with_w, without_w = sum(did) / len(did), sum(missed) / len(missed)
            results["h3_write_carries_the_others"] = Measure(
                "h3_write_carries_the_others",
                value={
                    "verdict": _verdict(
                        with_w > without_w, abs(with_w - without_w) >= H3_MIN_GAP
                    ),
                    "with_write": round(with_w, 3),
                    "without_write": round(without_w, 3),
                    "gap": round(with_w - without_w, 3),
                    "min_gap": H3_MIN_GAP,
                    "n_missed_days": len(missed),
                },
                n=len(days),
                needs=MIN_DAYS_RATE,
            )
    return results


# --- coupling to production -------------------------------------------------


def coupling(
    rows: Sequence[FlowRow],
    production: dict[str, int],
    max_lag: int = 14,
) -> Measure:
    """Correlate daily completion count against production at lags 0..max_lag.

    `production` maps flow-day ISO string to a count (e.g. forum posts).

    Confounded by construction: a good day plausibly raises both. This measures
    association and must never be reported as cause.
    """
    observed = _observed(rows)
    days = _days(observed)
    if len(days) < MIN_DAYS_COUPLING:
        return Measure("coupling", n=len(days), needs=MIN_DAYS_COUPLING)

    completed = Counter(r.day for r in observed if r.outcome == COMPLETED)
    adherence = [completed.get(d, 0) for d in days]

    span = set(days)
    out = []
    for lag in range(max_lag + 1):
        xs, ys = [], []
        for i, day in enumerate(days):
            target = (date.fromisoformat(day) + timedelta(days=lag)).isoformat()
            # Only pair days whose lagged partner is inside the observed range,
            # or the tail silently compares real adherence against assumed zeros.
            if target not in span:
                continue
            xs.append(adherence[i])
            ys.append(production.get(target, 0))
        r = _pearson(xs, ys)
        if r is not None:
            out.append({"lag": lag, "r": round(r, 3), "n": len(xs)})

    best = max(out, key=lambda o: abs(o["r"])) if out else None
    return Measure(
        "coupling",
        value=best,
        n=len(days),
        needs=MIN_DAYS_COUPLING,
        detail={"by_lag": out, "confounded": True},
    )


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    # strict=True is free here — the caller appends to both in lockstep — and a
    # future mismatch would otherwise correlate a truncated pair in silence.
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx: float = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy: float = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


# --- adherence without production, and aberration ---------------------------


def adherence_without_production(
    rows: Sequence[FlowRow], production: dict[str, int], window: int = 28
) -> Measure:
    """High adherence, flat output — the harmonious-but-stagnant case.

    Reads as total success on the board. Invisible without an external measure,
    which is the whole argument for ingesting the forum.
    """
    observed = _observed(rows)
    days = _days(observed)
    if len(days) < window:
        return Measure("adherence_without_production", n=len(days), needs=window)

    span = days[-window:]
    completed = Counter(r.day for r in observed if r.outcome == COMPLETED)
    n_activities = len({r.activity for r in observed}) or 1
    adherence = sum(completed.get(d, 0) for d in span) / (len(span) * n_activities)
    output = sum(production.get(d, 0) for d in span)

    return Measure(
        "adherence_without_production",
        value={
            "adherence": round(adherence, 3),
            "output": output,
            # High practice, no artefacts: the quiet precursor to stagnation.
            "flagged": adherence >= 0.7 and output == 0,
        },
        n=len(days),
        needs=window,
        detail={"window": window},
    )


def aberration(
    rows: Sequence[FlowRow], production: dict[str, int], channel: str = "Reveal"
) -> Measure:
    """Production arriving without the channel that is supposed to produce it.

    R says Reveal is how work reaches the world. Output on a day Reveal was not
    completed is, literally, valued work from outside the rules — the empirical
    signature of productive aberration.

    Requiring zero completions of *any* kind would be far too strict to ever
    fire: with five cards a day, days with no completions at all are rare, so the
    measure would read zero forever and tell you nothing.
    """
    observed = _observed(rows)
    days = _days(observed)
    if not days:
        return Measure("aberration", n=0, needs=1)

    done = {(r.day, r.activity) for r in observed if r.outcome == COMPLETED}
    total = Counter(r.day for r in observed if r.outcome == COMPLETED)

    events = [
        {
            "day": d,
            "output": production.get(d, 0),
            "channel_completed": False,
            "other_completions": total.get(d, 0),
        }
        for d in days
        if production.get(d, 0) > 0 and (d, channel) not in done
    ]
    produced_days = sum(1 for d in days if production.get(d, 0) > 0)
    return Measure(
        "aberration",
        value={
            "days": len(events),
            "share_of_producing_days": None
            if produced_days == 0
            else round(len(events) / produced_days, 3),
            "channel": channel,
            "events": events[-10:],
        },
        n=len(days),
        needs=1,
    )


# --- assembly ---------------------------------------------------------------


def run_all(
    cfg: Config, rows: Sequence[FlowRow], production: dict[str, int] | None = None
) -> dict[str, Any]:
    """Every diagnostic, each declaring its own adequacy."""
    production = production or {}
    activities = list(cfg.activities)
    measures = {
        "allocation_vs_capacity": allocation_vs_capacity(rows, activities),
        "dormancy": dormancy(rows, activities),
        "charge": charge(rows, activities),
        "coupling": coupling(rows, production),
        "adherence_without_production": adherence_without_production(rows, production),
        "aberration": aberration(rows, production),
    }
    measures.update(preregistered(rows, activities))
    return {
        "days": len(_days(_observed(rows))),
        "measures": measures,
        "underpowered": [name for name, m in measures.items() if not m.ok],
    }
