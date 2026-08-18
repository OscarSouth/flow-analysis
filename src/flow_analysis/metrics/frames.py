"""Polars frames for the analysis surfaces.

Shared by the marimo notebook and the published dashboard so both read the same
numbers. Nothing here computes a diagnostic — that lives in `diagnostics.py`;
this module only reshapes.

Every frame builder is paired with a `Gate`, because the whole analysis layer is
built on refusing to answer questions the data cannot carry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, cast

import polars as pl

from ..util import parse_iso, to_local
from .grid import ABANDONED, COMPLETED, NEVER_APPEARED, NEVER_STARTED, FlowRow

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..config import Config

# Minimum days/observations per plot. Mirrors the table in docs/06-diagnostics.md.
GATES: dict[str, int] = {
    "calendar": 7,
    "rolling_rate": 14,
    "start_latency": 20,  # observations per mode, not days
    "completion_clock": 20,  # observations per mode
    "weekday": 28,
    "pull_order": 14,
    "charge": 28,
    "streaks": 14,
    "coupling": 60,
    "cumulative_output": 28,
}

OUTCOME_ORDER = [COMPLETED, ABANDONED, NEVER_STARTED, NEVER_APPEARED]


@dataclass
class Gate:
    """Whether a plot may render, and what to say if not."""

    name: str
    n: int
    needs: int

    @property
    def open(self) -> bool:
        """Whether N has cleared the threshold this gate guards."""
        return self.n >= self.needs

    @property
    def message(self) -> str:
        """The refusal, phrased as a countdown rather than an error.

        "Not yet" is a result: the honest output below threshold says how far
        off it is, so the reader knows the question is coming, not broken.
        """
        return (
            f"**{self.name}** — insufficient data: {self.n} of {self.needs} needed. "
            f"{self.needs - self.n} more to go."
        )


def gate(name: str, n: int) -> Gate:
    """Look up a gate by name and test N against it.

    Thresholds live in one table so a plot and the prose about it cannot drift
    apart on what counts as enough data.
    """
    return Gate(name=name, n=n, needs=GATES[name])


def grid_frame(rows: Sequence[FlowRow]) -> pl.DataFrame:
    """One row per (day, activity) — the base table everything derives from.

    An explicit schema on the empty case matters: an empty frame with no columns
    would make every downstream `filter` raise instead of returning nothing.
    """
    if not rows:
        return pl.DataFrame(
            schema={
                "day": pl.Date,
                "activity": pl.Utf8,
                "outcome": pl.Utf8,
                "failure_kind": pl.Utf8,
                "minutes_to_start": pl.Float64,
                "minutes_to_complete": pl.Float64,
                "pull_rank": pl.Int64,
                "interleaved": pl.Int64,
                "completed_hour": pl.Int64,
                "weekday": pl.Utf8,
            }
        )

    records: list[dict[str, Any]] = []
    for row in rows:
        day = date.fromisoformat(row.day)
        records.append(
            {
                "day": day,
                "activity": row.activity,
                "outcome": row.outcome,
                "failure_kind": row.failure_kind,
                "minutes_to_start": row.minutes_to_start,
                "minutes_to_complete": row.minutes_to_complete,
                "pull_rank": row.pull_rank,
                "interleaved": row.interleaved,
                "completed_hour": None,
                "weekday": day.strftime("%a"),
            }
        )
    frame = pl.DataFrame(records)

    # Completion hour must be local — the whole point of the clock plot is when
    # work actually lands in the day as lived, not in UTC — and the timezone is
    # not known here, so `with_local_hours` fills this later. The column is still
    # declared with its dtype: built from all-null records it would come back as
    # Null, and the later fill would have nowhere typed to land.
    hours: list[int | None] = [None] * len(rows)
    return frame.with_columns(pl.Series("completed_hour", hours, dtype=pl.Int64))


def with_local_hours(
    frame: pl.DataFrame, rows: Sequence[FlowRow], tz: str
) -> pl.DataFrame:
    """Attach the local completion hour, which needs the timezone."""
    hours = [
        to_local(parse_iso(row.completed_at), tz).hour if row.completed_at else None
        for row in rows
    ]
    return frame.with_columns(pl.Series("completed_hour", hours, dtype=pl.Int64))


def daily_frame(frame: pl.DataFrame, production: dict[str, int]) -> pl.DataFrame:
    """Per-day totals, joined to external production."""
    if frame.is_empty():
        return pl.DataFrame(
            schema={
                "day": pl.Date,
                "completed": pl.Int64,
                "observed": pl.Int64,
                "rate": pl.Float64,
                "output": pl.Int64,
            }
        )

    observed = frame.filter(pl.col("outcome") != NEVER_APPEARED)
    daily = (
        observed.group_by("day")
        .agg(
            completed=(pl.col("outcome") == COMPLETED).sum(),
            observed=pl.len(),
        )
        .sort("day")
        .with_columns(rate=pl.col("completed") / pl.col("observed"))
    )
    output = pl.DataFrame(
        {
            "day": [date.fromisoformat(d) for d in production],
            "output": list(production.values()),
        },
        schema={"day": pl.Date, "output": pl.Int64},
    )
    return daily.join(output, on="day", how="left").with_columns(
        pl.col("output").fill_null(0)
    )


def rolling_rate(frame: pl.DataFrame, windows: Sequence[int] = (7, 28)) -> pl.DataFrame:
    """Per-activity completion rate over *trailing* rolling windows.

    Rate, never cumulative completion — a missed day is data, not debt, so there
    is no backlog to accumulate.

    The window looks backwards and is labelled at its right edge, so a point
    reads "the rate over the N days up to here". A forward window would both
    shift the whole curve N days early and end the series on progressively
    emptier windows, which reads as a dramatic late collapse or spike that is
    only an artefact of running out of data. The lead-in is dropped for the same
    reason: the first N-1 days cannot fill a window.
    """
    if frame.is_empty():
        return pl.DataFrame(
            schema={
                "day": pl.Date,
                "activity": pl.Utf8,
                "window": pl.Int64,
                "rate": pl.Float64,
            }
        )
    observed = frame.filter(pl.col("outcome") != NEVER_APPEARED).sort("day")
    # Polars types a Series scalar as the union of everything a Series can hold;
    # the column is pl.Date and the frame is non-empty, so this is a date.
    first = cast("date", observed["day"].min())
    out = []
    for window in windows:
        rolled = (
            observed.with_columns(hit=(pl.col("outcome") == COMPLETED).cast(pl.Float64))
            .rolling(index_column="day", period=f"{window}d", group_by="activity")
            .agg(rate=pl.col("hit").mean(), n=pl.len())
            .filter(pl.col("day") >= first + timedelta(days=window - 1))
            .with_columns(window=pl.lit(window, dtype=pl.Int64))
        )
        out.append(rolled)
    return pl.concat(out)


def pull_order_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """How often each activity is reached 1st…5th.

    The refill drops them in random order, so position is a choice rather than an
    artefact of the list.
    """
    if frame.is_empty():
        return pl.DataFrame(
            schema={"activity": pl.Utf8, "pull_rank": pl.Int64, "n": pl.Int64}
        )
    return (
        frame.filter(pl.col("pull_rank").is_not_null())
        .group_by(["activity", "pull_rank"])
        .agg(n=pl.len())
        .sort(["activity", "pull_rank"])
    )


def weekday_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """Completion rate by weekday.

    A rate, not a count: Mondays and Sundays are not equally represented until
    the history is a whole number of weeks long.
    """
    if frame.is_empty():
        return pl.DataFrame(
            schema={"activity": pl.Utf8, "weekday": pl.Utf8, "rate": pl.Float64}
        )
    observed = frame.filter(pl.col("outcome") != NEVER_APPEARED)
    return (
        observed.with_columns(hit=(pl.col("outcome") == COMPLETED).cast(pl.Float64))
        .group_by(["activity", "weekday"])
        .agg(rate=pl.col("hit").mean(), n=pl.len())
    )


def streak_frame(frame: pl.DataFrame, activities: Sequence[str]) -> pl.DataFrame:
    """Current and longest completion streak per activity."""
    if frame.is_empty():
        return pl.DataFrame(
            schema={"activity": pl.Utf8, "current": pl.Int64, "longest": pl.Int64}
        )
    observed = frame.filter(pl.col("outcome") != NEVER_APPEARED).sort("day")
    records = []
    for activity in activities:
        hits = (
            observed.filter(pl.col("activity") == activity)
            .select(pl.col("outcome") == COMPLETED)
            .to_series()
            .to_list()
        )
        longest = current = 0
        for hit in hits:
            current = current + 1 if hit else 0
            longest = max(longest, current)
        records.append({"activity": activity, "current": current, "longest": longest})
    return pl.DataFrame(records)


def cumulative_output(daily: pl.DataFrame) -> pl.DataFrame:
    """Cumulative production, banded by that day's adherence."""
    if daily.is_empty():
        return daily
    return daily.with_columns(
        cumulative=pl.col("output").cum_sum(),
        band=pl.when(pl.col("rate") >= 0.8)
        .then(pl.lit("high"))
        .when(pl.col("rate") >= 0.4)
        .then(pl.lit("mid"))
        .otherwise(pl.lit("low")),
    )


def load(
    cfg: Config, rows: Sequence[FlowRow], production: dict[str, int]
) -> dict[str, Any]:
    """Every frame the surfaces need, in one call."""
    frame = with_local_hours(grid_frame(rows), rows, cfg.timezone)
    daily = daily_frame(frame, production)
    n_days = daily.height
    return {
        "grid": frame,
        "daily": daily,
        "rolling": rolling_rate(frame),
        "pull_order": pull_order_frame(frame),
        "weekday": weekday_frame(frame),
        "streaks": streak_frame(frame, cfg.activities),
        "cumulative": cumulative_output(daily),
        "n_days": n_days,
    }
