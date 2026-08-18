# Flow

A daily practice of five modes — **W.A.T.E.R.** — running natively on Trello,
plus a gap-free local history of it for analysis.

| | | |
|---|---|---|
| **W** | Write | Documenting or organising thoughts and actions |
| **A** | Absorb | Absorbing new knowledge or information |
| **T** | Train | Internalising through disciplined practice |
| **E** | Express | Acting on unfiltered, authentic impulse and free association |
| **R** | Reveal | Exposing thoughts or actions to the broader culture |

Five cards appear in **`future`** each morning. You pull them individually
through **`present`** to **`past`**. Anything not in `past` by the day boundary
is drained and archived, then refilled next morning — a missed day is data, not
debt. Long-running work shares the same lists and is never touched, because it
carries no `Flow` label.

The framework, and the imbalance patterns worth testing against the data, are in
**[docs/05-water.md](docs/05-water.md)**.

## How it's split

| concern | where it runs | why |
|---|---|---|
| Daily refill + drain | **Trello Butler**, on Trello's own infrastructure | No laptop, no cron, no external service to fail. |
| Ad-hoc card work from the prompt | `@delorenj/mcp-server-trello` via Claude Code | Natural-language board control. |
| History and metrics | This repo, run manually | Butler can't do analysis; the API export can't hold history. |

Butler owns the loop. Everything else is optional on any given day.

## Daily operation

The platform is live; this is the loop. Docker is always required — the graph
is the sole analysis source, and a down graph fails loudly rather than
reporting zeros.

```bash
just up                      # Neo4j + schema (once per boot)
uv run flow sync --signals   # every source -> archive -> the whole graph DAG
uv run flow brief            # what deserves attention, and how deep to go
uv run flow report           # practice, reception, embodiment + posteriors
uv run flow evidence --window 7   # the review pack, when a review is due
```

Three analysis surfaces, one source (the graph): the **CLI** above; the
**summary dashboard** (`flow publish`, delivered as a claude.ai artifact); and
the **literate notebooks** (`just notebook`, then
`http://localhost:2719/?file=flow.py` for the practice narrative and
`?file=graph.py` for the guide to the graph — contract in
`notebooks/README.md`).

In normal use the agent runs all of this (`CLAUDE.md` is the contract, and it
engages socratically — `docs/10-socratic-practice.md`); every command also
works by hand.

## First-time setup (new machine or new board)

```bash
cp .env.example .env && chmod 600 .env    # add your key + token
uv sync --all-groups
just install-cmdstan                      # one-off: the inference layer
uv run flow discover                     # pick a board
uv run flow discover --select <board-id>
uv run flow bootstrap --apply            # ensure lists + Flow label
uv run flow check                        # what the drain would touch — read it
```

Then create the three Butler rules by hand: **`docs/02-butler-rules.md`**. The
board side is a one-off — Butler runs the daily cycle on Trello's own
infrastructure from then on.

## Commands

| | |
|---|---|
| `flow discover [--select ID]` | List boards, or describe and select the target |
| `flow bootstrap [--apply]` | Idempotently ensure lists and the `Flow` label. Dry run by default. |
| `flow check` | Show what the drain rule would archive vs spare, right now |
| `flow brief [--json]` | What is stale, due, changed and newly answerable — start here |
| `flow sync [--backfill] [--since DATE]` | Pull history into the local store, with an integrity check |
| `flow report [--json\|--rows\|--export PATH]` | Regularity metrics; CSV/parquet export |
| `flow evidence --window N [--json]` | The review pack: rates, diagnostics, verdicts, adequacy |
| `flow publish` | Render the summary dashboard to `reports/dashboard.html` |
| `flow refill [--dry-run]` | Create today's five W.A.T.E.R. cards (Butler fallback) |
| `flow drain [--dry-run]` | Archive unfinished `Flow` cards (Butler fallback) |

## Layout

```
config/board.yaml       hand-authored intent: activities, list names, schedule
config/resolved.json    machine-written Trello ids — never edit
src/flow_analysis/      client, discover, bootstrap, sync, store, surfaces
src/flow_analysis/definitions.py
                        the Dagster code location — every asset and resource
src/flow_analysis/resources/
                        one ConfigurableResource per origin (Layer A)
src/flow_analysis/assets/raw.py
                        six raw assets, stored verbatim as fetched
src/flow_analysis/io/   JsonlIOManager (rows before watermark) and
                        Neo4jIOManager (each asset's Cypher, co-located)
src/flow_analysis/graph/
                        constraints and indexes; `just up` applies them
src/flow_analysis/tiers.py
                        production / reception / embodiment — the vocabulary both
                        the sources and the metrics need, importing nothing
src/flow_analysis/sources/
                        one module per origin: forum, github, youtube, health
src/flow_analysis/metrics/
                        pure computation: the flow-day calendar, the grid fold,
                        production bucketing, diagnostics, reception, embodiment,
                        frames. Imports nothing that fetches or persists, and
                        tests/test_layering.py fails if that ever changes
docs/                   setup, the Butler rule spec, API notes, analysis notes
data/                   append-only local history (gitignored)
tests/                  offline tests of the folding and metrics
```

## Live setup

Board **flow** (`5a154e6d562db6cb027e211e`), lists `future` / `present` / `past`,
plus a scratch list `drain` that holds cards only between 04:00 and 04:05. The
**sky-blue `Flow` label** marks daily cards; unlabelled cards are never touched.

```
04:00  move each Flow card not in "past" → "drain"
04:05  archive all cards in "drain"
06:00  create Write / Absorb / Train / Express / Reveal in "future", labelled Flow
```

Three rules, 90 of 250 monthly automation runs.

All three rules were rebuilt on 2026-08-16 after the Flow / W.A.T.E.R. rename
broke the originals, and the sweep was re-verified with **Run now**. `flow refill`
and `flow drain` remain as manual fallbacks. Detail in `docs/02-butler-rules.md`.

## Three things worth knowing before changing anything

**Butler binds labels and lists by name.** Renaming the `Flow` label or any list
silently breaks every rule that mentions it — the rule still runs and still
reports success, matching nothing. Rebuild the rules after any rename, and verify
with **Run now**.

**Butler rules cannot be read or written by any API.** `docs/02-butler-rules.md`
is their only record. If you edit a rule in Trello, edit that file too.

**Trello Free allows 250 automation runs per month, pooled per workspace.** The
three scheduled rules use 90. A single event-triggered rule on card movement
would use 150 — do the statistics in `report.py`, not in Butler. See
`docs/03-api-notes.md`.
