"""Which question a stored row answers. The vocabulary, and nothing else.

Deliberately at the package root and deliberately dependency-free: both the
sources that *write* tiers and the metrics that *filter* on them need this, and
neither should have to import the other to get three strings.

The distinction is load-bearing, not decorative:

  production   what you put out       your forum posts, your uploads
  reception    what came back         stars, subscribers, other people's posts
  embodiment   what was done, bodily  workouts, body mass

Conflating them would let a stranger's attention inflate the measure of your own
output — `production_by_day` filters on it, and without that filter
`adherence_without_production` says the opposite of the truth. See
docs/06-diagnostics.md.
"""

from __future__ import annotations

from typing import Any

TIER_PRODUCTION = "production"
TIER_RECEPTION = "reception"
TIER_EMBODIMENT = "embodiment"
# An org-mate's post is neither. It is not a response from outside, so it is not
# reception; and it is not evidence that *your* practice produced anything, so
# counting it as production would let someone else's work answer the question
# `adherence_without_production` asks about you.
TIER_INTERNAL_OTHER = "internal_other"


def row_tier(row: dict[str, Any]) -> str:
    """The tier a stored row belongs to.

    Rows written before the field existed were all your own forum posts, so they
    default to production. New sources must set it explicitly — the source tests
    pin that they do.
    """
    return row.get("tier") or TIER_PRODUCTION
