"""Dagster assets, by medallion layer.

`raw` stores what the APIs said, verbatim, in `data/*.jsonl`. Everything from
`dim` onward lives in Neo4j as node **labels** — `(:Stg:FlowRow)`, `(:Dim:Day)` —
and is rebuildable from `raw` without a single external call, which is what makes
it safe to keep irreplaceable history behind a disposable Docker volume.
"""

from __future__ import annotations

from .dim import dim_activity, dim_day
from .enr import enr_day_adherence
from .fct import fct_measures
from .gds import enr_activity_similarity, enr_day_similarity
from .knowledge import stg_knowledge, stg_knowledge_links
from .posteriors import fct_posteriors
from .raw import RAW_ASSETS
from .stg import stg_flow_grid, stg_signals

DIM_ASSETS = [dim_day, dim_activity]
STG_ASSETS = [stg_flow_grid, stg_signals]
ENR_ASSETS = [enr_day_adherence, enr_activity_similarity, enr_day_similarity]
KNOWLEDGE_ASSETS = [stg_knowledge, stg_knowledge_links]
FCT_ASSETS = [fct_measures, fct_posteriors]

GRAPH_ASSETS = [*DIM_ASSETS, *STG_ASSETS, *ENR_ASSETS, *FCT_ASSETS, *KNOWLEDGE_ASSETS]
ALL_ASSETS = [*RAW_ASSETS, *GRAPH_ASSETS]

__all__ = [
    "ALL_ASSETS",
    "DIM_ASSETS",
    "ENR_ASSETS",
    "FCT_ASSETS",
    "GRAPH_ASSETS",
    "KNOWLEDGE_ASSETS",
    "RAW_ASSETS",
    "STG_ASSETS",
]
