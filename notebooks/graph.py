import marimo

__generated_with = "0.23.16"
app = marimo.App(width="medium", app_title="The Flow Graph — a guided tour")

# Literate contract: notebooks/README.md. This notebook is the guide to the
# graph itself — schema, layers, worked queries, and the knowledge layer.


@app.cell
def imports():
    import sys
    from pathlib import Path

    import altair as alt
    import marimo as mo
    import polars as pl

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

    from flow_analysis import dashboard
    from flow_analysis.graph import loaders
    from flow_analysis.resources.graph import Neo4jResource

    theme = dashboard.LIGHT

    def cypher(query: str) -> pl.DataFrame:
        """Run one read-only query and return a frame — the notebook's lens."""
        with Neo4jResource().driver() as d, d.session() as s:
            return pl.DataFrame(
                [dict(r) for r in s.run(query)], infer_schema_length=None
            )

    return alt, cypher, loaders, mo, pl, theme


@app.cell
def intro(mo):
    mo.md("""
    # The Flow Graph — a guided tour

    **What this notebook holds open:** what the graph contains, how each layer
    earns its place, and what the knowledge layer makes possible. Every query
    below runs live against the graph as you read.

    **The one architectural fact to carry:** the graph is *derived*. The
    append-only archive (`data/*.jsonl`) is the truth; Neo4j is rebuilt from it,
    provably, with no network. That is why it is safe to query freely — nothing
    here is the only copy of anything — and why it is the **sole analysis
    source**: one path from record to conclusion, so two readings can never
    quietly disagree.

    The layers are Neo4j **labels**, not name prefixes, so every query below is
    label-indexed:

    | layer | holds | intuition |
    |---|---|---|
    | `Dim` | Day, Activity, Source | the things facts hang off |
    | `Stg` | FlowRow, Signal, Note | validated observations, one node per fact |
    | `Enr` | day adherence, similarity edges | what a row cannot know alone |
    | `Fct` | Measure, Posterior, Interpretation | judgements, with their adequacy |
    | `Meta` | Review, Prescription, Transformation, Hypothesis, GateOpened, DevProposal, Belief, Reference, Journal | the practice's record of examining itself |
    """)
    return ()


@app.cell
def census_header(mo):
    mo.md("""
    ## 1 — The census

    *What's asking:* what does the graph hold right now? *How:* count every
    label. *How to read:* `Signal` dominates — every external event is one
    node. *What would change it:* every sync grows `Signal` and `Posterior`;
    the `Meta` labels grow only when the practice examines itself.
    """)
    return ()


@app.cell
def census(cypher, mo):
    _df = cypher("""
        MATCH (n) UNWIND labels(n) AS label
        RETURN label, count(*) AS nodes ORDER BY nodes DESC
    """)
    mo.ui.table(_df.to_dicts(), selection=None)
    return ()


@app.cell
def calendar_header(mo):
    mo.md("""
    ## 2 — The calendar spine

    *What's asking:* is the day chain intact? *How:* walk `NEXT` from the day
    nothing precedes to the day nothing follows. *How to read:* one row, whose
    `days` equals the number of `Dim:Day` nodes — a broken chain would split
    this into fragments. *What would change it:* nothing should, ever; the
    rebuild test asserts it.

    ```cypher
    MATCH p = (a:Dim:Day)-[:NEXT*]->(b:Dim:Day)
    WHERE NOT (:Dim:Day)-[:NEXT]->(a) AND NOT (b)-[:NEXT]->(:Dim:Day)
    RETURN a.date AS first, b.date AS last, length(p)+1 AS days
    ```
    """)
    return ()


@app.cell
def calendar_walk(cypher, mo):
    _df = cypher("""
        MATCH p = (a:Dim:Day)-[:NEXT*]->(b:Dim:Day)
        WHERE NOT (:Dim:Day)-[:NEXT]->(a) AND NOT (b)-[:NEXT]->(:Dim:Day)
        RETURN a.date AS first, b.date AS last, length(p)+1 AS days
    """)
    mo.ui.table(_df.to_dicts(), selection=None)
    return ()


@app.cell
def grid_header(mo):
    mo.md("""
    ## 3 — The staged grid, seen from the graph

    *What's asking:* what does one (day, mode) cell look like as a node? *How:*
    every `Stg:FlowRow` carries its outcome, latencies, pull order — and joins
    the calendar and its mode by relationship, which is what makes "all of
    Train's history" one hop. *How to read:* five rows per day, dense by
    construction: a day the refill failed still has rows, saying
    `never_appeared`. Absence is a finding.
    """)
    return ()


@app.cell
def grid_sample(cypher, mo):
    _df = cypher("""
        MATCH (r:Stg:FlowRow)-[:ON_DAY]->(d:Dim:Day)
        RETURN d.date AS day, r.activity AS mode, r.outcome AS outcome,
               r.minutes_to_start AS mins_to_start, r.pull_rank AS pull_rank
        ORDER BY day, mode
    """)
    mo.ui.table(_df.to_dicts(), selection=None)
    return ()


@app.cell
def signals_header(mo):
    mo.md("""
    ## 4 — Signals: the full payload, queryable

    *What's asking:* can the graph answer payload questions without Python?
    *How:* every scalar the sources ever reported rides on `(:Stg:Signal)` as a
    property — so "body mass over time" is a WHERE clause. *How to read:* the
    tier is the load-bearing column: `production` is what left the building,
    `reception` what came back, and conflating them would let a stranger's star
    count as your own output.

    ```cypher
    MATCH (s:Stg:Signal {metric: 'body_mass'})
    RETURN s.created_at, s.value ORDER BY s.created_at DESC LIMIT 5
    ```
    """)
    return ()


@app.cell
def signals_sample(cypher, mo):
    _tiers = cypher("""
        MATCH (s:Stg:Signal)-[:FROM_SOURCE]->(src:Dim:Source)
        RETURN src.name AS source, s.tier AS tier, count(*) AS rows
        ORDER BY rows DESC
    """)
    _mass = cypher("""
        MATCH (s:Stg:Signal {metric: 'body_mass'})
        RETURN s.created_at AS at, s.value AS kg
        ORDER BY at DESC LIMIT 5
    """)
    mo.vstack([
        mo.md("**Rows by source and tier:**"),
        mo.ui.table(_tiers.to_dicts(), selection=None),
        mo.md("**The payload at work — latest body-mass readings:**"),
        mo.ui.table(_mass.to_dicts(), selection=None),
    ])
    return ()


@app.cell
def posterior_header(mo):
    mo.md("""
    ## 5 — Posteriors: belief, with its provenance

    *What's asking:* what does the system currently believe, and should the
    belief itself be believed? *How:* one `(:Fct:Posterior)` per (measure, day)
    — the daily snapshot of a seed-pinned Stan fit, carrying its own
    diagnostics. *How to read:* the interval is the honest part; a wide one is
    visibility of uncertainty, not a claim. Hollow/red rows are fits **the
    sampler itself distrusts** (R̂, ESS, divergences) — stored as facts about
    the sampler, never read as results. *What would change it:* every sync
    re-fits on cumulative data; intervals tighten as days accumulate, and the
    per-day history of this chart becomes the evolving-distribution view.
    """)
    return ()


@app.cell
def posterior_forest(alt, loaders, mo, pl, theme):
    _post = loaders.posteriors()
    if _post.is_empty():
        _view = mo.md("*No posterior snapshots yet — run `flow sync`.*")
    else:
        _last = _post.filter(pl.col("day") == _post["day"].max()).filter(
            pl.col("measure").str.starts_with("adherence:")
        )
        _base = alt.Chart(_last)
        _view = mo.ui.altair_chart(
            (
                _base.mark_rule(strokeWidth=2).encode(
                    x=alt.X("ci_low:Q", title="completion rate (90% CI)",
                            scale=alt.Scale(domain=[0, 1])),
                    x2="ci_high:Q",
                    y=alt.Y("measure:N", title=None),
                    color=alt.Color(
                        "trusted:N",
                        scale=alt.Scale(domain=[True, False],
                                        range=[theme.accent, theme.bad]),
                        title="sampler trusts it",
                    ),
                )
                + _base.mark_point(filled=True, size=70).encode(
                    x="mean:Q", y="measure:N", color="trusted:N"
                )
            ).properties(height=180)
        )
    _view
    return ()


@app.cell
def knowledge_header(mo):
    mo.md("""
    ## 6 — The knowledge layer: the practice examining itself

    This is the part of the graph that makes the system more than telemetry.
    Everything the reviewing agent concludes — reviews, interpretations,
    prescriptions, transformations, hypotheses, opened gates, development
    proposals — is captured under a **closed vocabulary** (`taxonomy.py`),
    promoted append-only into the archive, and lands here linked to the
    calendar and to the measures it concerns.

    *Why it matters:* next month's review can ask what last month's concluded
    — and whether the one change it prescribed was followed, and worked. That
    loop is a query, not a memory:

    ```cypher
    MATCH (p:Meta:Prescription)-[:PRESCRIBED_BY]->(r:Meta:Review)
    OPTIONAL MATCH (o:Stg:Note)-[:OUTCOME_OF]->(p)
    RETURN r.name, p.change, o.note
    ```
    """)
    return ()


@app.cell
def knowledge_state(cypher, mo):
    _entities = cypher("""
        MATCH (n) WHERE n:Meta OR n:Interpretation OR (n:Note AND n:Stg)
        RETURN n.entity_type AS type, count(*) AS captured
        ORDER BY captured DESC
    """)
    _loops = cypher("""
        MATCH (p:Meta:Prescription) WHERE NOT (:Stg:Note)-[:OUTCOME_OF]->(p)
        RETURN p.name AS open_prescription, p.change AS change
    """)
    _blocks = [
        mo.md("**Captured so far, by type:**"),
        mo.ui.table(_entities.to_dicts(), selection=None),
    ]
    if _loops.is_empty():
        _blocks.append(mo.md(
            "*No open prescriptions — the first weekly review will create "
            "one, and next week's review will be asked what became of it.*"
        ))
    else:
        _blocks.append(mo.ui.table(_loops.to_dicts(), selection=None))
    mo.vstack(_blocks)
    return ()


@app.cell
def register_header(mo):
    mo.md("""
    ### The DevProposal register

    The platform's own roadmap lives *in* the graph: each proposal carries the
    limitation that motivated it and an explicit **gate** — the condition under
    which it becomes worth building. `flow brief` surfaces them when gates are
    reached; the quarterly review walks them. "Later" is a queryable condition,
    not a memory.
    """)
    return ()


@app.cell
def register(cypher, mo):
    _df = cypher("""
        MATCH (p:Meta:DevProposal)
        RETURN replace(p.name, 'devproposal:2026-08-18:', '') AS proposal,
               p.gate AS gate, p.status AS status
        ORDER BY proposal
    """)
    mo.ui.table(_df.to_dicts(), selection=None)
    return ()


@app.cell
def gds_header(mo):
    mo.md("""
    ## 7 — Structure through GDS: visibility, never inference

    Two **standing projections** are refreshed on every sync and can be
    streamed by anyone (the agent does it through read-only Cypher):
    `flow_cocompletion` (which modes complete on the same days) and `flow_days`
    (days as feature vectors). *How to read:* these are *observed overlaps* —
    which modes travel together — never facilitation claims. The inference
    versions (regime clustering, the co-occurrence probit) sit gated in the
    register above until the data can carry them.

    ```cypher
    CALL gds.nodeSimilarity.stream('flow_cocompletion')
    YIELD node1, node2, similarity
    RETURN gds.util.asNode(node1).name AS a,
           gds.util.asNode(node2).name AS b, similarity
    ```
    """)
    return ()


@app.cell
def gds_stream(cypher, mo):
    _co = cypher("""
        MATCH (a:Dim:Activity)-[r:CO_COMPLETES]->(b:Dim:Activity)
        RETURN a.name AS mode, b.name AS travels_with,
               round(r.similarity, 2) AS jaccard
        ORDER BY jaccard DESC, mode
    """)
    _days = cypher("""
        MATCH (a:Enr:Day)-[s:SIMILAR_DAY]->(b:Enr:Day)
        RETURN a.date AS day, b.date AS most_like, round(s.score, 2) AS score
        ORDER BY day, score DESC
    """)
    if _co.is_empty():
        _view = mo.md("*No co-completion structure yet — no two modes have "
                      "completed on the same day.*")
    else:
        _view = mo.vstack([
            mo.md("**Modes that travel together (Jaccard over shared "
                  "completed days):**"),
            mo.ui.table(_co.to_dicts(), selection=None),
            mo.md("**Which past day most resembles which** — the agent's "
                  "'last time it looked like this' retrieval:"),
            mo.ui.table(_days.to_dicts(), selection=None),
        ])
    _view
    return ()


@app.cell
def outro(mo):
    mo.md("""
    ## What to take away

    - **One source.** Every surface — report, evidence, dashboard, these
      notebooks, the agent's own answers — reads this graph and only this
      graph.
    - **Refusals are stored.** A measure below its gate is a row saying so; a
      distrusted fit is a row saying so. The graph never looks more certain
      than the system is.
    - **The knowledge layer is the compounding part.** Telemetry accrues by
      itself; judgement accrues only because reviews write back — and every
      write is validated against a closed vocabulary before it can become
      permanent.

    *The full account of the theory this implements is
    `docs/08-creative-systems-practice.md`; the operational cookbook is
    `docs/09-agent-runbook.md`.*
    """)
    return ()


if __name__ == "__main__":
    app.run()
