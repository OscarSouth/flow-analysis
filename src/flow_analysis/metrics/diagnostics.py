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

from .contracts import ABERRATION_SHARE, REGISTRY
from .contracts import by_key as contract_by_key
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

# Effect margins live in the contract registry (metrics/contracts.py) — one
# source for bars, windows and gates since the 2026-08-19 rework.


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


# --- the deterministic contracts ---------------------------------------------
# The statistical contracts (c1-c5, c9) are judged in the posterior layer;
# these three are facts, not estimates, so they are judged here — with the
# same four-way verdict vocabulary (minus `inconclusive`, which needs a
# posterior to exist). The registry in metrics/contracts.py is the source of
# windows, gates and bars.


def contract_dormancy_escalation(
    rows: Sequence[FlowRow], activities: Sequence[str]
) -> Measure:
    """c6 — some mode dormant ≥ 21 consecutive days (the R question)."""
    contract = contract_by_key("c6_dormancy_escalation")
    base = dormancy(rows, activities)
    if not base.ok:
        return Measure(contract.key, n=base.n, needs=contract.needs)
    escalated = sorted(
        name
        for name, state in (base.value or {}).items()
        if state.get("status") == "escalate"
    )
    return Measure(
        contract.key,
        value={
            "verdict": "supported" if escalated else "not supported",
            "escalated": escalated,
            "bar": contract.bar,
        },
        n=base.n,
        needs=contract.needs,
    )


def contract_harmonious_stagnation(
    rows: Sequence[FlowRow], production: dict[str, int]
) -> Measure:
    """c7 — adherence high while production flat (harmony as precursor)."""
    contract = contract_by_key("c7_harmonious_stagnation")
    base = adherence_without_production(
        rows, production, window=contract.window_days or 28
    )
    if not base.ok:
        return Measure(contract.key, n=base.n, needs=contract.needs)
    flagged = bool((base.value or {}).get("flagged"))
    return Measure(
        contract.key,
        value={
            "verdict": "supported" if flagged else "not supported",
            "adherence": (base.value or {}).get("adherence"),
            "output": (base.value or {}).get("output"),
            "bar": contract.bar,
        },
        n=base.n,
        needs=contract.needs,
    )


def contract_productive_aberration(
    rows: Sequence[FlowRow], production: dict[str, int]
) -> Measure:
    """c8 — a real share of producing days arrive without a completed Reveal."""
    contract = contract_by_key("c8_productive_aberration")
    observed = _observed(rows)
    days = _days(observed)
    span = set(days[-(contract.window_days or 60) :])
    windowed_production = {d: n for d, n in production.items() if d in span}
    producing_days = sum(1 for n in windowed_production.values() if n > 0)
    if producing_days < contract.needs:
        return Measure(contract.key, n=producing_days, needs=contract.needs)
    base = aberration([r for r in rows if r.day in span], windowed_production)
    share = (base.value or {}).get("share_of_producing_days") or 0.0
    return Measure(
        contract.key,
        value={
            "verdict": "supported" if share >= ABERRATION_SHARE else "not supported",
            "share_of_producing_days": share,
            "min_share": ABERRATION_SHARE,
            "days": (base.value or {}).get("days"),
            "bar": contract.bar,
        },
        n=producing_days,
        needs=contract.needs,
    )


def contract_gates(rows: Sequence[FlowRow]) -> dict[str, Measure]:
    """Gate-state rows for the posterior contracts.

    The verdicts live on `(:Fct:Posterior {measure: "contract:…"})`; these
    rows exist so `brief`'s newly-answerable machinery sees each contract's
    N approach its gate. `value` is a pointer once the gate is met, `None`
    (a refusal) before it — never a second verdict computation.
    """
    observed = _observed(rows)
    days = _days(observed)
    era_days = len({r.day for r in rows})
    out: dict[str, Measure] = {}
    for contract in REGISTRY:
        if contract.kind != "posterior":
            continue
        n = era_days if contract.needs_unit == "flow_era_days" else len(days)
        met = n >= contract.needs
        value = {"kind": "posterior", "see": contract.measure} if met else None
        out[contract.key] = Measure(
            contract.key, value=value, n=n, needs=contract.needs
        )
    return out


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
        "c6_dormancy_escalation": contract_dormancy_escalation(rows, activities),
        "c7_harmonious_stagnation": contract_harmonious_stagnation(rows, production),
        "c8_productive_aberration": contract_productive_aberration(rows, production),
    }
    measures.update(contract_gates(rows))
    return {
        "days": len(_days(_observed(rows))),
        "measures": measures,
        "underpowered": [name for name, m in measures.items() if not m.ok],
    }
