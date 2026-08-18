---
description: Monthly flow review — the pre-registered hypotheses and the diagnostic table
allowed-tools: Bash(uv run flow sync:*), Bash(uv run flow brief:*), Bash(uv run flow evidence:*), Bash(uv run flow report:*), Read, mcp__memory__create_entities, mcp__memory__create_relations, mcp__neo4j__read-cypher
---

Run the monthly review. This is the one that tests what was committed to in
advance — the **E_L** event of the cadence.

## Gather

```bash
uv run flow sync --signals
uv run flow brief --json
uv run flow evidence --window 28
```

Read `docs/06-diagnostics.md` for the diagnostic table, the extensions and the
decision criteria, so the vocabulary matches the document rather than being
improvised. Retrieve last month's interpretations before writing:

```cypher
MATCH (i:Fct:Interpretation)-[:FOLLOWS_FROM]->(r:Meta:Review {cadence: 'monthly'})
RETURN r.name, i.measure, i.reading ORDER BY r.name DESC LIMIT 12
```

## Write

Five sections, in order.

**1. The three pre-registered hypotheses.** Report each exactly as published in
article 05. Verdicts are Bayesian (see `docs/06-diagnostics.md` for the priors
and decision thresholds) and three-way: **supported / not supported /
inconclusive**, with the posterior probability, the pre-registered bar, and the
posterior interval stated. Where the posterior layer is not yet built or a
measure remains under-powered, report the stored verdict and its N honestly.

**2. Which rows of the diagnostic table fire.** For each: the imbalance, the
CSF mode, the component at fault (**R**, **E** or **T**), the prescription. The
prescriptions are not interchangeable. If no row fires, say so plainly — that
is a result about balance.

**3. The extension measures.** Allocation vs capacity; dormancy; charge;
adherence-without-production; productive aberration. Only those that cleared.

**4. Production against reception.** Levels and cumulative totals, never rates
until the pack supports one. Steady production with flat reception is
**E_A ≠ E_S** — the individual's evaluation diverging from the field's — and
the prescription is *not* "promote harder". Standing corrections: clones are
infrastructure; stars on this repo are a decaying series.

**5. What to do.** At most two changes, each traceable to a number above.

## Capture (after Oscar has seen the review)

- `review:<today>:monthly` (Review), window 28.
- One `Interpretation` per measure actually read —
  `interp:<today>:<measure>` with `day:`, `measure:`, `reading:`; relation
  `follows_from` → the Review, `tests` → the Hypothesis where one exists.
- `prescription:<today>:<slug>` with `prescribed_by` → the Review.
- `gate:<today>:<measure>` (GateOpened) for anything acted on from
  `brief`'s newly-answerable list.

## Rules

- **Test what was pre-registered.** New patterns are candidates for *next*
  period — write them into `docs/06-diagnostics.md`, dated, with prior and
  threshold, before they are tested.
- **Cite every number and its N; refuse when under-powered.**
- **Never claim cause; never correlate reception with practice at any lag.**
- **Distinguish dormancy from uninspiration** — an unattempted mode did not
  fail to be reached.
