"""The contract registry — the practice's falsifiable claims, in one place.

Reworked 2026-08-19 from the three scaffolding hypotheses (H1–H3) that
launched the platform: each row of the diagnostic table in
`docs/06-diagnostics.md` becomes a formal, CSF-typed, rolling contract — a
failure-positive claim Oscar works to *disprove* through deliberate
practice. A `supported` verdict names the broken CSF component and carries
its Wiggins prescription; the healthy state is the claim staying refuted.
c9 is the one health-positive contract (the publication-cadence floor,
registered as H4), hence `healthy_verdict` is per-contract rather than a
convention.

Two subtleties are load-bearing:

- c1/c2's "some mode leads" is judged **per posterior draw** — within each
  draw the leader is found and tested against the margin — so the claim is
  "a persistent leader exists", not "the mode that happens to lead in the
  point estimate leads", which would be a selection effect.
- Rolling verdicts can flap. A contract is *standing* only when the same
  verdict has held for `PERSISTENCE_DAYS` consecutive snapshot days —
  computed from posterior history at render time, never stored.

This module is Layer B leaf vocabulary: importable by anything, imports
nothing but the standard library.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

# Consecutive snapshot days a verdict must hold before it is *standing* and
# prescription language is allowed. One week: a rolling window sliding one
# day rarely changes truth, so a week of agreement is cheap when real and
# effective against single-snapshot noise.
PERSISTENCE_DAYS = 7

# Shared bars. The 1.2 leader margin and 0.10/0.30 gaps carry over from the
# superseded hypotheses and the diagnostic table — pre-registered before any
# data existed, kept on the same reasoning.
LEAD_MARGIN = 1.2
GAP_WRITE = 0.10
GAP_PATTERN = 0.30
ABERRATION_SHARE = 0.25

CSF_COMPONENTS = frozenset({"R", "E", "T", "R/E", "allocation"})


@dataclass(frozen=True)
class Contract:
    """One falsifiable claim about the practice, typed to the CSF."""

    key: str  # measure key, e.g. "c1_allocation_failure"
    title: str  # short human label for surfaces
    claim: str  # the claim, plain words
    component: str  # CSF component implicated when supported
    csf_mode: str  # Wiggins failure mode (or cadence floor for c9)
    prescription: str  # what a standing supported verdict prescribes
    kind: str  # "posterior" | "deterministic"
    window_days: int | None  # trailing window; None = current-state
    needs: int  # N-gate; unit given in `needs_unit`
    needs_unit: str  # "days" | "producing_days" | "flow_era_days"
    bar: str  # the margin, human-readable
    healthy_verdict: str  # the verdict that means the practice is healthy

    @property
    def measure(self) -> str:
        """The posterior naming scheme for this contract."""
        return f"contract:{self.key}"


REGISTRY: tuple[Contract, ...] = (
    Contract(
        key="c1_allocation_failure",
        title="Allocation failure",
        claim="some mode's never-started rate persistently leads the others",
        component="allocation",
        csf_mode="generative uninspiration (allocation)",
        prescription="protect time and scheduling for the leading mode — "
        "not drills; nothing was attempted, so nothing failed to be reached",
        kind="posterior",
        window_days=28,
        needs=14,
        needs_unit="days",
        bar="P(per-draw leader ≥ 1.2 x runner-up) ≥ 0.90",
        healthy_verdict="not supported",
    ),
    Contract(
        key="c2_capacity_failure",
        title="Capacity failure",
        claim="some mode's abandoned-in-progress rate persistently leads",
        component="T",
        csf_mode="generative uninspiration (capacity)",
        prescription="transform T: the boring drills for the leading mode — "
        "traversal was attempted and did not arrive",
        kind="posterior",
        window_days=28,
        needs=14,
        needs_unit="days",
        bar="P(per-draw leader ≥ 1.2 x runner-up) ≥ 0.90",
        healthy_verdict="not supported",
    ),
    Contract(
        key="c3_correct_and_dead",
        title="Correct and dead",
        claim="Train completion exceeds Express by a wide gap",
        component="R",
        csf_mode="conceptual uninspiration",
        prescription="new material, not more practice — the space has "
        "stopped containing anything valued; reach is not the problem",
        kind="posterior",
        window_days=28,
        needs=14,
        needs_unit="days",
        bar="P(completion gap ≥ 0.30) ≥ 0.90",
        healthy_verdict="not supported",
    ),
    Contract(
        key="c4_well_running_dry",
        title="Well running dry",
        claim="Reveal completion exceeds Absorb by a wide gap",
        component="R/E",
        csf_mode="approaching conceptual uninspiration",
        prescription="stop producing, refill — output is outrunning input "
        "and repetition arrives before it is noticed",
        kind="posterior",
        window_days=28,
        needs=14,
        needs_unit="days",
        bar="P(completion gap ≥ 0.30) ≥ 0.90",
        healthy_verdict="not supported",
    ),
    Contract(
        key="c5_write_carries_the_others",
        title="Write carries the others",
        claim="days where Write is missed show lower completion across the other four",
        component="T",
        csf_mode="traversal degradation (all modes)",
        prescription="offload to text — reactive and disorganised is a "
        "traversal problem, and Write is the traversal aid",
        kind="posterior",
        window_days=60,
        needs=14,
        needs_unit="days",
        bar="P(completion gap ≥ 0.10) ≥ 0.90, both arms non-empty",
        healthy_verdict="not supported",
    ),
    Contract(
        key="c6_dormancy_escalation",
        title="Dormancy escalation",
        claim="some mode has been dormant for 21 or more consecutive days",
        component="R",
        csf_mode="dormancy (masquerades as generative uninspiration)",
        prescription="the R question: if nothing visibly suffered in three "
        "weeks, that is evidence about the rules — recommit or honestly "
        "retire the semantics",
        kind="deterministic",
        window_days=None,
        needs=1,
        needs_unit="days",
        bar="current never-started run ≥ 21 days for any mode",
        healthy_verdict="not supported",
    ),
    Contract(
        key="c7_harmonious_stagnation",
        title="Harmonious stagnation",
        claim="adherence stays high while production stays at zero",
        component="R/E",
        csf_mode="the harmonious case (conceptual uninspiration in slow motion)",
        prescription="inject charge: value something the current practice "
        "does not already produce — harmony is the precursor to stagnation",
        kind="deterministic",
        window_days=28,
        needs=28,
        needs_unit="days",
        bar="trailing 28-day adherence ≥ 0.7 with zero production events",
        healthy_verdict="not supported",
    ),
    Contract(
        key="c8_productive_aberration",
        title="Productive aberration",
        claim="a real share of producing days have no completed Reveal",
        component="R",
        csf_mode="observable productive aberration",
        prescription="the quarterly question: if the good stuff keeps "
        "arriving from outside the five, the boundary of R is drawn wrong "
        "— not the discipline, the rules",
        kind="deterministic",
        window_days=60,
        needs=4,
        needs_unit="producing_days",
        bar="≥ 25% of producing days in the window lack a completed Reveal",
        healthy_verdict="not supported",
    ),
    Contract(
        key="c9_publication_rate",
        title="Publication cadence floor",
        claim="the practice sustains at least one publication per month, "
        "regardless of size or substance — an absolute minimum, "
        "indefinitely",
        component="E",
        csf_mode="cadence floor (tests the two-year publication goal)",
        prescription="if refuted, the floor is broken: address the nature "
        "of the flow, never the accounting",
        kind="posterior",
        window_days=90,
        needs=90,
        needs_unit="flow_era_days",
        bar="P(λ ≥ 1.0/month) ≥ 0.90, λ ~ Gamma(2, 2) prior, trailing 90 days",
        healthy_verdict="supported",
    ),
)

CONTRACT_KEYS = frozenset(c.key for c in REGISTRY)
CONTRACT_MEASURES = frozenset(c.measure for c in REGISTRY)


def by_key(key: str) -> Contract:
    """The contract for a key; KeyError on an unknown one, loudly."""
    for contract in REGISTRY:
        if contract.key == key:
            return contract
    raise KeyError(f"no contract {key!r} in the registry")


def trailing(
    rows: list[dict[str, Any]], window_days: int | None, today: date
) -> list[dict[str, Any]]:
    """The rows inside a trailing window ending today, by flow day.

    `None` means no window — the rows come back untouched — so callers can
    pass a contract's `window_days` straight through. The boundary is
    half-open on the old side: exactly `window_days` distinct days can
    appear, today included.
    """
    if window_days is None:
        return list(rows)
    floor = (today - timedelta(days=window_days)).isoformat()
    return [r for r in rows if r.get("day") and r["day"] > floor]
