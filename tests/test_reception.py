"""Reception — levels are facts, rates are claims.

The distinction these tests defend: a cumulative total needs no N and is always
shown; a trend needs a long observed span and is refused until it has one.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from flow_analysis.fixtures import fixture_config
from flow_analysis.metrics import reception
from flow_analysis.tiers import TIER_PRODUCTION, TIER_RECEPTION


def _counter(metric, value, day) -> dict[str, Any]:
    return {
        "id": f"github:{metric}:{day}",
        "tier": TIER_RECEPTION,
        "source": "github",
        "kind": "counter",
        "metric": metric,
        "observed_at": f"{day}T12:00:00+00:00",
        "value": value,
    }


def _star(login, when) -> dict[str, Any]:
    return {
        "id": f"github:star:{login}",
        "tier": TIER_RECEPTION,
        "source": "github",
        "kind": "star",
        "created_at": when,
        "actor": login,
    }


def _traffic_day(metric, day, count, uniques) -> dict[str, Any]:
    return {
        "id": f"github:{metric}:{day}",
        "tier": TIER_RECEPTION,
        "source": "github",
        "kind": f"traffic_{metric}",
        "metric": metric,
        "day": day,
        "created_at": f"{day}T00:00:00Z",
        "count": count,
        "uniques": uniques,
    }


def _window(metric, day, count, uniques) -> dict[str, Any]:
    return {
        "id": f"github:{metric}_window:{day}",
        "tier": TIER_RECEPTION,
        "source": "github",
        "kind": "traffic_window",
        "metric": metric,
        "observed_at": f"{day}T12:00:00+00:00",
        "window_days": 14,
        "count": count,
        "uniques": uniques,
    }


def test_counters_take_the_latest_observation():
    rows = [
        _counter("stars", 116, "2026-08-01"),
        _counter("stars", 118, "2026-08-17"),
    ]
    result = reception.counters(rows)
    assert result["stars"]["value"] == 118
    assert result["stars"]["first_observed_at"].startswith("2026-08-01")
    assert result["stars"]["observed_days"] == 17


def test_star_history_reads_as_a_record_not_a_forecast():
    """The real shape: a 2020 peak, then decay. Both facts must survive."""
    rows = (
        [_star(f"a{i}", "2020-06-01T00:00:00Z") for i in range(37)]
        + [_star(f"b{i}", "2025-03-01T00:00:00Z") for i in range(2)]
        + [_star(f"c{i}", "2026-05-29T00:00:00Z") for i in range(3)]
    )
    history = reception.star_history(rows)

    assert history["total"] == 42
    assert history["peak_year"] == "2020"
    assert history["by_year"] == {"2020": 37, "2025": 2, "2026": 3}
    assert history["last"] == "2026-05-29"


def test_window_prefers_githubs_own_distinct_count():
    """Summing daily uniques double-counts anyone who returned."""
    rows = [
        _traffic_day("views", "2026-08-15", 4, 3),
        _traffic_day("views", "2026-08-16", 3, 3),
        _window("views", "2026-08-17", 7, 5),  # GitHub's true distinct count
    ]
    window = reception.traffic_window(rows, "views")

    assert window["count"] == 7
    assert window["uniques"] == 5  # not 3 + 3
    assert window["contaminated"] is False


def test_clones_are_flagged_as_contaminated():
    """41 unique cloners against 5 unique viewers is machines, not readers."""
    rows = [_window("clones", "2026-08-17", 55, 41)]
    assert reception.traffic_window(rows, "clones")["contaminated"] is True


def test_coverage_reports_an_unrecoverable_gap():
    """Retention is 14 days, so a polling gap can never be filled in later."""
    rows = [
        _traffic_day("views", "2026-08-15", 1, 1),
        _traffic_day("views", "2026-08-16", 1, 1),
    ]
    coverage = reception.daily_coverage(rows, "views", end=date(2026, 8, 16))

    assert coverage["observed"] == 2
    assert coverage["of"] == 14
    assert coverage["fraction"] == pytest.approx(0.143, abs=0.001)


def test_full_coverage_is_reported_as_such():
    rows = [_traffic_day("views", f"2026-08-{day:02d}", 1, 1) for day in range(3, 17)]
    coverage = reception.daily_coverage(rows, "views", end=date(2026, 8, 16))
    assert coverage["observed"] == 14
    assert coverage["fraction"] == 1.0


def test_trend_is_refused_on_a_short_span():
    """A rate from one day of observation is not a rate."""
    rows = [_counter("stars", 118, "2026-08-17")]
    gate = reception.trend_gate(rows)

    assert gate["open"] is False
    assert gate["observed_days"] == 1
    assert gate["needs"] == reception.MIN_DAYS_RECEPTION_TREND


def test_trend_opens_once_the_span_is_long_enough():
    rows = [_counter("stars", 100, "2026-01-01"), _counter("stars", 118, "2026-08-17")]
    assert reception.trend_gate(rows)["open"] is True


def test_production_rows_are_never_read_as_reception():
    """The tier boundary holds in this direction too."""
    rows = [
        {
            "id": "p",
            "tier": TIER_PRODUCTION,
            "source": "forum",
            "created_at": "2026-07-09T08:00:00+00:00",
        },
    ]
    assert reception.external_posts(rows)["total"] == 0
    assert reception.counters(rows) == {}


def test_render_always_shows_totals_and_refuses_the_trend():
    cfg = fixture_config(date(2026, 7, 1))
    rows = [_counter("stars", 118, "2026-08-17"), _star("a", "2020-06-01T00:00:00Z")]

    text = reception.render(reception.summarise(cfg, rows))

    assert "stars 118" in text  # the fact, shown regardless of N
    assert "not yet" in text  # the claim, refused
    assert "Never coupled to recent practice" in text


# --- the flow epoch ---------------------------------------------------------


def _yt_day(day, views=0, gained=0, lost=0, minutes=0) -> dict[str, Any]:
    return {
        "id": f"youtube:day:{day}",
        "tier": TIER_RECEPTION,
        "source": "youtube",
        "kind": "analytics_day",
        "day": day,
        "created_at": f"{day}T12:00:00+00:00",
        "views": views,
        "subscribers_gained": gained,
        "subscribers_lost": lost,
        "minutes_watched": minutes,
    }


def test_pre_epoch_reception_is_ground_zero_not_growth():
    """Everything before the practice began was earned by something else.

    Reporting a lifetime total as though the practice produced it is exactly the
    flattering accounting this repo exists to avoid.
    """
    epoch = date(2026, 8, 16)
    rows = [
        _star("old", "2020-06-01T00:00:00Z"),  # inherited
        _star("new", "2026-08-17T00:00:00Z"),  # earned since
        _yt_day("2026-08-01", views=500, gained=9),  # inherited
        _yt_day("2026-08-17", views=40, gained=2, lost=1),  # earned since
    ]

    era = reception.flow_era(rows, epoch)

    assert era["github_stars"] == {"baseline": 1, "since": 1, "exact": True}
    assert era["youtube_views"]["baseline"] == 500
    assert era["youtube_views"]["since"] == 40
    assert era["youtube_subscribers"]["baseline"] == 9
    assert era["youtube_subscribers"]["since"] == 1  # 2 gained less 1 lost


def test_the_epoch_day_itself_counts_as_flow():
    """The boundary is inclusive: day one of the practice belongs to it."""
    epoch = date(2026, 8, 16)
    rows = [_star("a", "2026-08-16T09:00:00Z")]
    assert reception.flow_era(rows, epoch)["github_stars"]["since"] == 1


def test_polled_counters_admit_they_start_at_first_poll():
    """Forks and watchers have no event history.

    Their baseline is whenever polling began, which must be stated rather than
    passed off as the epoch.
    """
    epoch = date(2026, 8, 16)
    rows = [_counter("forks", 8, "2026-08-17")]

    entry = reception.flow_era(rows, epoch)["github_forks"]

    assert entry["exact"] is False
    assert entry["from_first_poll"] == "2026-08-17"
    assert entry["since"] == 0


def test_render_leads_with_growth_and_labels_the_baseline():
    cfg = fixture_config(date(2026, 7, 1))
    cfg.start_date = date(2026, 8, 16)
    rows = [_star("old", "2020-06-01T00:00:00Z"), _star("new", "2026-08-17T00:00:00Z")]

    text = reception.render(reception.summarise(cfg, rows))

    assert "Reception since flow began (2026-08-16)" in text
    assert "ground zero" in text
    assert "GitHub stars" in text
