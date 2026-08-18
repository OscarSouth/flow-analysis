"""The flow-day calendar — the day boundary, defined once.

The flow day runs **04:00 → 04:00**, not midnight → midnight, in both the
board's behaviour and the analysis. A completion at 01:00 belongs to the
previous day: at 01:00 that card is still sitting in `present`, un-drained.

Everything that buckets a moment into a day derives from here. If
`schedule.drain_at` ever changes, the Butler rule and this move together or the
numbers stop matching the board.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from ..util import to_local

if TYPE_CHECKING:
    from datetime import date, time


def flow_day(moment: datetime, tz_name: str, day_start: time) -> date:
    """Attribute a moment to a flow day.

    The day boundary is the purge time, not midnight: with a 04:00 purge, work
    finished at 01:00 belongs to the previous day, which is exactly how the board
    behaves — that card is still sitting there un-purged.
    """
    local = to_local(moment, tz_name)
    if local.time() < day_start:
        return (local - timedelta(days=1)).date()
    return local.date()


def day_bounds(day: date, tz_name: str, day_start: time) -> tuple[datetime, datetime]:
    """UTC [start, end) of a flow day."""
    tz = ZoneInfo(tz_name)
    start = datetime.combine(day, day_start, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), day_start, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def calendar_days(start: date, end: date) -> list[dict[str, Any]]:
    """Every flow day from `start` to `end` inclusive, with its own attributes.

    A dense calendar, so a day on which nothing happened at all still exists as a
    row. That is the same reason the flow grid is dense: absence is a finding,
    and it can only be seen if there is something there to be empty.

    Weekday and week number are carried rather than derived later so that every
    surface groups days the same way — the weekday effect is one of the things
    the analysis reports, and two implementations of "which week is this" would
    eventually disagree.
    """
    if end < start:
        raise ValueError(f"calendar runs forwards: got start={start}, end={end}")

    days: list[dict[str, Any]] = []
    current = start
    while current <= end:
        iso_year, iso_week, iso_weekday = current.isocalendar()
        days.append(
            {
                "date": current.isoformat(),
                "weekday": current.strftime("%a"),
                "weekday_index": iso_weekday,  # Monday = 1, matching ISO
                "is_weekend": iso_weekday >= 6,
                "iso_week": f"{iso_year}-W{iso_week:02d}",
                "month": current.strftime("%Y-%m"),
                "year": current.year,
            }
        )
        current += timedelta(days=1)
    return days
