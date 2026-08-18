"""Synthetic history, so the analysis layer can be built before real data exists.

The daily practice went live on 2026-08-16. Rates and streaks mean nothing for
8-12 weeks, but the metrics, the gating and the plots all need something to be
developed against. This module fabricates a realistic store.

**These fixtures are constructed, not observed.** They deliberately contain the
patterns the analysis is supposed to detect — Train under-allocated, Express slow
to start, a dormant stretch, a decaying tail. That makes them a test of the
*machinery*, and emphatically not evidence about the real practice. Nothing here
should ever be cited as a finding.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from .config import Config

# Fixture list ids. Deliberately unlike real Trello ids so a fixture store can
# never be mistaken for the real one.
FIX_FUTURE = "fixlist_future"
FIX_PRESENT = "fixlist_present"
FIX_PAST = "fixlist_past"
FIX_DRAIN = "fixlist_drain"
FIX_LABEL = "fixlabel_flow"

ACTIVITIES = ["Write", "Absorb", "Train", "Express", "Reveal"]

# Per-activity behaviour. `complete` is the baseline daily completion rate;
# `never_start` is the share of failures where the card was never touched at all
# (allocation failure) rather than started and abandoned (capacity failure);
# `start_hours` is the mean delay from the card appearing to first being moved.
#
# Train and Express are the load-bearing pair: Train fails by allocation (never
# reached) and Express by capacity (started, abandoned), because the analysis has
# to be able to tell those apart and the remedies are opposite. Express sat at
# 0.50 — a coin flip — which meant the split only actually appeared when the
# weekend modifiers happened to fall a certain way, and the test asserting it
# passed on Mondays and failed the rest of the week. Keep Express well clear of
# 0.5 so the pattern is present by design rather than by calendar alignment.
PROFILE: dict[str, dict[str, float]] = {
    "Write": {"complete": 0.82, "never_start": 0.55, "start_hours": 2.5},
    "Absorb": {"complete": 0.68, "never_start": 0.60, "start_hours": 4.0},
    "Train": {"complete": 0.44, "never_start": 0.85, "start_hours": 5.0},
    "Express": {"complete": 0.61, "never_start": 0.30, "start_hours": 9.0},
    "Reveal": {"complete": 0.55, "never_start": 0.65, "start_hours": 6.5},
}

# Tests pin `end` to this so the suite cannot depend on the day it is run.
# Deliberately a Wednesday: the weekday-dependent bug this replaced only showed
# the intended pattern when `end` landed on a Sunday, so pinning to a Sunday
# would have hidden it just as effectively as leaving the default.
REFERENCE_END = date(2026, 8, 12)


@dataclass
class Fixture:
    """A fabricated store: Trello cards and actions, plus forum posts."""

    cards: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    forum: list[dict[str, Any]] = field(default_factory=list)
    days: list[date] = field(default_factory=list)


def _oid(moment: datetime, counter: int) -> str:
    """Mongo-style id: 8 hex chars of epoch, then 16 of anything.

    Real Trello ids carry their creation time this way, and `util.card_created_at`
    reads it — so fixtures must too, or every appeared_at would be wrong.
    """
    return f"{int(moment.timestamp()):08x}{counter:016x}"


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _move(
    counter: int, card_id: str, name: str, at: datetime, before: str, after: str
) -> dict[str, Any]:
    return {
        "id": f"fixact{counter:08d}m",
        "type": "updateCard",
        "date": _iso(at),
        "data": {
            "card": {"id": card_id, "name": name},
            "listBefore": {"id": before},
            "listAfter": {"id": after},
        },
    }


def synthesize(
    days: int = 120,
    end: date | None = None,
    tz: str = "Europe/London",
    refill_at: time = time(6, 0),
    seed: int = 7,
    dormant: tuple[str, int, int] | None = ("Absorb", 62, 78),
    decay_from: float = 0.75,
) -> Fixture:
    """Fabricate `days` of practice ending on `end` (default: yesterday).

    `dormant` closes one channel entirely between two day-indices — the failure
    mode with no analogue in Wiggins' framework, since nothing is ever attempted.
    `decay_from` is the fraction of the run after which completion rates ramp
    down, producing a fading tail for the rolling-rate and lead/lag work.
    """
    rng = random.Random(seed)
    zone = ZoneInfo(tz)
    end = end or (datetime.now(zone).date() - timedelta(days=1))
    first = end - timedelta(days=days - 1)

    fx = Fixture()
    counter = 0

    for index in range(days):
        day = first + timedelta(days=index)
        fx.days.append(day)
        appeared = datetime.combine(day, refill_at, tzinfo=zone)

        # Weekends are quieter; the tail of the run decays.
        modifier = 0.8 if day.weekday() >= 5 else 1.0
        if index >= days * decay_from:
            span = days - days * decay_from
            modifier *= 1.0 - 0.4 * ((index - days * decay_from) / span)

        # Write is load-bearing: on days it is missed, everything else suffers.
        # This is one of the publicly pre-registered hypotheses, so the fixture
        # has to contain it for the test of that hypothesis to be meaningful.
        write_done = rng.random() < PROFILE["Write"]["complete"] * modifier
        order = ACTIVITIES[:]
        rng.shuffle(order)  # cards are refilled in random order

        for rank, activity in enumerate(order):
            counter += 1
            profile = PROFILE[activity]
            card_id = _oid(appeared + timedelta(seconds=rank), counter)

            fx.actions.append(
                {
                    "id": f"fixact{counter:08d}c",
                    "type": "createCard",
                    "date": _iso(appeared + timedelta(seconds=rank)),
                    "data": {
                        "card": {"id": card_id, "name": activity},
                        "list": {"id": FIX_FUTURE},
                    },
                }
            )

            is_dormant = bool(
                dormant and activity == dormant[0] and dormant[1] <= index <= dormant[2]
            )
            chance = profile["complete"] * modifier
            if activity != "Write" and not write_done:
                chance -= 0.25

            if is_dormant:
                outcome = "never_started"
            elif rng.random() < chance:
                outcome = "completed"
            elif rng.random() < profile["never_start"]:
                outcome = "never_started"
            else:
                outcome = "abandoned"

            list_now = FIX_FUTURE
            closed = True
            if outcome in ("completed", "abandoned"):
                started = appeared + timedelta(
                    hours=max(0.1, rng.gauss(profile["start_hours"], 1.6))
                )
                fx.actions.append(
                    _move(counter, card_id, activity, started, FIX_FUTURE, FIX_PRESENT)
                )
                list_now = FIX_PRESENT
                if outcome == "completed":
                    done = started + timedelta(hours=max(0.15, rng.gauss(1.4, 0.7)))
                    fx.actions.append(
                        _move(counter, card_id, activity, done, FIX_PRESENT, FIX_PAST)
                    )
                    list_now = FIX_PAST
                    closed = False

                    # Reveal is the mode that leaves an external trace.
                    if activity == "Reveal" and rng.random() < 0.38:
                        fx.forum.append(
                            {
                                "id": f"fixpost{counter:08d}",
                                "created_at": _iso(
                                    done + timedelta(minutes=rng.randint(5, 240))
                                ),
                                "author": "Oscar-UDAGAN",
                                "kind": "post",
                            }
                        )

            if closed:  # swept by the 04:00 drain the following morning
                swept = datetime.combine(
                    day + timedelta(days=1), time(4, 0), tzinfo=zone
                )
                fx.actions.append(
                    _move(counter, card_id, activity, swept, list_now, FIX_DRAIN)
                )
                list_now = FIX_DRAIN

            fx.cards.append(
                {
                    "id": card_id,
                    "name": activity,
                    "idList": list_now,
                    "closed": closed,
                    "labels": [{"id": FIX_LABEL, "name": "Flow"}],
                }
            )

    # Occasional production on days the practice was skipped — observable
    # productive aberration, the trigger for asking whether R is still right.
    for day in fx.days:
        if rng.random() < 0.04:
            moment = datetime.combine(day, time(21, 0), tzinfo=zone)
            fx.forum.append(
                {
                    "id": f"fixpost-ab-{day.isoformat()}",
                    "created_at": _iso(moment),
                    "author": "Oscar-UDAGAN",
                    "kind": "post",
                }
            )

    fx.actions.sort(key=lambda a: a["date"])
    fx.forum.sort(key=lambda p: p["created_at"])
    return fx


def fixture_config(start: date, tz: str = "Europe/London") -> Config:
    """A Config wired to the fixture list ids, for use with `metrics.grid.fold_rows`."""
    from .config import Config, ListRole

    return Config(
        intent={},
        resolved={"board_id": "fixboard", "label_id": FIX_LABEL},
        lists={
            "future": ListRole("future", "future", FIX_FUTURE),
            "present": ListRole("present", "present", FIX_PRESENT),
            "past": ListRole("past", "past", FIX_PAST),
            "drain": ListRole("drain", "drain", FIX_DRAIN),
        },
        activities=list(ACTIVITIES),
        descriptions={},
        label_name="Flow",
        label_colour="sky",
        timezone=tz,
        drain_at=time(4, 0),
        refill_at=time(6, 0),
        start_date=start,
    )
