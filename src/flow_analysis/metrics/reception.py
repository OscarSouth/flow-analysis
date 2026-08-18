"""Reception: what came back, read at the horizon it can actually support.

The governing principle for this whole layer is that we are measuring the
**cumulative reward on sustained commitment**, not the immediate impact of a
specific effort. Two consequences run through everything here:

1. **No coupling to recent practice.** A star answers to a link someone posted,
   or to work shipped two years ago — not to whether you did Absorb on Tuesday.
   There is deliberately no lag-correlation in this module, and there should
   never be one. It is excluded by design rather than by threshold.

2. **Visibility is always allowed; inference is gated.** A cumulative total and
   a current level are facts and need no N. A *rate* estimated from three events
   is noise. So the summary always shows where things stand, and refuses only
   the claims — "growing", "stalling" — that the data cannot carry.

Measured on 2026-08-17, the reason that distinction matters here: the repo has
118 stars accumulated since 2018 but only 2 in 2025 and 3 so far in 2026. The
total is a real record of reach; the rate is close to dead. Both facts deserve
to be visible, and only one of them supports a trend.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from ..tiers import TIER_RECEPTION, row_tier
from ..util import parse_iso

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ..config import Config

# A trend claim on reception needs this much observed span. Levels and totals
# are shown regardless — they are facts, not inferences.
MIN_DAYS_RECEPTION_TREND = 180

# GitHub's traffic window. Also the retention period, which is why a snapshot
# rather than a continuous series is the honest unit.
TRAFFIC_WINDOW_DAYS = 14

# Clones are recorded but never treated as attention. Measured over one
# fortnight: 7 views from 5 unique visitors against 55 clones from 41 unique
# cloners. Readers do not outnumber themselves eight to one — that is mirrors,
# CI and crawlers, and the biggest clone days landed on a push, so clones partly
# measure your own activity.
CONTAMINATED_METRICS = frozenset({"clones"})


def _reception(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if row_tier(r) == TIER_RECEPTION]


def counters(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Latest observed value of each running total, and its first observation.

    Cumulative, so a gap in polling costs resolution but never the level.
    """
    latest: dict[str, dict[str, Any]] = {}
    first: dict[str, str] = {}
    for row in _reception(rows):
        if row.get("kind") != "counter":
            continue
        metric = row.get("metric")
        observed = row.get("observed_at")
        if not metric or not observed:
            continue
        if metric not in first or observed < first[metric]:
            first[metric] = observed
        current = latest.get(metric)
        if current is None or observed > current["observed_at"]:
            latest[metric] = {"value": row.get("value"), "observed_at": observed}
    for metric, entry in latest.items():
        entry["first_observed_at"] = first[metric]
        entry["observed_days"] = _span_days(first[metric], entry["observed_at"])
    return latest


def _span_days(start: str, end: str) -> int:
    return (parse_iso(end).date() - parse_iso(start).date()).days + 1


def star_history(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Stars per calendar year, from the backfilled `starred_at` timestamps.

    This is the one reception series with real history, because GitHub hands
    over the whole thing at once. It needs no waiting — but read it as a record
    of when attention arrived, not as a forecast.
    """
    stamps = sorted(
        row["created_at"]
        for row in _reception(rows)
        if row.get("kind") == "star" and row.get("created_at")
    )
    if not stamps:
        return {"total": 0, "by_year": {}, "first": None, "last": None}
    by_year = Counter(stamp[:4] for stamp in stamps)
    return {
        "total": len(stamps),
        "by_year": dict(sorted(by_year.items())),
        "first": stamps[0][:10],
        "last": stamps[-1][:10],
        "peak_year": max(by_year, key=lambda y: by_year[y]),
    }


def traffic_window(
    rows: Sequence[dict[str, Any]], metric: str = "views"
) -> dict[str, Any] | None:
    """The most recent 14-day level GitHub reported, with its own distinct count.

    Preferred over summing the per-day rows: GitHub's `uniques` for the window is
    a true distinct-visitor count, whereas adding daily uniques counts anyone who
    returned on another day more than once.
    """
    best: dict[str, Any] | None = None
    for row in _reception(rows):
        if row.get("kind") != "traffic_window" or row.get("metric") != metric:
            continue
        if best is None or row["observed_at"] > best["observed_at"]:
            best = row
    if best is None:
        return None
    return {
        "metric": metric,
        "observed_at": best["observed_at"],
        "window_days": best.get("window_days", TRAFFIC_WINDOW_DAYS),
        "count": best.get("count"),
        "uniques": best.get("uniques"),
        "contaminated": metric in CONTAMINATED_METRICS,
    }


def daily_coverage(
    rows: Sequence[dict[str, Any]], metric: str = "views", end: date | None = None
) -> dict[str, Any]:
    """How much of the trailing window we actually hold day-level data for.

    Retention is 14 days, so a gap in polling is unrecoverable. Reporting the
    fraction keeps a sparse window from being silently compared against a full
    one.
    """
    days = {
        row["day"]
        for row in _reception(rows)
        if row.get("kind") == f"traffic_{metric}" and row.get("day")
    }
    if not days:
        return {"observed": 0, "of": TRAFFIC_WINDOW_DAYS, "fraction": 0.0, "end": None}
    last = end or date.fromisoformat(max(days))
    window = {
        (last - timedelta(days=offset)).isoformat()
        for offset in range(TRAFFIC_WINDOW_DAYS)
    }
    observed = len(days & window)
    return {
        "observed": observed,
        "of": TRAFFIC_WINDOW_DAYS,
        "fraction": round(observed / TRAFFIC_WINDOW_DAYS, 3),
        "end": last.isoformat(),
    }


def referrers(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Where the traffic came from, in the most recent snapshot."""
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _reception(rows):
        if row.get("kind") == "referrer_window":
            by_day[row["observed_at"][:10]].append(row)
    if not by_day:
        return []
    newest = by_day[max(by_day)]
    return sorted(
        (
            {
                "referrer": r["referrer"],
                "count": r.get("count"),
                "uniques": r.get("uniques"),
            }
            for r in newest
        ),
        key=lambda r: r["count"] or 0,
        reverse=True,
    )


def external_posts(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Forum posts by people outside you and the org."""
    stamps = sorted(
        row["created_at"]
        for row in _reception(rows)
        if row.get("source") == "forum" and row.get("created_at")
    )
    return {
        "total": len(stamps),
        "first": stamps[0][:10] if stamps else None,
        "last": stamps[-1][:10] if stamps else None,
    }


def youtube_by_year(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Views, subscriber movement and watch time per calendar year.

    The year is the right unit here, not the day. Daily figures on a channel this
    size are mostly zeros, and the question the whole layer asks is about
    cumulative reward on sustained commitment — which only resolves at long
    horizons.
    """
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"views": 0, "gained": 0, "lost": 0, "minutes": 0}
    )
    for row in _reception(rows):
        if row.get("kind") != "analytics_day" or not row.get("day"):
            continue
        year = totals[row["day"][:4]]
        year["views"] += row.get("views") or 0
        year["gained"] += row.get("subscribers_gained") or 0
        year["lost"] += row.get("subscribers_lost") or 0
        year["minutes"] += row.get("minutes_watched") or 0
    for year in totals.values():
        year["net_subscribers"] = year["gained"] - year["lost"]
    return dict(sorted(totals.items()))


def youtube_span(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """How much YouTube history we hold.

    Unlike the GitHub counters — which only start when we begin polling — the
    Analytics API backfills, so a trend here can be supportable immediately.
    """
    days = sorted(
        row["day"]
        for row in _reception(rows)
        if row.get("kind") == "analytics_day" and row.get("day")
    )
    if not days:
        return {"days": 0, "first": None, "last": None, "open": False}
    span = _span_days(days[0], days[-1])
    return {
        "days": span,
        "first": days[0],
        "last": days[-1],
        "open": span >= MIN_DAYS_RECEPTION_TREND,
    }


def _daily_value(row: dict[str, Any], key: str | None) -> int:
    """One day's value for a YouTube analytics metric.

    Module level rather than a closure inside the metric loop: a function that
    captures the loop variable reads correctly only while it is called in the
    same iteration, and nothing in the signature says so.

    `key is None` means subscribers, which is not a column but a difference —
    gained minus lost, so a day that shed more than it gained counts negative.
    """
    if key is None:
        return (row.get("subscribers_gained") or 0) - (row.get("subscribers_lost") or 0)
    return row.get(key) or 0


def flow_era(rows: Sequence[dict[str, Any]], epoch: date) -> dict[str, dict[str, Any]]:
    """Growth since the practice began — the only reception that belongs to it.

    Everything before `epoch` is **ground zero**: real, but earned by ad-hoc
    ventures of interest rather than by this system. Reporting a lifetime total
    as though the practice produced it would be the flattering kind of accounting
    this repo exists to avoid. So the headline number is the delta, and the
    inherited baseline is shown beside it as context.

    Where an event stream exists — stars carry `starred_at`, YouTube days are
    exact, forum posts are timestamped — the delta is exact. Counters we merely
    poll (forks, watchers) can only be measured from the first observation, which
    is marked as such rather than quietly presented as if it were the epoch.
    """
    cutoff = epoch.isoformat()
    out: dict[str, dict[str, Any]] = {}

    stars = [
        r["created_at"]
        for r in _reception(rows)
        if r.get("kind") == "star" and r.get("created_at")
    ]
    out["github_stars"] = {
        "baseline": sum(1 for s in stars if s[:10] < cutoff),
        "since": sum(1 for s in stars if s[:10] >= cutoff),
        "exact": True,
    }

    external = [
        r["created_at"]
        for r in _reception(rows)
        if r.get("source") == "forum" and r.get("created_at")
    ]
    out["forum_outsiders"] = {
        "baseline": sum(1 for s in external if s[:10] < cutoff),
        "since": sum(1 for s in external if s[:10] >= cutoff),
        "exact": True,
    }

    days = [
        r for r in _reception(rows) if r.get("kind") == "analytics_day" and r.get("day")
    ]
    for metric, key in (
        ("youtube_views", "views"),
        ("youtube_subscribers", None),
        ("youtube_minutes", "minutes_watched"),
    ):
        out[metric] = {
            "baseline": sum(_daily_value(r, key) for r in days if r["day"] < cutoff),
            "since": sum(_daily_value(r, key) for r in days if r["day"] >= cutoff),
            "exact": True,
        }

    for metric in ("forks", "watchers"):
        observed = counters(rows).get(metric)
        if observed:
            out[f"github_{metric}"] = {
                "baseline": observed["value"],
                "since": 0,
                "exact": False,
                "from_first_poll": observed["first_observed_at"][:10],
            }
    return out


def trend_gate(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Whether any *rate* claim about reception is supportable yet.

    Deliberately keyed on how long we have been observing, not on how many
    events happened to arrive — an unusually busy fortnight is not evidence of a
    trend.
    """
    observed = counters(rows)
    span = max((entry["observed_days"] for entry in observed.values()), default=0)
    return {
        "observed_days": span,
        "needs": MIN_DAYS_RECEPTION_TREND,
        "open": span >= MIN_DAYS_RECEPTION_TREND,
    }


def summarise(cfg: Config, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Everything the reception surfaces need, in one call.

    `rows` is passed in rather than loaded: Layer B never reaches into the
    store. The caller owns where the data came from, which is what lets every
    function here be run against fabricated rows without touching `data/`.
    """
    all_rows = list(rows)
    return {
        "counters": counters(all_rows),
        "stars": star_history(all_rows),
        "views_window": traffic_window(all_rows, "views"),
        "clones_window": traffic_window(all_rows, "clones"),
        "views_coverage": daily_coverage(all_rows, "views"),
        "referrers": referrers(all_rows),
        "external_posts": external_posts(all_rows),
        "epoch": cfg.start_date.isoformat() if cfg.start_date else None,
        "flow_era": flow_era(all_rows, cfg.start_date) if cfg.start_date else {},
        "youtube_by_year": youtube_by_year(all_rows),
        "youtube_span": youtube_span(all_rows),
        "trend": trend_gate(all_rows),
    }


def render(summary: dict[str, Any]) -> str:
    """Growth since the practice began, then the inherited baseline as context."""
    lines: list[str] = []

    era = summary.get("flow_era")
    if era:
        lines += [f"Reception since flow began ({summary['epoch']})", ""]
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
                f"  {label:<28} {stat['since']:>+7}"
                f"    (baseline {stat['baseline']:,} before flow)"
            )
        lines += [
            "",
            "  Everything before that date is ground zero — real, but earned by ad-hoc",
            "  ventures rather than by this practice. Only the left column belongs "
            "to flow.",
            "",
            "Baseline and context",
            "",
        ]
    else:
        lines += ["Reception — what came back", ""]

    counts = summary["counters"]
    if counts:
        parts = [f"{m} {c['value']}" for m, c in sorted(counts.items())]
        lines.append("  GitHub: " + ", ".join(parts))
    stars = summary["stars"]
    if stars["total"]:
        years = "  ".join(f"{y} {n}" for y, n in stars["by_year"].items())
        lines.append(f"  Stars by year: {years}")
        lines.append(
            f"    {stars['total']} total, {stars['first']} .. {stars['last']}, "
            f"peak {stars['peak_year']}"
        )

    views = summary["views_window"]
    if views:
        coverage = summary["views_coverage"]
        lines.append(
            f"  Traffic (last {views['window_days']}d): {views['count']} views from "
            f"{views['uniques']} unique visitors"
        )
        if coverage["fraction"] < 1.0:
            lines.append(
                f"    day-level coverage {coverage['observed']}/{coverage['of']} — "
                "GitHub retains traffic 14 days, so the gap is unrecoverable"
            )
    clones = summary["clones_window"]
    if clones:
        lines.append(
            f"  Clones (last {clones['window_days']}d): {clones['count']} from "
            f"{clones['uniques']} uniques — infrastructure, not attention; "
            "mirrors and CI dominate this"
        )

    refs = summary["referrers"]
    if refs:
        lines.append(
            "  Referrers: "
            + ", ".join(f"{r['referrer']} ({r['count']})" for r in refs[:5])
        )

    years = summary["youtube_by_year"]
    span = summary["youtube_span"]
    if years:
        lines += [
            "",
            f"  YouTube, by year ({span['first']} .. {span['last']}):",
            f"    {'year':6}{'views':>8}{'subs+':>7}{'subs-':>7}{'net':>6}{'hours':>7}",
        ]
        for year, stat in list(years.items())[-8:]:
            lines.append(
                f"    {year:6}{stat['views']:>8}{stat['gained']:>7}{stat['lost']:>7}"
                f"{stat['net_subscribers']:>6}{stat['minutes'] // 60:>7}"
            )
        if span["open"]:
            lines.append(
                f"    {span['days']} days of exact daily history — "
                "long enough to read year over year"
            )

    external = summary["external_posts"]
    lines.append("")
    lines.append(
        f"  Forum posts by others: {external['total']}"
        + (f", latest {external['last']}" if external["last"] else "")
    )

    trend = summary["trend"]
    lines += [
        "",
        "  GitHub trend: "
        + (
            "supportable"
            if trend["open"]
            else f"not yet — {trend['observed_days']} of {trend['needs']} days "
            "observed since polling began. Totals above are facts; a rate is not "
            "yet one."
        ),
    ]
    if span.get("days"):
        lines.append(
            "  YouTube trend: "
            + (
                "supportable — Analytics backfills, so the history was there from day "
                "one"
                if span["open"]
                else f"not yet — {span['days']} of {MIN_DAYS_RECEPTION_TREND} days"
            )
        )
    lines.append(
        "  Never coupled to recent practice: reception answers to "
        "promotion and to work shipped long ago."
    )
    return "\n".join(lines)
