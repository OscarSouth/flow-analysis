# Agent runbook — the operational cookbook

What a fresh session needs beyond `CLAUDE.md`: the registry of what the graph
holds, the queries that answer the common questions, and the procedures the
contract points at. Every query here was executed against the live graph before
it was written down. If one stops working, that is an incident (§7).

## 1. Session bootstrap (practice mode)

1. Neo4j reachable? (`nc -z localhost 7689`) — if not, `just up`.
2. `uv run flow sync --signals` — materialises the whole DAG (raw → graph →
   posteriors → knowledge). Takes ~30–60s; the Stan fits run inside it.
3. `uv run flow brief --json` — follow the depth it prescribes.
4. Servers on demand only: `just dagster` (port 3001) if the dagster MCP tools
   are needed; the notebook server per the delivery policy. Neither is a
   precondition for sync, brief, report or evidence.
5. Before the first *dialogic* practice interaction — discussion, hypothesis
   work, anything transformation-shaped — read
   `docs/10-socratic-practice.md`: the method, the hardness spectrum, and the
   Belief/Reference capture patterns.

One-off machine provisioning: Docker, `uv sync --all-groups`,
`just install-cmdstan`.

## 2. The measure registry

### `(:Fct:Measure)` — the gated diagnostics (from `metrics/diagnostics.py`)

`allocation_vs_capacity` · `dormancy` · `charge` · `coupling` ·
`adherence_without_production` · `aberration` — plus one row per **contract**
(`c1_…` .. `c9_…`): deterministic contracts (c6–c8) carry their verdict here;
posterior contracts (c1–c5, c9) carry only their gate state, with the verdict
on the posterior snapshot.

Each carries `ok` (cleared its gate), `n`, `needs`, `value_json`,
`detail_json`. A measure with `ok: false` is a refusal — a result, never a gap.

### The contract registry (`metrics/contracts.py`, reworked 2026-08-19)

Nine falsifiable, CSF-typed, rolling contracts mirroring the diagnostic
table — failure-positive (healthy = refuted) except c9, the health-positive
publication-cadence floor. Windows, gates, margins and prescriptions live in
`REGISTRY`; the full table is in `docs/06-diagnostics.md`. A rolling verdict
is *standing* only after 7 consecutive snapshot days (`PERSISTENCE_DAYS`);
prescriptions attach only to standing verdicts. The old H1–H3 were
superseded by this registry (H1→c1 generalised, H3→c5, H2 retired).

### `(:Fct:Posterior)` — daily posterior snapshots, one row per (measure, day)

| naming scheme | quantity |
|---|---|
| `adherence:practice` | practice-level completion rate (hierarchical μ) |
| `adherence:<Mode>` | per-mode completion rate (pooled θ) |
| `latency_median:<Mode>` | median minutes to first touch, censoring-aware |
| `p_never_started:<Mode>` | the survival plateau — allocation-failure probability |
| `contract:c1_…` .. `contract:c9_…` | the statistical contracts, each over its own trailing window |
| `cascade:production~commitment` | windowed production vs cumulative adherence (confounded, always say so) |

Every row carries `mean`, `median`, `ci_low`, `ci_high` (central 90%),
`rhat_max`, `ess_min`, `divergences`, `trusted`, and for the prereg rows
`probability` and `verdict`.

**Verdict semantics (four-way, all-Bayes):** `supported` (P ≥ 0.90) ·
`not supported` (P ≤ 0.10) · `inconclusive` (between) · **`not testable yet`**
(below its N-gate *or* the sampler's diagnostics failed). Never read an
untrusted row as a result; never read `not testable yet` as evidence against.

### Workout intensity (2026-08-21, devproposal:2026-08-21:workout-intensity)

Not a posterior and not a contract — **visibility only**, rendered in `flow
report`'s embodiment block. Each workout's heart-rate series is archived as a
`(:Stg:Signal {kind: 'workout_hr'})` row (parallel `hr_offsets_s` / `hr_bpm`
arrays, paired 1:1 with its workout by fingerprint; Apple's per-session
statistics — `hr_avg_session`, `hr_min_session`, `hr_max_session`, `avg_mets`,
`active_kcal` — ride the same row). Features are computed at read time in
`metrics/embodiment.py` and every constant is **provisional by design**,
revisable in dialogue because the raw series is archived:

- active span = first to last sample at ≥70% of *that session's* max
  (`WORKING_HR_FRACTION`) — self-calibrating across Oscar's varied patterns;
- mean/min HR taken across every sample inside the span (rests between sets
  are the point);
- `elevated_minutes` = capped time-in-zone (`DWELL_CAP_S`), cardio's measure;
- features refused below 30 samples (`MIN_SERIES_SAMPLES`) — the export's
  series is dense only where the watch tracked the session, and a span drawn
  through background samples would be a confident answer the data cannot
  carry. Session statistics still speak for those workouts.

No trend language until a trend question is pre-registered and N-gated.

### Knowledge entities (from `taxonomy.py`)

`Review` `Interpretation` `Prescription` `Transformation` `Hypothesis`
`GateOpened` `DevProposal` `Observation` `Belief` `Reference` `Journal` —
labels `(:Meta:*)`, `(:Fct:Interpretation)`, `(:Stg:Note)`. Names encode the
day: `review:2026-08-18:monthly`. Relations: `CONCERNS` `ON_DAY`
`FOLLOWS_FROM` `TESTS` `PRESCRIBED_BY` `OUTCOME_OF` `ENABLED_BY` and the
socratic four — `REVISES` (Belief→Belief, the provisionality chain)
`CHALLENGES` `SUPPORTS` `CITES`. A Belief's `status` is
`held`/`revised`/`retired`, never final.

Two relations are **structural** — derived from fields in the post-cypher,
never agent-declared: `ON_DAY` (from `day:`) and `REFLECTS_ON` (from `day:` +
`activities: Train, Express`, comma-separated → the day's `(:Stg:FlowRow)`
state rows). A reflection about a mode *in general* (no specific day) instead
declares `concerns` → the `(:Dim:Activity)` node by name.

## 3. Cypher cookbook (read-cypher; all verified live)

**The last review of a cadence, with its day:**
```cypher
MATCH (r:Meta:Review {cadence: 'weekly'})-[:ON_DAY]->(d:Dim:Day)
RETURN r.name, d.date ORDER BY d.date DESC LIMIT 1
```

**Open loops — prescriptions nothing has answered:**
```cypher
MATCH (p:Meta:Prescription) WHERE NOT (:Stg:Note)-[:OUTCOME_OF]->(p)
RETURN p.name, p.change
```

**A measure's belief over time (the ridgeline data):**
```cypher
MATCH (p:Fct:Posterior {measure: 'adherence:practice'})
RETURN p.day, p.mean, p.ci_low, p.ci_high, p.trusted ORDER BY p.day
```

**Every measure with its adequacy:**
```cypher
MATCH (m:Fct:Measure) RETURN m.name, m.ok, m.n, m.needs ORDER BY m.name
```

**The calendar span (NEXT-chain endpoints):**
```cypher
MATCH p = (a:Dim:Day)-[:NEXT*]->(b:Dim:Day)
WHERE NOT (:Dim:Day)-[:NEXT]->(a) AND NOT (b)-[:NEXT]->(:Dim:Day)
RETURN a.date, b.date, length(p)+1 AS days
```

**Which past day most resembles a given day:**
```cypher
MATCH (a:Enr:Day {date: $day})-[s:SIMILAR_DAY]->(b)
RETURN b.date, s.score ORDER BY s.score DESC
```

**The DevProposal register:**
```cypher
MATCH (p:Meta:DevProposal) RETURN p.name, p.gate, p.status ORDER BY p.name
```

**Deep-dive days** (the completed-status checkbox on card fronts, repurposed:
Oscar flags a mode he doubled up on or dove deep into, judged at flag time.
Orthogonal to outcome by decision — `deep` + `abandoned_in_progress` is a real
state. Retroactive flags attribute to the card's day, not the flag's date):
```cypher
MATCH (r:Stg:FlowRow) WHERE r.deep
RETURN r.day AS day, r.activity AS activity, r.outcome AS outcome ORDER BY day
```

**What was said about a mode's days, beside how those days went** (the
journalling layer — REFLECTS_ON is drawn from the `activities:` field):
```cypher
MATCH (j:Meta:Journal)-[:REFLECTS_ON]->(r:Stg:FlowRow {activity: 'Train'})
RETURN r.day AS day, j.name AS entry, j.note AS note, r.outcome AS outcome
ORDER BY day
```

**Beliefs and their revision chains (the socratic layer, docs/10)** — note the
`ORDER BY` must use the aliased `day`; the aggregation makes `b` unreachable:
```cypher
MATCH (b:Meta:Belief)
OPTIONAL MATCH (b)<-[:REVISES]-(successor:Meta:Belief)
OPTIONAL MATCH (b)<-[c:CHALLENGES|SUPPORTS]-(x)
RETURN b.day AS day, b.name AS name, b.claim AS claim, b.status AS status,
       successor.name AS revised_by,
       collect(DISTINCT {rel: type(c), by: x.name}) AS bearing
ORDER BY day
```

**GDS against the standing projections** (`flow_cocompletion`,
`flow_days`; refreshed on every sync — never project through the MCP):
```cypher
CALL gds.nodeSimilarity.stream('flow_cocompletion')
YIELD node1, node2, similarity
RETURN gds.util.asNode(node1).name AS a,
       gds.util.asNode(node2).name AS b, similarity
```

## 4. Notebook delivery

1. `nc -z localhost 2719` — if closed:
   `nohup uv run marimo edit notebooks/ -p 2719 --headless --mcp
   > /tmp/marimo.log 2>&1 &` and wait for the port.
2. Hand direct links: `http://localhost:2719/?file=flow.py` (practice
   narrative + dashboard mirror), `http://localhost:2719/?file=graph.py`
   (the graph guide).
3. marimo MCP tools reach a server started *this* session only after a Claude
   Code restart — mention it once if relevant, never block on it.
4. Notebooks obey `notebooks/README.md` — the literate contract.

## 5. Artifact delivery

`uv run flow publish --out reports/dashboard.html`, publish as a claude.ai
artifact, hand the link. One artifact updated in place — the summary dashboard
view; depth lives in the notebooks.

## 6. Capture cheat-sheet

Entities via the memory MCP, required fields as `key: value` observation
lines. `flow sync` promotes. Fix mistakes in the working set *before* the next
sync makes them permanent.

| when | entity | required fields |
|---|---|---|
| review completes | `review:<day>:<cadence>` | day, cadence, window |
| a measure is read | `interp:<day>:<measure>` | day, measure, reading |
| one change proposed | `prescription:<day>:<slug>` | day, change, review |
| gate acted on | `gate:<day>:<measure>` | day, measure, n |
| hypothesis pre-registered | `hypothesis:<day>:<slug>` | day, claim, bar, prior |
| platform limit hit | `devproposal:<day>:<slug>` | day, motivation, proposal, gate, status |
| change lands (confirmed!) | `transformation:<day>:<slug>` | day, kind, what, confirmed |
| incident / context | `observation:<day>:<slug>` | day, note |
| conviction surfaced/revised in dialogue | `belief:<day>:<slug>` | day, claim (Oscar's exact words), status (`held`/`revised`/`retired`) |
| source enters the dialogue | `reference:<day>:<slug>` | day, title, source |
| dialogue ends in perplexity | `observation:<day>:aporia-<slug>` | day, note |
| day's practice reflected on (journalling) | `journal:<day>:<slug>` | day, note — plus optional `activities: <Mode>, <Mode>` (draws REFLECTS_ON) and `url:`/`video_id:` (artefact identity for future attribution) |

A revision never edits a belief away: the successor Belief points at its
predecessor with `revises`, and the predecessor's `status:` line changes to
`revised`. `challenges`/`supports` link evidence to a Belief; `cites` links
anything to a Reference.

## 7. Durability procedures

- **The archive is the truth for everything**, including knowledge history
  (`data/notes.jsonl` — every state, reverts included) and posterior
  snapshots (`data/posteriors.jsonl` — replayed into the graph on every
  run, so purge-and-rebuild reproduces the full ridgeline history).
- **The memory working set** (`.claude/memory.jsonl`) is the MCP-owned
  fast store. `brief` raises a health item when it is missing entities the
  archive holds. `flow memory restore` rebuilds it losslessly (refuses a
  non-empty file without `--force`; run `flow sync` first so unarchived
  captures are not overwritten). A running MCP server may need a session
  restart to see the rebuilt file.
- Deletion after a sync is permanent in the archive and graph; retraction
  is `status: retired`.

## 8. Incident checklist (self-healing)

On any operational anomaly — failed asset, `brief` health items, a surface
raising, drift, a query in this runbook failing:

1. Name it in the conversation immediately.
2. Capture `observation:<day>:<slug>` with what was seen.
3. Diagnose: operational (re-run, restart service), platform defect, or
   capability gap.
4. Defect → propose the fix; capability → `DevProposal`. **Confirmation gates
   development mode.**
5. Land the fix, record `transformation:<day>:<slug> {kind: platform}`, link
   the resolution `outcome_of` the opening Observation.

Never work around silently; never let a workaround stand unrecorded.
