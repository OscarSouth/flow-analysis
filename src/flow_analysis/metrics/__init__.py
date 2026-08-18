"""Layer B — computation. Pure functions, and nothing else.

Diagnostics, reception, embodiment, the frames the surfaces plot, the gating
that refuses to answer under-powered questions, and the flow-day calendar.

**Nothing here may import from Layer A (`sources/`, fetching) or Layer C
(`store`, `graph/`, the assets).** These functions take data as arguments and
return computed results, which is what makes them testable against fabricated
fixtures and what will let them move under Dagster unchanged. Layers A and C may
import from here; the arrow never points back.
"""

from __future__ import annotations
