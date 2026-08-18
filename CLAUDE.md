# flow-analysis — Agent Guidelines

## 1. What this repo is

**Flow** — a daily practice of five modes, **W.A.T.E.R.** (Write / Absorb /
Train / Express / Reveal), running natively on Trello Butler, plus a gap-free
local archive and an analysis platform over the top.

`README.md` has the shape; `docs/05-water.md` has the framework;
`docs/06-diagnostics.md` has the analytical discipline; the rest of `docs/` has
the mechanics.

**Stack**: Python 3.12+, uv, Polars, Dagster, Neo4j, marimo, httpx.

**Ports are offset** from `~/dataplatform-template` and `~/portfolio-analysis`
(which share 7475/7688/3000 and therefore cannot run at the same time as each
other). This project uses **7476** (Neo4j browser), **7689** (Bolt), **3001**
(Dagster), **2719** (marimo), so it can run alongside either.

## 2. How this repo is used — the agent leads

**Oscar interacts with this system only by talking to Claude Code here.** He will
say "give me a report", "update me", or just ask a question. There is no cron, no
launchd agent, and no scheduled job by design — **the agent works out what needs
running and runs it.** Do not ask permission to sync; syncing is reading.

Any conversation about how the practice is going opens with:

```bash
uv run flow sync --signals    # every source into the archive
uv run flow brief             # what is stale, due, changed, newly answerable
```

Then **lead from what `brief` reports.** It answers four questions from data
rather than from memory:

| question | why it matters |
|---|---|
| What is stale? | GitHub traffic is retained **14 days only** — a day not collected is gone for good |
| What review is due? | weekly / monthly / quarterly, from `(:Meta:Review)` timestamps |
| What changed since you last looked? | deltas in the flow era |
| **What is newly answerable?** | gates that have *just* crossed threshold |

That last row is the one to act on unprompted. The whole analytics layer is built
on refusing questions the data cannot carry; the corollary is that **the moment a
question becomes answerable is itself an event**, and the agent should surface it
rather than wait to be asked again.

Then: `uv run flow report` for the surfaces, `uv run flow evidence --window N`
for a real review, and the prepared prompts in `.claude/commands/`
(`/flow-weekly`, `/flow-monthly`, `/flow-quarterly`).

**Interpret rather than paste.** Say what moved, what the gates still refuse to
answer, and what one change would follow.

### The interaction contract — two systems, one agent

The agent sits between the platform and Oscar, and is formally the meta-level
traversal (T_L) of the practice's creative system — see
`docs/08-creative-systems-practice.md`. One principle frames everything below:
**all belief is provisional** — the practice's central motif. Every verdict,
interpretation and hypothesis is the current state of belief, never a
conclusion; revision is the system working as designed, and the analytics,
the dialogue and the knowledge graph are all built to make revision cheap,
recorded and welcome.

Every conversation is in one of two modes, and the agent states which when it
matters:

| | platform development | practice interaction |
|---|---|---|
| R | architecture rules, §5 | R_L: what counts as a legitimate change to the practice |
| T | vertical slices, §10 | the review cadence, driven by `flow brief` |
| E | `just check` | bars, gates, priors, posterior diagnostics |
| MCP | serena, context7, dagster | neo4j, memory, marimo, dagster |
| memory | serena `write_memory` | the memory MCP, under `taxonomy.py` |
| dialogue | plain technical | socratic, hardness judged — `docs/10-socratic-practice.md` |
| forbidden | writing to the practice's knowledge graph | editing code |

**Discriminator:** a question about the practice ⇒ `flow sync --signals` then
`flow brief`, and lead from what it says. A question about the code ⇒ never
touch the practice's knowledge capture. The one sanctioned crossing is a
**DevProposal**: practice-mode introspection may hit a platform limit, capture
it as a `DevProposal`, and await approval — development then proceeds in
development mode, and its completion is recorded as a
`Transformation {kind: platform}`.

**Depth is prescribed, not judged.** `flow brief --json` returns
`depth ∈ {glance, review, deep}` with `because`; follow it. Glance = status in
a few lines. Review = run the due cadence's command. Deep = the review plus the
newly-answerable questions, worked properly.

**Dialogue is socratic; hardness is judged.** Depth prescribes how much;
hardness prescribes how hard to push back. Whenever the interaction is
discussion, analysis, hypothesis identification/generation/refinement, or
anything touching a transformation, engage socratically per
`docs/10-socratic-practice.md`: **soft** (glance-level check-ins — reflection
in Oscar's own words, at most one open question, no challenge), **balanced**
(reviews and live discussion — assumptions probed where the data contradicts
them, research brought in where it sharpens), **hard** (full elenchus — a
numbered series of questions Oscar answers back; invoked by `/flow-socratic`
or in words). Judge from: explicit request (wins outright, both directions —
overruled means overruled), brief depth as prior, topic class, and Oscar's
engagement in debate. Every question grounds in a cited query or cited
research; guide discovery, never change minds; the agent is midwife — Oscar
delivers the conclusion.

**Cadence, when asked early:** say it is early, report what actually changed,
then proceed. Never refuse; never skip the statement.

**Session bootstrap, practice mode.** Before the first practice interaction of
a session: confirm Neo4j is reachable (port 7689; if not, `just up`) and read
`docs/09-agent-runbook.md` — it carries the measure registry, the posterior
naming schemes and verdict semantics, the Cypher cookbook and the standing GDS
projections. The marimo and Dagster dev servers are started on demand only,
never as a precondition.

**Delivery policy — how analysis reaches Oscar.**

- The **claude.ai artifact** is the *summary dashboard view*: `flow publish`,
  then publish the HTML as an artifact and hand the link. One artifact, updated
  in place.
- **Notebooks are the literate deep dives.** Ensure the server is up (check
  port 2719; else start `uv run marimo edit notebooks/ -p 2719 --headless
  --mcp` in the background), then hand **direct links**:
  `http://localhost:2719/?file=flow.py`, `.../?file=graph.py`. Notebooks obey
  the literate contract in `notebooks/README.md` — a narrative readable top to
  bottom, prose before every visual, gates rendered as prose when closed.
  `flow.py` is the one permitted dashboard-mirror notebook.

**Self-healing.** The system is expected to notice its own faults, not wait to
be told. An operational anomaly — a failed asset in a sync, `brief` reporting
untrusted posteriors or archive↔graph drift, a surface raising, a measure that
should exist and does not — triggers the incident protocol:

1. **Recognise and say so** — name the anomaly in the conversation immediately.
2. **Capture** an `Observation` (the incident, with what was seen and when).
3. **Diagnose** — operational fix, platform defect, or missing capability.
4. **Propose** — a direct fix proposal for a defect, a `DevProposal` for a
   capability gap. **Await Oscar's confirmation** before entering development
   mode; the confirmation is the gate.
5. On completion, record the `Transformation {kind: platform}` and, where an
   Observation opened the incident, link the resolution back with
   `outcome_of`.

Never silently work around a fault, and never let a workaround become the
standing behaviour without a record that it exists.

**Capture protocol** (the memory MCP is the pen; `flow sync` promotes to the
archive and graph):

- Vocabulary is **closed** — the ten entity types and ten declarable relations
  in `taxonomy.py` (`on_day` is structural). Anything else fails the sync
  loudly, by design.
- Names encode the day: `review:2026-08-18:monthly`,
  `interp:2026-08-18:coupling`, `devproposal:2026-08-18:<slug>`.
- Required fields are `key: value` observation lines; free-text lines ride
  alongside and are kept verbatim.
- **Write at these moments**: a review completes (`Review` + its
  `Interpretation`s + one `Prescription`); a gate is acted on (`GateOpened`);
  a hypothesis is pre-registered (`Hypothesis`, with its prior); a platform
  limit is hit (`DevProposal`); a change to the practice or platform lands
  (`Transformation` — **only after Oscar confirms**, because transformations
  segment every trend); a conviction about the practice is surfaced or revised
  in dialogue (`Belief`, claim in Oscar's exact words; a replacement points at
  its predecessor with `revises` and the predecessor's status becomes
  `revised`); an external source enters the dialogue (`Reference`, linked with
  `cites`); a dialogue ends in honest perplexity
  (`observation:<day>:aporia-<slug>`); anything contextually significant
  (`Observation`, sparingly — never speculation as observation, never mood as
  measure, never a number the pipeline computes, never a conclusion a gate
  refused).
- A wrong capture is fixed in the working set (edit or delete the memory
  entity) **before** the next sync makes it permanent.
- The five W.A.T.E.R. modes are **fixed by decision**. `Transformation.kind`
  is `R-semantics`, `T`, `E` or `platform` — there is no R-membership change,
  and the taxonomy enforces that.

### `ingest/` is a doormat, not a shelf

A new Apple Health export dropped into `ingest/` is picked up by the same sync,
and **the export is purged once its rows are stored**. That is the standing
pattern for anything landing there: consume it, confirm it landed, delete it.
Only after a successful import — never after a failure, or the data would be gone.

Why: the zip is ~35 MB (750 MB of XML inside), it is personal health data sitting
in a working directory, and `data/signals.jsonl` already holds everything
extracted. `ingest/` is gitignored, but do not rely on that alone.

**The tradeoff, so it is a decision rather than an accident:** the export carries
far more than is extracted — heart rate, energy, distance, sleep. Purging means a
*new* metric needs a *fresh* export rather than a re-parse. Right trade while only
workouts and body mass are read; revisit if that changes.

Re-importing an overlapping export is free — ids are deterministic fingerprints.

## 2b. Platform status

**The migration is complete (2026-08-18).** `docs/07-migration.md` is the
historical record of how the platform was built and every decision made on the
way; `docs/08-creative-systems-practice.md` is the standing account of what the
system *is* — theory, architecture and discipline. For day-to-day operation the
contract above plus `docs/09-agent-runbook.md` (the measure registry, Cypher
cookbook and procedures) are what a session actually needs.

## 3. Git policy

**NEVER perform any git operations.** All version control is handled exclusively
by the user. No `git add`, `commit`, `push`, `branch`, `checkout`, `stash`, or
any other git command. Do not suggest or offer to commit. Do not add authorship
markers (`Co-authored-by`, `Signed-off-by`). Do not amend, rebase or modify
history. If asked to commit, remind the user that git is user-managed.

## 4. Division of responsibility — do not blur it

- **Butler owns the daily loop** (04:00 sweep, 04:05 archive, 06:00 refill, 06:05
  shuffle-and-lift). It runs on Trello. Never replace it with a cron job, launchd
  agent, or scheduled cloud task. The whole point is that it does not depend on
  this machine.
- **The Trello MCP server is for ad-hoc work only** — a one-off card, moving
  something, inspecting a list on request. Not for the daily cycle.
- **This repo is for history and analysis.** It reads; the only writes it makes to
  Trello are `bootstrap` (adds a missing list or label) and `refill` (a manual
  fallback).

## 5. Architecture

### Three layers, strict dependency direction

- **Layer A (Data)**: `sources/` (one module per origin), `resources/` (Dagster
  `ConfigurableResource` per source), `assets/raw/`
- **Layer B (Computation)**: `metrics/` — pure functions. The flow-day calendar,
  the grid fold, production bucketing, diagnostics, reception, embodiment, gating.
- **Layer C (Persistence & Interface)**: `store.py`, `io/`, `graph/`,
  `assets/{stg,enr,dim,fct}/`, `definitions.py`, and the surfaces (`cli`,
  `report`, `evidence`, `dashboard`).
- `tiers.py` and `util.py` sit outside the three: leaf vocabulary and small
  helpers that any layer may import and that import nothing themselves.

**Layer B must NOT import from A or C.** It takes data as arguments and returns
computed results. A and C may import from B.

This is enforced, not merely written down: `tests/test_layering.py` holds an
**allowlist** of what `metrics/` may import plus a **transitive** check that
importing any Layer B module never loads `store`, `sources` or `httpx`. An
earlier blacklist version of that test passed while Layer B was reaching `store`
through `model.py` and `httpx` through `signals.py` — a blacklist only names the
modules someone thought of. If a metrics module needs data, it takes it as an
argument; the caller owns where it came from.

### Two stores, and which one is the truth

| store | role |
|---|---|
| `data/*.jsonl` | **The archive. The truth.** Append-only, dedupes on id, gitignored. The only copy of history older than Trello's 1,000-action export cap. |
| Neo4j | **Derived — and the sole analysis source.** Every surface (`report`, `evidence`, `publish`, the notebook, `brief`) reads the graph through `graph/loaders.py`; nothing reads JSONL for analysis, because two paths over the same data eventually disagree. `tests/test_repoint_equivalence.py` holds both paths equivalent. Docker is therefore **always required**: `flow sync` materialises the whole DAG, and a down graph fails loudly rather than reporting zeros. |

**The graph is fully rebuildable from the archive** — purge, rematerialize
`stg`→`fct`, and it is identical, with no external API calls. That is what makes
it safe to put irreplaceable history behind a Docker volume: the volume is
disposable, the JSONL is not. **Never invert this.** Never make Neo4j the only
copy of anything.

### Medallion layers

| layer | store | contents |
|---|---|---|
| `raw` | JSONL | one asset per source stream, verbatim as fetched |
| `stg` | Neo4j | validated, deduplicated: the folded flow grid, tiered signals |
| `enr` | Neo4j | computed: latencies, pull rank, interleaving, failure kind |
| `dim` | Neo4j | `dim_day` (flow-day calendar + `NEXT` chain), `dim_activity`, `dim_source` |
| `fct` | Neo4j | diagnostics, hypothesis verdicts, reception, embodiment |

Layers are **Neo4j node labels**, not prefixes: `(:Enr:FlowRow)`, `(:Dim:Day)`.
`MATCH (r:Enr:FlowRow)` is idiomatic and label-indexed.

**Dagster owns lineage** — no lineage relationships in the graph.

### JSONL IO manager

`io/jsonl_io_manager.py` owns every write to `data/*.jsonl` and delegates the
appending to `store`, so the dedupe semantics have exactly one implementation.
Each raw asset names its destination in `@asset(metadata={"jsonl_stream": ...})`;
an undeclared or unknown stream raises rather than defaulting to a file.

**Rows land before the watermark.** `state.json` claims coverage, and
`sync.integrity()` believes it — so state written first would report a gap as
OK. `tests/test_io_manager.py` pins the order.

`flow sync` materialises the raw assets **in-process** (`orchestration.py`)
rather than shelling out to `dagster asset materialize`: the CLI keeps its
summary and its non-zero exit on incomplete history, and the run is still
recorded in `.dagster_home` for `dagster dev` and the MCP.

### Neo4j IO manager

All graph persistence goes through `io/neo4j_io_manager.py`. No asset calls Neo4j
directly. Assets return Polars DataFrames and declare Cypher in
`@asset(metadata={...})`: `cypher_template` (UNWIND batch write), `load_cypher`
(read back), `post_cypher` (optional, e.g. the calendar `NEXT` chain). Templates
are co-located with the asset, not in a shared `queries.py`. An asset that
declares no `cypher_template` raises rather than materialising green over an
empty graph.

**Declare the frame's schema; do not let Polars infer it.** Both staged frames
are sparse in exactly the wrong way — the oldest signals carry no `observed_at` —
so sampled inference calls that column null and then fails on the first row that
has one. `pl.Schema({...})` beside the asset, and `infer_schema_length=None`
when reading back.

**`enr` holds what a row cannot know alone.** Latency, pull rank, interleaving
and failure kind come out of the fold and live on `(:Stg:FlowRow)` already;
putting them in `enr` too would be a second implementation. Per-day adherence
beside per-day production is the kind of thing that belongs there.

**Phantom dependencies**: assets that create relationships to dimensions declare
those dimensions as inputs and ignore the value (`_ = dim_day`), so Dagster
materializes them first and the Cypher `MATCH` can find the nodes.

### Polars only — no pandas

Hard constraint. Prefer streaming LazyFrames; collect only when necessary.

### Idempotent pipelines

Every pipeline is idempotent — re-running produces identical state. `MERGE`, never
`CREATE`. This already holds for the archive and must hold for the graph.

## 6. Hard constraints — Butler

**Butler rules cannot be read or written by any API.** There is no endpoint. If a
rule needs changing, it is a browser task, and `docs/02-butler-rules.md` must be
updated in the same change — it is the only record that exists.

**Never add an event-triggered Butler rule** ("when a card is moved to…"). Those
fire once per card: 5 cards/day = 150 runs/month, and the four scheduled rules
already use 120 of the 250-run Free quota. New metrics go in `metrics/`, computed
from stored history. Check Automation → Usage before adding any rule at all.

**Butler binds labels and lists by NAME, not id.** Renaming the `Flow` label or
any list silently breaks every rule referencing it — the rule still runs, still
logs success, and matches nothing. Learned the hard way on 2026-08-16. Any rename
is a *rule rebuild*. Verify with **Run now** (the rocket icon), which triggers the
real saved rule.

**Two Butler constraints shaped the design** — do not "simplify" past them: a
batch `move each card` must be the last action in a command, and no archive action
accepts a list *and* a label together. That is why the drain is two rules plus the
`drain` scratch list.

**The drain is destructive by design** (archive, not delete — recoverable). It
keys entirely off the `Flow` label. Before touching anything affecting which cards
carry it, run `uv run flow check` and read both lists. Long-running cards must
appear under "would survive".

**Card titles are a contract.** The refill rule creates cards by literal name and
the model joins on it. Changing `activities` in `config/board.yaml` means editing
rule 3 in the Trello UI too, or the new activity records as `never_appeared`
forever.

**`flow refill` and `flow drain` are fallbacks, not the design.** They exist so the
cycle survives a Butler outage. If you find yourself scheduling them, stop — that
recreates the laptop dependency the whole thing was built to avoid.

## 7. Analytics discipline

**Hypotheses are pre-registered.** Write them in `docs/06-diagnostics.md`, dated,
*before* running the analysis that examines them. Three are committed to publicly
in article 05 and must be tested as published. Finding a flattering pattern after
the fact is trivially easy and worth nothing.

**Every metric and plot is N-gated.** Five binary-ish outcomes a day is thin;
rates and streaks are noise for 8–12 weeks. Below threshold, output says
"insufficient data — N=x, needs y" rather than drawing a line. **"Not yet" is a
result.**

**Visibility is always allowed; inference is gated.** A cumulative total and a
current level are facts and need no N. A rate from three events is noise. Show
where things stand every time; withhold trend language until N clears.

**Everything is measured from the epoch, never from birth.** The practice went
live on 2026-08-16 (`history.start_date`); everything banked before is ground
zero, earned by ad-hoc ventures rather than by this system. Applies to reception
**and health**: pre-epoch workouts came under a different regime, after a phone
change that made measurement unreliable. Report the delta since the epoch as the
headline and the inherited baseline as labelled context. Only **public** artefacts
count as production — a private or unlisted video did not leave the building.

**Body mass is the one exception, for a reason worth keeping straight.** It is a
*level*, not an accumulation, so its epoch value is a genuine starting line rather
than something to discount — the question is how far it has moved, not how much of
it flow can claim.

**Embodiment is not an impact metric, and silence is not absence.** Apple Health is
a *second observer* of Train, which stays one lane. Only explicit workouts and body
measurements are read — step counts and activity rings are missing-not-at-random,
because the watch is worn while exercising or out of the house. When the watch has
been quiet, say so as a gap in **measurement**; it took one message from Oscar to
establish that a 78-day silence covered days he had trained and logged the card
without wearing it. Strength training records as `FunctionalStrengthTraining`,
**not** `Traditional` — filtering on the wrong one matches zero of 208 sessions and
reports, plausibly, that it never happened.

**Reception is never coupled to recent practice, at any lag.** Excluded by design,
not by threshold: a star answers to a link someone posted or to work shipped two
years ago. The unit is cumulative reward on sustained commitment, read at year
scale. `Train` stays **one lane** — commitment to a category of growth, not the
activity inside it.

**Nothing here is causal.** No randomisation by design — card ordering is
randomised for variety, not inference. Coupling between practice and output is
confounded, and reports must say so every time.

**Tiers are load-bearing.** `production` (what you put out) / `reception` (what came
back) / `internal_other` (an org-mate's output, neither) / `embodiment`. Without
the tier filter a stranger's star reads as your own output and
`adherence_without_production` says the opposite of the truth.

**`fixtures.py` is fabricated data**, built to contain the patterns the analysis
looks for. Use it to develop and test; never cite it as evidence about the real
practice. Anything that *writes* fixtures must wrap the writes in
`store.redirect(<throwaway dir>)` — the store is append-only and dedupes on id, so
fabricated rows landing in `data/` cannot be undone by any normal command.

**Charts are checked by rendering them, not by reading the code.** Two bugs got
through review looking perfectly reasonable: a `mark_rect` on a continuous `day:T`
(no band, so every cell spanned its row) and a forward rolling window (curve
shifted early, final weeks averaging emptier windows). Both drew without erroring.
`tests/test_frames.py` pins them.

## 8. Pre-work checklist

```bash
just up               # Neo4j + graph schema (constraints and indexes)
uv sync --all-groups
just install-cmdstan  # one-off: the inference layer samples with CmdStan
just check            # typecheck + lint + test
```

Only proceed if all pass.

## 9. MCP servers

Six, and they are a core architectural feature rather than supplementary tooling.

| server | use |
|---|---|
| **neo4j** | Read-only Cypher against the live graph. Use it *instead of writing throwaway Python* to inspect data — the single biggest day-to-day win of this platform. `get-schema`, `read-cypher`, `list-gds-procedures`. Two **standing GDS projections** are maintained platform-side and refreshed on sync — `flow_cocompletion` (activity→day through completed rows) and `flow_days` (enriched days with features) — and `CALL gds.*.stream('flow_cocompletion', ...)` works through read-cypher. Projection *creation* stays platform-side; never try to project through the MCP. |
| **dagster** | `list_assets`, `materialize_asset`, `get_run_info`, `recent_runs`. The MCP speaks GraphQL to `just dagster` (port 3001) — start it only when you need those tools. `flow sync` and `flow brief` use the Dagster instance directly and need **no server**. |
| **serena** | LSP-powered symbol search — and `write_memory`, which is the **development-mode** memory (codebase knowledge). |
| **context7** | Current library docs — Dagster, Polars, Neo4j, altair, CmdStanPy. |
| **memory** | The **practice-mode capture surface**: the working set the knowledge layer promotes from, under `taxonomy.py`'s closed vocabulary. Never module-architecture notes — that is serena's job. See the capture protocol in §2. |
| **marimo** | Interact with running notebook sessions. Needs the notebook server (see delivery policy in §2); MCP tools register at session start, so a server started mid-session is reachable by URL immediately but by MCP only after a Claude Code restart — say so, never block on it. |

`NEO4J_READ_ONLY=true` by design — all graph writes go through the IO manager.

**The loop**: plan (query graph, search code, check docs) → implement → verify
(materialize, query results) → iterate on structured failures.

## 10. Vertical slices

**All normal work is delivered in vertical slices** — the minimum deliverable,
independently verifiable unit. A single pure function, one dataclass, one asset,
one test, one bug fix. **Not** a slice: several unrelated changes, or changes
spanning modules without a clear dependency.

1. Identify the smallest atomic change that can be verified on its own
2. Implement only that
3. Verify with everything in §11
4. Repeat

**The one standing exception** is the platform migration itself. A package rename
or an IO-manager swap cannot be decomposed without leaving the tree importing
itself two ways. There, the rule is **slices within each step, and each step lands
whole** — `just check` green at the end of every step, never only at the end of the
migration. Outside that migration, the normal rule applies.

## 11. Mandatory verification

Every slice passes **all** of these before proceeding.

```bash
just check      # typecheck + lint + test, in one
```

- **Types**: `uv run mypy src/` — no errors, complete annotations
- **Lint & format**: `uv run ruff check . && uv run ruff format --check .`
- **Tests**: `uv run pytest` — offline, no credentials needed
- **Board-touching work**: `uv run flow check` and `uv run flow sync` — sync prints
  an integrity verdict and exits non-zero when history is incomplete
- **Graph work**: query it back through the `neo4j` MCP and confirm the shape
- **Charts**: render and look at them
- **Against the spec**: `docs/05-water.md` and `docs/06-diagnostics.md` win over
  code and over tests when they disagree

### Suspect all existing code

Agents introduce unnecessary logic, stubs and incorrect implementations. **Every
detail should be examined.** Compare metric implementations against the domain
specification.

### Tests are not infallible

Tests may pin incorrect behaviour or be missing critical cases. When results
conflict with the specification, **trust the specification**.

## 12. Code conventions

**Documentation starts with why.** Docstrings explain the reason a thing exists
before what it does. The codebase's comments carry hard-won findings — the
14-day traffic retention, the settle window, the strength-training spelling. Keep
that habit; those comments are the reason those bugs stay fixed.

**Naming**: `raw_*`, `stg_*`, `enr_*`, `dim_*`, `fct_*` for assets, matching the
node labels.

**Functional practices**: immutability by default, pure functions in `metrics/`,
complete type annotations, composition over inheritance, explicit errors over
silent fallbacks. **A lapsed credential must fail loudly** — recording zeros looks
exactly like a channel nobody watched.

## 13. Files

- `config/board.yaml` — hand-authored. Safe to edit.
- `config/resolved.json` — written by `flow discover` / `flow bootstrap`. Never
  edit by hand.
- `data/` — append-only, gitignored, **the truth**. Never rewrite or truncate;
  `sync` is idempotent, so re-running is always safe and deleting is never
  necessary.
- `ingest/` — a doormat (§2). Consumed and purged.
- `neo4j/`, `.dagster_home/` — local service state, gitignored, disposable.

## 14. Day boundary

The flow day runs **04:00→04:00**, not midnight→midnight, in both the board's
behaviour and the analysis. A completion at 01:00 belongs to the previous day. If
`schedule.drain_at` changes, the Butler rule and this boundary move together or
the numbers stop matching the board.

This is defined once, in the flow-day calendar, and everything else derives from
it.

## 15. Before saying something works

- `just check` passes
- Anything board-touching: `uv run flow check`, `uv run flow sync`
- Anything graph-touching: purge and rematerialize reproduces it exactly
- Anything chart-touching: rendered and looked at
- Report honestly: if tests fail, say so with the output; if a step was skipped,
  say that
