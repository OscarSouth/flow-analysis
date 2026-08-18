# Platform migration — status and remaining steps

Moving this project onto the local data platform used by
`~/dataplatform-template` and `~/portfolio-analysis`: Dagster + Neo4j + Polars +
marimo, six MCP servers, strict mypy, ruff, hypothesis.

Full reasoning, the verdict on whether it was worth doing, and the target
architecture live in the plan:
`~/.claude/plans/evaluate-this-conversation-with-dapper-creek.md`

## Why, in one paragraph

Not a data-engineering necessity — 5,312 rows need none of this. It is worth
doing for **agent-queryability** (the `neo4j` MCP replaces the throwaway Python
scripts previously written to inspect data), **static checking this repo entirely
lacked**, **real orchestration for five sources** instead of a hand-rolled
try/except loop, and **one mental model across three repos**. The weakest argument
is graph shape: flow data is largely tabular, and the one genuinely graph-shaped
relation — practice → reception — is forbidden by design.

## Decisions that constrain everything downstream

| | |
|---|---|
| **Neo4j** | Derived store. `data/*.jsonl` stays the truth. |
| **Rebuildability** | Purge + rematerialize must reproduce the graph with **no API calls**. |
| **Docker** | **Always required** (2026-08-18): sync materialises the whole DAG; analysis reads only the graph. |
| **Ports** | 7476 / 7689 / 3001 / 2719 — offset so this can run alongside the other two projects, which collide with each other on 7475/7688/3000. |

## Progress

- [x] **0. Rename** `~/trello-automation` → `~/flow-analysis`. Package still
      `trello_flow` (renamed in step 3). Claude Code memories copied to the new
      project key. `.venv` rebuilt — venvs bake absolute paths.
- [x] **1. Scaffolding.** `pyproject.toml` (mypy strict, 15 ruff rule sets,
      pytest markers, `[tool.dagster]`), `Justfile`, `docker-compose.yml`,
      `.mcp.json`, `dagster_mcp.py`, `.python-version`. `CLAUDE.md` merged —
      platform discipline plus every Butler constraint and analytics rule from the
      previous contract, nothing dropped.
- [x] **2. Green under the new tooling.** `just check` over the *existing* code —
      50 mypy errors and 465 ruff findings to zero, 123 tests still passing, no
      behaviour changed. What surfaced: `ranked`/`runner_up` shadowed between the
      H1 and H2 blocks of `preregistered`, `source` rebound from `GitHubSource` to
      `YouTubeSource` inside one function, a dead loop in `grid_frame` appending
      `None` per row, and `zip()` without `strict=` correlating a possibly
      truncated pair. JSON boundaries now unwrap through `util.json_object` /
      `json_array`, which raise on shape rather than casting blind. 88 docstrings
      written. **Known, deliberately left:** the published dashboard emits no
      `<meta charset>`, so en dashes mojibake when the file is opened directly —
      pre-existing, and a behaviour change rather than a lint fix.
- [x] **3. Package rename** `trello_flow` → `flow_analysis`, and Layer B extracted
      into `metrics/` (`diagnostics`, `reception`, `embodiment`, `frames`,
      `calendar`). Still no Dagster. Two things the move forced rather than
      merely relocated:
      - `reception.summarise` and `embodiment.summarise` each carried a lazy
        `from .. import store` inside the function body, so Layer B was reaching
        into Layer C. `rows` is now a required argument and the four callers pass
        it. **`tests/test_layering.py` walks the AST of `metrics/` and fails on
        any import of a fetching or persisting module**, including the
        inside-a-function form the violation actually took.
      - The flow-day calendar left `util.py` for `metrics/calendar.py`, so the
        04:00 boundary is defined in the layer that owns it and `util` is back to
        being genuinely small.
      `TRELLO_FLOW_DATA_DIR` is now `FLOW_ANALYSIS_DATA_DIR`. Equivalence held:
      `flow report` byte-identical, the fixture dashboard identical but for its
      generated timestamp, two syncs adding zero rows.
- [x] **3b. Layer B made actually pure.** Step 3's guard was passing on a false
      negative: it checked *direct* imports against a **blacklist**, and the
      blacklist omitted the only two modules where the mixing lived. Measured at
      the time: `metrics.diagnostics` reached `flow_analysis.store` through
      `model.py`, and `metrics.reception` reached `httpx` through `signals.py`.
      `signals.py` also carried a third copy of the lazy `from . import store`
      already fixed twice in step 3.
      - `signals.py` split three ways: `tiers.py` (vocabulary, imports nothing),
        `sources/forum.py` (Layer A), `metrics/production.py` (Layer B, `rows`
        now required). `model.py` → `metrics/grid.py`, with `build_rows(cfg)`
        becoming `fold_rows(cfg, cards, actions)` — the shape a Dagster asset
        needs, since an asset that reaches into the store bypasses lineage.
        `cli._grid(cfg)` does the loading, in the layer that should.
      - `tests/test_layering.py` rewritten: an **allowlist** of what `metrics/`
        may import (fails closed) plus a **transitive** check that importing any
        Layer B module never loads `store`, `sources` or `httpx`. Both breach
        forms — top-level and lazy-in-function — were planted and confirmed to
        fail the guard.
      - Tests follow the seam: `test_signals.py` → `test_forum.py` +
        `test_production.py`, `test_model.py` → `test_grid.py`.
      163 tests. `flow report` still byte-identical to the pre-step-2 baseline.

- [x] **3a. The suite was date-dependent.** Found while starting 3b, unrelated to
      it. `fixtures.synthesize` is seeded, but `end` defaults to *yesterday*, so
      the weekday modifiers slide against a fixed random stream as the calendar
      advances. `Express` sat at `never_start: 0.50` — a coin flip between
      allocation and capacity failure — so
      `test_allocation_and_capacity_are_distinguished` held only when `end`
      landed on a Sunday: **it passed on Mondays and failed the other six days**,
      measured at 4/28 end-dates. Two fixes: `Express.never_start` → 0.30 so the
      split is present by design, and tests pin `fixtures.REFERENCE_END`
      (deliberately a Wednesday — pinning to a Sunday would have hidden it).
      `test_the_failure_split_survives_every_weekday` sweeps a full week and
      fails if the old value is restored. Fabricated data moved; real-data
      `flow report` is unchanged.

- [x] **4. JSONL IO manager + raw assets.** Fetching runs under Dagster.
      `resources/` (one `ConfigurableResource` per origin), `io/` (the
      `JsonlIOManager` and the stream table), `assets/raw.py` (six assets), and
      `definitions.py`. **`just validate` passes** — it was red for the whole
      migration until now.
      - **Equivalence proved by construction, not by eye**: both paths were run
        into their own throwaway directory seeded from the real archive, and the
        three streams hashed. Identical on all three, with `observed_at`
        normalised out — card rows carry the wall-clock instant they were seen,
        so two runs seconds apart legitimately differ there and nowhere else.
        `data/` was untouched throughout (`store.redirect`).
      - The IO manager writes **rows before watermark**. Reversed, a failed write
        would leave `state.json` claiming coverage the archive lacks, and
        `integrity()` reads the watermark — so the gap would report as OK.
        `test_io_manager.py` pins the ordering with spies.
      - `flow sync` materialises **in this process** rather than shelling out to
        `dagster asset materialize`: the CLI keeps its summary and its non-zero
        exit, which scripts depend on, and the run is still recorded in
        `.dagster_home` so it appears in `dagster dev` and to the MCP.
      - `sync.run` was first split into `fetch_actions` / `fetch_cards`, which
        fetch and return without writing, so the CLI and the asset share one
        implementation of the stateful newest-first walk.
      179 tests.
- [x] **5. Neo4j** — schema, `dim_day` (calendar + `NEXT` chain), `stg`, `enr`,
      `fct`. `graph/schema.py` declares six uniqueness constraints and two
      indexes, applied by `just up`; `io/neo4j_io_manager.py` runs each asset's
      co-located `cypher_template` / `post_cypher` / `load_cypher`.
      - **Rebuildability is proved, not asserted.**
        `tests/test_rebuildable.py` purges the entire graph, rebuilds it, and
        compares node and relationship digests — **with `httpx.Client` patched to
        raise**, so a rebuild that reached for an endpoint fails the test rather
        than passing quietly. A second test rematerialises twice and checks
        nothing duplicated, which is what the uniqueness constraints buy.
        Marked `integration`; `just check` stays offline, `just test-integration`
        runs them.
      - **`enr` is not what CLAUDE.md sketched, on purpose.** Latency, pull rank,
        interleaving and failure kind are computed by the fold and already sit on
        `(:Stg:FlowRow)`; recomputing them would be a second implementation of
        the same thing. What the layer holds instead is what a row cannot know
        alone — a day's adherence across all five modes beside that day's
        production, which is `adherence_without_production` as a Cypher question.
      - `fct_measures` stores every diagnostic **including the refusals**, each
        with the N it had and the N it needed. A measure that cannot be evaluated
        yet is a fact about the practice's age; dropping it would make the graph
        look like the question was never asked. On 2 days of history, 7 of 9
        refuse — which is the discipline working.
      - Nested values (per-mode medians, the lag profile) are stored as JSON
        strings: Neo4j properties are scalars, and flattening would either lose
        the shape or invent node types nothing joins on.
      185 tests + 2 integration.
- [x] **6. Re-point the surfaces.** The graph is the sole analysis source
      (decision 2026-08-18): `report`, `evidence`, `publish` and the notebook
      read Neo4j through `graph/loaders.py` — the one place Cypher becomes a
      frame. The fixture path still folds from its redirected throwaway store,
      because fabricated data must never pass through the real graph.
      - **Handover verified, not assumed**: both paths run on identical data,
        every surface compared as canonical JSON — grid, production, report,
        diagnostics, reception, embodiment, the full evidence pack. All
        equivalent, and `tests/test_repoint_equivalence.py` holds the comparison
        open permanently (integration-marked).
      - Two live bugs caught by the comparison: `stg_signals` was **shadowing
        YouTube's native `day`** with the computed flow-day (now stored as
        `day` + `flow_day`, calendar links on `flow_day`); and Float64 coercion
        turned integer counters into floats ("stars 116.0") — `value` is now
        `pl.Object` on the write side and `signal_dicts()` bypasses polars so
        each node's own types survive verbatim.
      - The full scalar payload (32 fields) now rides on `(:Stg:Signal)` as
        sparse properties, queryable in Cypher.
      - **Docker is now always required** (decision 2026-08-18): `flow sync`
        materialises the entire DAG — raw through fct — so the graph is current
        the moment a sync finishes. Graph down ⇒ analysis fails loudly with the
        fix named, exit 1; it never reports zeros that look like a stopped
        practice.
- [x] **6b. The knowledge layer.** The graph now accumulates the agent's own
      record, not just telemetry. Pipeline: memory MCP working set
      (`.claude/memory.jsonl`, mutable, gitignored) → `raw_agent_memory`
      (snapshot, content-hash ids) → `data/notes.jsonl` (append-only truth) →
      `stg_knowledge` / `stg_knowledge_links` → `(:Meta:*)`,
      `(:Fct:Interpretation)`, `(:Stg:Note)`, linked to the calendar and the
      measures they concern.
      - **`taxonomy.py` is the closed vocabulary**: eight entity types with
        required fields (as `key: value` observation lines), six relation
        types, validated at capture — an unknown type or a missing field fails
        the snapshot loudly before anything reaches the archive. Deliberate
        deviation from raw-verbatim: the memory file is agent-authored, and a
        taxonomy mistake is cheap in the working set, permanent after it.
        `Transformation.kind` excludes R-membership by construction — the five
        modes are fixed by decision; only their semantics can change.
      - Latest state wins in the graph (MERGE by name); every state an entity
        passed through stays in the archive (content-hash rows).
      - The DevProposal register is live: HMM regimes, STM/LDA topics, three
        GDS items and the co-occurrence probit are graph entities with explicit
        gates, seeded through the real capture path end to end.
      196 offline + 9 integration tests.

- [x] **7. `flow brief`.** The deterministic conversation opener: staleness
      (from the Dagster instance's own materialisation records), reviews due
      (`(:Meta:Review)` vs cadence, anchored on the epoch when never run),
      deltas since the last look, **newly answerable measures** (ok without a
      `GateOpened` record), and open loops (prescriptions without outcomes,
      unconfirmed transformations, registered DevProposals). Depth ∈ {glance,
      review, deep} from a fixed table with `because` — same state, same depth,
      every session. Pure Layer B (`metrics/brief.py`), pinned by table tests.
      First live run correctly said `deep`: two measures newly answerable on
      day three.

- [x] **8. The steering.** CLAUDE.md gained the interaction contract: the two
      modes (platform development / practice interaction) with their R/T/E per
      mode, the discriminator, the DevProposal crossing, prescribed depth,
      the early-review stance, and the full capture protocol under
      `taxonomy.py`. The three review commands rewritten: weekly (T-level,
      closes last week's prescription loop), monthly (E_L, Bayesian verdicts),
      quarterly (**re-aimed at R-semantics** — the five are fixed by decision;
      what stays open is whether each mode's substantive content still matches
      what is done and valued — plus the DevProposal walk and the whitepaper
      drift check). Each command ends by capturing its Review, Interpretations
      and Prescription through the memory MCP.

- [x] **9. The rolling Bayesian layer (CmdStanPy).** Four pre-registered Stan
      models in `models/` (priors in the files, dated); `metrics/inference/`
      (prep / engine / summarise, pure and offline-tested); `fct_posteriors`
      snapshots daily into `(:Fct:Posterior {measure, day})` with R̂, ESS,
      divergences and `trusted` as first-class properties.
      - **All-Bayes from the start** (decided 2026-08-18): H1–H3 judged as
        posterior probabilities of their published claims with their published
        margins; verdicts four-way, gated on N *and* sampler diagnostics.
        First live snapshot: all three `not testable yet` with posteriors
        visible — 9 of 19 rows untrusted at N=2–3, which is the sampler being
        honest about two-observation survival fits.
      - **Calibration held to algebra**: the integration suite requires Stan to
        reproduce the conjugate Beta posterior within 0.01, and the hierarchy
        to visibly pool a 2-observation mode toward the practice mean.
      - Survival treats `never_started` as right-censored at the 22-hour day —
        the plateau IS the allocation-failure probability; the cascade model
        links stages through cumulative intensities over 28-day windows only,
        preserving the reception exclusion.
      - `flow report` and the evidence pack now carry the posterior snapshot;
        `just install-cmdstan` provisions the toolchain.


- [x] **10. GDS, adopted deliberately.** Classed under the repo's own
      discipline — **visibility now, inference gated**. Visibility-class assets:
      `enr_activity_similarity` (which modes travel together — Jaccard over
      shared completed days) and `enr_day_similarity` (which past day most
      resembles which — KNN over enriched features, the agent's "last time it
      looked like this" retrieval). Pattern: standing projections
      (`graph/projections.py`, dropped and re-projected on refresh so a stale
      projection cannot answer for yesterday's structure) → `gds.*.stream` →
      frame → the IO manager, with a new `pre_cypher` hook clearing derived
      edges wholesale before each write. The agent streams against the standing
      names through read-cypher; projection lifecycle stays platform-side
      because the MCP is read-only by design. Inference-class uses (regime
      clustering, knowledge-network centrality, embeddings) are registered
      DevProposals with explicit gates, queryable in the graph.

- [x] **11. The whitepaper.** `docs/08-creative-systems-practice.md` v0.1.0 —
      the practice-led research account of the whole system, standalone and
      abstract of any one practitioner's data: notation guide with a written
      intuition under every core formula (verified against the source papers);
      the full CSF exposition including the meta-level septuple; the
      rate-limited extensions; the agent-as-T_L identification and platform
      development as meta-transformation; the measurement architecture; the
      rolling Bayesian layer and its gated verdicts; the staged-model register;
      a formal revision log (git handles versioning underneath). Errata applied
      to `docs/06`: the enumeration interpreter is ⟪R,T,E⟫◊ (was transposed),
      and the septuple's two interpreters are now stated. Continues South 2016
      and 2018, which applied Wiggins through Candy's methodology.

- [x] **12. Initial state (2026-08-19).** The steering was audited against a
      fresh session and closed: `CLAUDE.md` §2b records the migration as
      complete, §9's MCP table matches the interaction contract (memory =
      practice capture; serena = dev memory; the standing GDS projections and
      the marimo/dagster server semantics stated), and the contract gained the
      session bootstrap, the delivery policy (artifact = summary dashboard;
      notebooks = literate deep dives, handed as direct `?file=` links) and the
      **self-healing protocol** (recognise → Observation → diagnose → propose →
      confirmation gate → Transformation). `docs/09-agent-runbook.md` carries
      the measure registry, verdict semantics, a live-verified Cypher cookbook
      and the procedures. `flow brief` gained health signals (failed sync
      assets, archive↔graph drift, persistent untrusted posteriors), each
      forcing ≥ review depth. The literate notebook layer landed:
      `notebooks/README.md` (the contract), `flow.py` upgraded with the
      narrative arc and an Inference chapter (posterior forest, Kaplan-Meier
      survival with the allocation plateau, gated evolving-posterior view), and
      `graph.py` — the guided tour of the graph, knowledge layer and GDS
      projections, every query executed live before inclusion. Whitepaper §9
      expanded with the technology-to-theory mapping (still v0.1.0). 223
      offline + 12 integration tests.

## Non-negotiables while migrating

**Slices within each step; each step lands whole.** `just check` green at the end
of every step, never only at the end of the migration. A package rename cannot be
decomposed further without leaving the tree importing itself two ways — that is
the one standing exception to the vertical-slice rule, and it is scoped to this
migration only.

**The 123 existing tests must port and pass.** They pin invariants that are one
line each and silently corrupting if lost:

- dedupe-on-id in the append-only store
- the tier filter protecting `production_by_day`
- `store.redirect` isolating fixtures from `data/`
- GitHub traffic skipping the current (still accumulating) day
- the YouTube 3-day settle window
- the epoch boundary, inclusive of the epoch day
- both strength-workout spellings

**Equivalence checks** at the end: `flow report` output matches pre-refactor on the
same data, every gate refusing at the same threshold; two consecutive syncs add
zero rows.

## Setup on a fresh machine or session

```bash
brew install just          # the Justfile is the entry point
uv sync --all-groups
just up                    # Neo4j on 7476/7689
just check                 # typecheck + lint + test
```

MCP servers are read from `.mcp.json` at session start — reopen Claude Code at
`~/flow-analysis` for them to become available.
