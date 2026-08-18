# Diagnostics: W.A.T.E.R. under the Creative Systems Framework

`05-water.md` says which channel is closed. This document says **what kind of
failure that is, which component is responsible, and therefore what to do** — in
the vocabulary of Wiggins' Creative Systems Framework rather than in the
vocabulary of feeling stuck.

The difference matters because the remedies are not interchangeable. "I'm not
making progress" admits every response, most of them wrong. "My traversal cannot
reach what my own evaluation would approve of" admits one: change the traversal,
leave the rules and the taste alone.

## The three questions

**R** — validity. What counts as a valid thing at all?
**E** — evaluation. Of the valid things, which are good?
**T** — traversal. How do you actually get around the space and find them?

Written **R→E→T**, matching the pipeline order used across theHarmonicAlgorithm
(`Rules/`, `Evaluation/`, `Traversal/`) rather than Wiggins' naming order R,T,E.
Same three questions, sequenced the way the machine runs them.

Formally the full system is a **septuple** ⟨U, L, ⟦·⟧, ⟪·,·,·⟫, R, T, E⟩ — the
three rule sets plus the universe, the language they are written in, and the two
interpreters (testing and enumerating). The notation, every core formula and a
written intuition for each are in `docs/08-creative-systems-practice.md` §3,
which is the reference account; formulae here were corrected against the source
papers on 2026-08-18 (the enumeration interpreter is ⟪R,T,E⟫◊, previously
transposed).

Every creative system answers all three whether or not it knows it. The point of
separating them is not tidiness — it is that **you cannot tell which one is broken
until they are apart**.

## Wiggins' failure catalogue

| mode | formal condition | meaning | remedy |
|---|---|---|---|
| **generative uninspiration** | `⟦E⟧(⟪R,T,E⟫◊({⊤})) = ∅` | R and E are both sound; the traversal never reaches the valued concepts | **transform T** |
| **conceptual uninspiration** | `⟦E⟧(⟦R⟧(U)) = ∅` | nothing in the conceptual space is valued; rules and taste have come apart | **transform R** |
| **hopeless uninspiration** | `⟦E⟧(U) = ∅` | nothing anywhere is valued | *deus ex machina* — unfixable from inside |
| **aberration** | `B = ⟪R,T,E⟫◊({⊤}) \ ⟦R⟧(U) ≠ ∅` | output that violates R | depends on E — see below |

Aberration sorts by what evaluation makes of it: **pointless** (worthless — fix
T), **productive** (valued anyway — rewrite R), **perfect** (all of it valued).

Productive aberration is the only mechanism by which R ever changes. It requires
that **E is independent of R**: if your taste can only approve things your rules
already permit, nothing rule-breaking can ever turn out to be good, and the system
can never transform. The wrong note that turns out to be the right note.

Generative uninspiration is the mild, recoverable failure. Most of the time when
something is not working, it is this one. **Check which before tearing up your
rules.**

## The diagnostic table

Each row: what the data shows → the imbalance → the formal mode → the component
at fault → what follows.

| data pattern | imbalance | CSF mode | at fault | prescription |
|---|---|---|---|---|
| Express completes, Train `never_started` | ideas, none executable | generative uninspiration | **T** | do the boring drills |
| Train completes, Express `never_started` | correct and dead | conceptual uninspiration | **R** | new material, not more practice |
| Absorb high, Reveal low | perpetual student | generative uninspiration *on Reveal* | **T** | ship something unfinished |
| Reveal high, Absorb low | well running dry | approaching conceptual uninspiration | **R/E** | stop producing, refill |
| Write missed | reactive; ideas don't survive the day | traversal degradation, all modes | **T** | offload to text |
| a mode `never_started` for k days | — | *dormancy* (new) | **allocation** | see below |
| all five complete, output flat | — | *adherence without production* (new) | **R/E** | see below |
| output on days the five were skipped | — | *observable productive aberration* | **R** | see below |

## Extensions

Wiggins models a system's **capability**, at the extensional limit where every
concept is notionally elaborated. A daily human practice differs in one decisive
respect: **it is rate-limited, and it can simply fail to run.** His catalogue has
no vocabulary for that, because his systems are always on. The following modes
live in that gap. Each is measurable from data this repo already collects.

### 1. Allocation failure vs capacity failure

Generative uninspiration is one label covering two different problems, and the
board separates them for free because it records two distinct failure outcomes:

- **`never_started`** — the card appeared and was never touched. The traversal was
  never *attempted*. An **allocation** failure: about time, attention, ordering.
- **`abandoned_in_progress`** — started, not finished. The traversal was attempted
  and did not arrive. A **capacity** failure: about reach and skill.

Same CSF label, opposite remedies. Allocation failure wants scheduling and
protection of time; capacity failure wants the boring drills. Prescribing drills
for an allocation failure is how people conclude they are lazy when they are
merely oversubscribed.

This is the single most useful refinement available here, and it costs nothing —
the distinction is already in every row of the grid.

### 2. Dormancy

A channel `never_started` for k consecutive days is **not uninspiration**. Nothing
was attempted, so nothing failed to be reached. Wiggins' modes all presuppose
execution; dormancy is the absence of it.

It matters because dormancy *masquerades* as generative uninspiration and attracts
the wrong prescription. A mode nobody has attempted for three weeks does not need
a better traversal strategy. It needs to be attempted, or honestly retired.

Threshold: `k ≥ 7` flags dormancy; `k ≥ 21` escalates it to a question about R —
if a channel has been closed for three weeks and nothing has visibly suffered,
that is evidence about the rules, not about discipline.

### 3. Adherence without production

Visible only with an external production measure: **all five completing
consistently while output stays flat.**

On the board this reads as total success. In CSF terms it is the harmonious
case — you value exactly what you already do, so nothing generates the tension
that provokes change. Harmony sounds like the goal and is actually the precursor
to stagnation: it is conceptual uninspiration in slow motion, arriving so quietly
that the tracker congratulates you the whole way.

This is the argument for ingesting the forum. Trello can only ever record that the
practice ran. It cannot record whether anything came of it.

### 4. Observable productive aberration

Article 04 concedes that theHarmonicAlgorithm's generator **cannot** aberrate: R
is enforced as a pre-filter, so invalid candidates are removed before scoring. It
will never hand over something outside its own rules. Every rule-breaking move in
the project has come from a human typing it in and deciding they liked it.

The flow system *can* observe the human kind. **Production appearing on days the
five were skipped** is work outside R that turned out to be valued — the empirical
signature of productive aberration.

That is the trigger for the quarterly question: if the good stuff keeps arriving
from outside the five, the five are wrong. Not the discipline — the rules.

### 5. Quiet decay and leading indicators

Article 05 claims Absorb and Express decay most quietly, and take the whole system
with them when they go. That is a testable lead/lag claim: does a decline in one
channel *precede* decline across the rest, and by how many days?

If it holds, the quiet channels become an early-warning instrument — the thing to
watch is not today's total but last week's Absorb.

### 6. Production without reception

*Pre-registered 2026-08-17, before any reception data was analysed.*

The board records that you practised. The forum records that you shipped. Neither
records whether anybody cared — and the state where **you ship consistently and
nothing comes back** is invisible to both.

In CSF terms this implicates **E**. Your evaluation of what is good has diverged
from the environment's: R still admits the work, T still reaches it, you still
judge it worth making. What has come apart is the agreement between your taste
and the world's. That is distinct from conceptual uninspiration (where R and E
have come apart *inside* you) and from generative uninspiration (where T cannot
reach). In a *social* creative system it is the pressure that eventually forces R
to change — but only if it is visible.

Detecting it requires three tiers, not two:

| tier | question | measured by |
|---|---|---|
| adherence | did the practice run? | Trello cards |
| production | did anything leave the building? | your forum posts, your uploads |
| reception | did anyone care? | stars, traffic, subscribers, others' posts |

An org-mate's post is deliberately **none of these** — it is not a response from
outside, and it is not evidence that *your* practice produced anything.

**The prescription is not "promote harder".** The diagnosis says E, so the
question is what you value and why the environment disagrees — which may equally
be answered by concluding the environment is wrong and continuing.

### 7. Cumulative commitment against cumulative reward

*Pre-registered 2026-08-17.*

The governing principle of the whole analytics layer, made computable: **we are
measuring the cumulative reward on sustained commitment, not the immediate impact
of a specific effort.** Plot cumulative practice-days against cumulative
reception, and compare across long horizons.

Two things follow, and both are constraints rather than preferences:

- **No lag-correlation between practice and reception, at any lag, ever.** Not
  gated behind a threshold — excluded by design. A star answers to a link someone
  posted, or to work shipped two years ago. Coupling it to Tuesday's Absorb would
  manufacture a number out of nothing.
- **Visibility is always allowed; inference is gated.** A cumulative total and a
  current level are facts and need no N. A *rate* estimated from three events is
  noise. So the weekly view always shows where things stand and never
  editorialises; trend language waits for 180 days of observation.

This is also why `Train` stays **one lane**. The point is commitment to a category
of growth, not the specific activity inside it. Whether a day's Train was strength
work or instrumental practice matters when *troubleshooting an output* — never
when scoring a day.

### Ground zero: reception is measured from the epoch, not from birth

**The practice went live on 2026-08-16** (`history.start_date`). Every star,
subscriber and view banked before that date came from ad-hoc ventures of
interest — real achievements, but not this system's. Counting them as the
practice's output would be exactly the flattering accounting the discipline
section forbids.

So the headline is always the **delta since the epoch**, with the inherited
baseline shown beside it as context and labelled as such:

```
Reception since flow began (2026-08-16)

  YouTube subscribers, net           +0    (baseline 58 before flow)
  GitHub stars                       +0    (baseline 116 before flow)
```

Where an event stream exists the delta is **exact** — stars carry `starred_at`,
YouTube days are exact and backfilled, forum posts are timestamped. Counters that
are merely polled (forks, watchers) can only be measured from the first
observation, and say so rather than implying the epoch.

A corollary worth stating: the 2026 YouTube numbers below are *pre-flow* and stay
pre-flow. They are the best evidence available that publishing more coincides
with more reception — but they were earned before the practice began, and the
system does not get to claim them.

### Calibration, measured 2026-08-17

Recorded here because it sets expectations that no amount of tooling will change:

- **Stars are a decaying series.** 116 timestamped stars on
  `theHarmonicAlgorithm`: 18 (2018), 20 (2019), **37 (2020)**, 12, 11, 5, 8,
  2 (2025), 3 (2026 to date). Attention peaked in 2020 and faded. The cumulative
  total is a fair record of reach; at three to five a year the *rate* cannot
  support a trend claim on any horizon shorter than several years.
- **Clones are contaminated; views are not.** One fortnight showed 7 views from 5
  unique visitors against 55 clones from 41 unique cloners. Readers do not
  outnumber themselves eight to one — that is mirrors, CI and crawlers, and the
  largest clone days landed on a push, so clones partly measure your own activity.
- **Referrers showed only `github.com`.** No outside route in was visible at all.
- **Forum posts by outsiders: one, ever.**

**YouTube tells the opposite story**, and the contrast is the most useful thing
in this section. The Analytics API backfilled 6,204 days — exact daily figures
from 2009 — so unlike GitHub this needed no waiting:

| year | views | subs + | subs − | net | hours |
|---|---|---|---|---|---|
| 2022 | 200 | 2 | 1 | +1 | 1 |
| 2023 | 163 | 0 | 1 | **−1** | 1 |
| 2024 | 932 | 1 | 1 | 0 | 3 |
| 2025 | 3,997 | 8 | 0 | **+8** | 16 |
| 2026 (to Aug) | 1,501 | 18 | 1 | **+17** | 13 |

2026 is already the best year for net subscribers on record, ahead of 2021's +14,
with four months still to run — and it is also the heaviest publishing year ever
at 14 uploads against a previous maximum of nine. Production is up and reception
is up with it.

**That is an association across years, not a demonstration.** It is exactly the
horizon extension 7 endorses — cumulative reward on sustained commitment — and
exactly why the short-lag coupling is excluded: the same data at daily resolution
would show almost nothing but zeros.

Note the channel is **58 subscribers**, not the 2.13k an early page-scrape
suggested; that number came from a recommended-channel shelf on the page. The
value of YouTube here is not audience size but that its history is exact, daily
and complete, where GitHub's is a single running total observed from today.

So extension 6 may fire for GitHub while failing to fire for YouTube — the same
practice, two channels, opposite receptions. That is the honest baseline, and
having it recorded is what will make any future change legible.

## Discipline

Two rules govern everything built on this document.

**Pre-registration.** Hypotheses are written down before they are tested. Three
are already committed to publicly in article 05 — Train most often never-started;
Express longest appear→touch delay; Write-missed days depressing the other four.
Those are the ones the monthly review tests, phrased as they were published. New
hypotheses get added here, dated, *before* the analysis that examines them. It is
extremely easy to find a flattering pattern in a habit tracker after the fact.

**Decision criteria are Bayesian, from the start (decided 2026-08-18).**
The platform launched with the rolling posterior layer in place, so there is no
frequentist legacy to carry: the three published hypotheses are judged as
posterior probabilities of their published claims *including their published
effect margins*, computed by the seed-pinned Stan models in `models/` whose
priors are pre-registered in the model files themselves.

| | claim, as a posterior quantity | prior | model |
|---|---|---|---|
| H1 | P(θ_never,Train > 1.2 · max other θ_never) | hierarchical: μ~Beta(2,2), κ~Gamma(2,0.1) | `adherence_hierarchical.stan` |
| H2 | P(median_Express > 1.2 · max other medians) | α~Gamma(2,1), σ~LogNormal(ln 240, 1) | `latency_survival.stan` |
| H3 | P(completion gap ≥ 10 pp) | Beta(1,1) per arm | `beta_binomial.stan` |

Verdicts are **four-way**: `supported` at P ≥ 0.90, `not supported` at
P ≤ 0.10, `inconclusive` between — and `not testable yet` whenever the measure
is below its N-gate **or the sampler's own diagnostics failed** (R̂ ≥ 1.01,
bulk ESS ≤ 400, any divergence). The gate matters doubly under pooling: at
small N shrinkage drives every mode's lead-probability toward zero, and without
the gate absence of evidence would read as refutation.

Posteriors themselves are **always visible** — a 90% interval that spans half
the unit line is visibility of uncertainty, not a claim — and every
`(:Fct:Posterior)` row carries R̂, ESS, divergence count and a `trusted` flag,
so an untrusted fit can be stored as a fact about the sampler without ever
being read as a result.

**Effect sizes, also fixed in advance.** A hypothesis whose direction holds by a
single count or a single minute is not supported — it is a coin landing. Each of
the three carries a minimum effect, chosen before the data existed for the same
reason the hypotheses were:

| | bar | meaning |
|---|---|---|
| H1 | leader ahead of the runner-up by **20%** of its own count | Train being one ahead is not "most frequent" |
| H2 | leader's median ahead by **20%** | a few minutes' difference in a median is nothing |
| H3 | **10 percentage points** of completion rate | anything less is inside the noise at this N |

Verdicts are therefore three-way, not two: **supported**, **not supported**, and
**inconclusive** — the direction held, the margin did not. Collapsing that middle
case into "supported" is exactly how a habit tracker confirms whatever you hoped
it would.

The same logic gates the diagnostic table above: a row fires only when the two
modes it compares differ by **30 percentage points**. Prescribing a
transformation of R or T on a five-point gap is prescribing on noise.

**N-gating.** Five binary-ish outcomes a day is a thin signal. Rates and streaks
are noise for 8–12 weeks. Every metric and plot declares its minimum N and refuses
rather than misleads. "Not yet" is a valid result and the most likely one for the
first months.

And one standing caveat: none of this is causal. There is no randomisation, by
choice — the ordering randomisation on the board is for variety, not inference. A
good day plausibly raises both completions and output, so coupling between them is
confounded and must always be reported as such.
