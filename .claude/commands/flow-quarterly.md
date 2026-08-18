---
description: Quarterly R-semantics review — do the five still mean what you do?
allowed-tools: Bash(uv run flow sync:*), Bash(uv run flow brief:*), Bash(uv run flow evidence:*), Bash(uv run flow report:*), Read, mcp__memory__create_entities, mcp__memory__create_relations, mcp__neo4j__read-cypher
---

Run the quarterly review. **The five modes are fixed by decision — this review
does not ask whether they are the right five.** It asks the question that stays
open: **does the substantive content of each mode still match what you actually
do and value?** That is R-semantics — the boundary of what counts as a valid
instance of Write, Absorb, Train, Express, Reveal — and it is the component you
change last and least. Wiggins' warning applies: most failures are T. Check
that first.

## Gather

```bash
uv run flow sync --signals
uv run flow brief --json
uv run flow evidence --window 90
```

Read `docs/06-diagnostics.md` (extensions 2–4) and `docs/05-water.md` for what
each mode is *for*. Retrieve every open DevProposal and every Transformation
this quarter:

```cypher
MATCH (p:Meta:DevProposal) WHERE p.status = 'registered'
RETURN p.name, p.gate, p.motivation ORDER BY p.name
```

## The case for refining a mode's semantics

Argue only from evidence that bears on validity:

- **Productive aberration** — output arriving on days the five were skipped is
  work outside R that was valued anyway. Under fixed membership this argues
  "the boundary of which mode this belongs to is drawn wrong", or it is telling
  you about T. Say which, with the count and share of producing days.
- **Escalated dormancy** (21+ days, nothing visibly suffering) — evidence about
  a mode's *semantics* being too narrow or too stale to engage, not about
  discipline.
- **Adherence without production** — the harmonious case; conceptual
  uninspiration in slow motion. The board alone cannot see it.

## The case against

- **Allocation failure is not evidence about R.** A mode never started told you
  nothing about whether its definition is right.
- **Under-powered is not evidence.** Say plainly which parts of the argument
  the data cannot yet carry.

## Also, each quarter

1. **The platform**: walk the open DevProposals — which gates have been
   reached? Raise those for a decision. Any platform limits hit this quarter
   that have no proposal yet?
2. **The whitepaper**: does `docs/08-creative-systems-practice.md` still
   describe the system as it exists? If not, list the drift; updating it rides
   the same Transformation records.

## Write

1. **Verdict** per mode: semantics hold, or a specific refinement — exactly
   what would now count that did not, or stop counting that did.
2. **Evidence for**, with numbers and N. 3. **Evidence against**, likewise.
4. If refining: the consequences. Card titles are a contract — names do not
   change; only the understanding of what belongs under them.

## Capture (after Oscar has seen the review — and any semantics refinement
only after he confirms it)

- `review:<today>:quarterly` (Review), window 90.
- `Interpretation`s as in the monthly.
- A confirmed refinement: `transformation:<today>:<slug>` with
  `kind: R-semantics`, `what:`, `confirmed: yes` — **only post-confirmation**;
  trends segment at this node.
- DevProposal status updates for anything approved, declined or gated-in.
