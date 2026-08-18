---
description: Weekly flow review — what moved, what stalled, one thing to change
allowed-tools: Bash(uv run flow sync:*), Bash(uv run flow brief:*), Bash(uv run flow evidence:*), Bash(uv run flow report:*), Read, mcp__memory__create_entities, mcp__memory__create_relations, mcp__neo4j__read-cypher
---

Run the weekly review of the W.A.T.E.R. practice. This is the **T-level**
review: it looks at how the days actually went — what was reached, what was
deferred, where time leaked — and never touches R or E.

## Gather

```bash
uv run flow sync --signals
uv run flow brief --json
uv run flow evidence --window 7
```

If `sync` reports incomplete history, say so first and treat every number as a
lower bound. If `brief` says a heavier review is due, say that too — then still
deliver the weekly that was asked for.

Check what the *last* weekly concluded and prescribed before writing a word:

```cypher
MATCH (r:Meta:Review {cadence: 'weekly'})-[:ON_DAY]->(d)
OPTIONAL MATCH (p:Meta:Prescription)-[:PRESCRIBED_BY]->(r)
RETURN r.name, d.date, p.change ORDER BY d.date DESC LIMIT 1
```

## Write

Short. Six sentences at most, no headings. Cover:

1. **Last week's prescription** — was it followed, and did it move anything?
   One sentence, honest. This closes the loop before opening a new one.
2. **What moved** — which modes went up, with the rate and the change.
3. **What stalled** — the weakest mode, and whether its failures are
   `never_started` (allocation — time and ordering) or `abandoned` (capacity —
   reach). Name which; the remedies are opposite.
4. **Where reception stands** — one line, levels only. No trend language; the
   pack says when a trend is supportable, and for a long while it will not be.
5. **One concrete change** for the coming week. One. Something that fits inside
   the flow of moving cards.

## Capture (after Oscar has seen the review)

Write through the memory MCP, in taxonomy shape:

- `review:<today>:weekly` (Review) — `day:`, `cadence: weekly`, `window: 7`,
  plus a one-line summary observation.
- `prescription:<today>:<slug>` (Prescription) — `day:`, `change:`,
  `review: review:<today>:weekly`; relation `prescribed_by` → the Review.
- An `Observation` with relation `outcome_of` → *last* week's Prescription,
  recording what became of it.

## Rules

- **Cite the numbers, state N.** A week clears almost nothing; say so.
- **Do not diagnose from a week.** The CSF table needs 14 days and will refuse.
- **Never claim cause.** Nothing is randomised.
- **Never connect reception to this week's practice.** Cumulative reward on
  sustained commitment — at any lag, excluded by design.
- **Clones are not reach.** Quote views and unique visitors.
- **A missed day is data, not debt.**
