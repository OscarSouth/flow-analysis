# Instrumenting a Creative Practice: a Creative-Systems Account of a Measured Daily Discipline

*A practice-led research document. Evolving — see the revision log (§11).
Version 0.1.0, 2026-08-18.*

---

## Abstract

This paper describes a system for the sustained, measured practice of creative
behaviour: a small fixed set of daily engagement modes, an append-only record
of every day's outcomes, a derived knowledge graph over that record, and a
reviewing agent that reads the graph, quantifies its uncertainty, and writes
its own conclusions back. The system is given a formal account in the
vocabulary of Wiggins' Creative Systems Framework (CSF), extended where a
rate-limited human practice differs from the always-running computational
systems the framework was built for. Three things are argued. First, that the
CSF's central diagnostic separation — rules, traversal, evaluation — survives
the move from generative programs to daily human practice, and becomes *more*
useful there, because the failure modes of a practice attract interchangeable
folk remedies that the framework correctly distinguishes. Second, that the
reviewing agent is not an accessory but a formal component: the traversal
function of the meta-level system that searches the space of possible
practices, which makes consistent agentic behaviour a matter of specification
rather than aspiration. Third, that under small-N, cumulative, interconnected
observation, a rolling Bayesian treatment — posteriors always visible,
decisions gated — is the honest quantitative companion to the framework: it
distinguishes *absence of evidence* from *evidence of absence* by
construction, which is precisely the distinction the framework's failure
catalogue turns on. The account is deliberately abstract of any one
practitioner's data: it describes the state of the system, not the state of a
practice.

---

## 1. Practice-led framing

This document continues a line of practice-led work begun in *The Harmonic
Algorithm* (South 2016) and *Data Science in the Creative Process* (South
2018), both of which applied Wiggins' framework to working creative systems
under Candy's methodology. Candy (2006) distinguishes practice-*based* research,
where the creative artefact is itself the contribution, from practice-*led*
research, which "is concerned with the nature of practice" and aims "to advance
knowledge about practice, or to advance knowledge within practice". The present
work is practice-led in exactly that sense: the artefact under study is a
*practice* — a daily discipline and the instrument built around it — and the
knowledge sought is about how such a practice can be observed, diagnosed and
legitimately transformed.

Two methodological commitments follow from the framing and recur throughout:

- **Pre-registration.** Hypotheses about the practice are written down, dated,
  with their decision criteria, before the data that tests them is examined.
  A measured practice is a habit tracker at heart, and it is trivially easy to
  find a flattering pattern in a habit tracker after the fact.
- **Visibility versus inference.** A cumulative total or a current level is a
  fact and is always shown. A rate, a trend, a diagnosis or a verdict is an
  inference, and every inference declares the evidence it requires and refuses
  below it. "Not yet" is a result.

## 2. The practice under study

The practice is five modes of engagement, one instance each, every day, of
which any may be completed, started and abandoned, or never touched. The five
used in the reference implementation — Write, Absorb, Train, Express, Reveal —
are one instantiation; the account holds for any small fixed set whose members
decay at different rates and fail in different ways. Three properties matter
formally:

1. **The set is fixed by decision.** Its membership does not change. What
   remains open is each mode's *semantics* — the boundary of what counts as a
   valid instance of it (§6.4).
2. **A day is rate-limited and can simply fail to run.** Unlike a generative
   program, a practice has an allocation problem before it has a search
   problem. This single difference generates most of the extensions in §6.
3. **Outcomes are observed at three tiers**: *adherence* (did the practice
   run), *production* (did anything leave the building), *reception* (did
   anyone care). The tiers are kept apart with some ceremony, because
   conflating them lets a stranger's attention masquerade as one's own output.

## 3. Reading the formalism

The CSF papers are compact and symbol-dense. This section is the
domain-skillcheck: every core symbol and formula used in this paper, each with
a written intuition. A reader comfortable here can read Wiggins (2006a),
Wiggins (2006b) and Linkola & Kantosalo (2019) unaided.

### 3.1 The symbols

| symbol | read as | intuition |
|---|---|---|
| `U` | the universe | every concept that could possibly exist, useful or not, reachable or not. Nothing is created into existence; it is *located* in U. |
| `L` | a language | the notation rules are written in. Rules about music are written in some L; so are rules about days of practice. |
| `⟨x, y, z⟩` | a tuple | an ordered bundle: "a creative system is these seven things taken together". |
| `⟦R⟧` | interpretation of R | the double brackets turn a *description* of rules into a *working test*: `⟦R⟧(U)` is "run the rule set R over the universe and keep what passes". |
| `⟪R, T, E⟫` | the enumeration interpreter | turns rules, traversal and evaluation together into a *generator*: something that actually walks the space producing concepts, guided by all three. |
| `◊` (superscript) | iterate to closure | apply the generator again and again until nothing new appears — the system's *extensional limit*: everything it would ever produce, given unlimited time. |
| `{⊤}` | the top/empty concept | the featureless starting point; enumeration begins from nothing in particular. |
| `∅` | the empty set | "nothing". Most failure conditions are statements that some set *is* empty. |
| `\` | set difference | `A \ B`: what is in A but not in B. Aberration lives in a set difference. |
| `C = ⟦R⟧(U)` | the conceptual space | the subset of the universe the current rules admit: everything that *counts* as a valid concept, whether or not anyone ever reaches it. |
| `L*` | the space of rule sets | every possible rule set expressible in L. At the meta level this becomes the universe being searched. |
| `R, T, E` | rules, traversal, evaluation | the three questions of §4.1. |

### 3.2 The core formulae, with intuitions

**The exploratory septuple** (Wiggins 2006a):

    ⟨ U, L, ⟦·⟧, ⟪·,·,·⟫, R, T, E ⟩

*Intuition*: a creative system is a universe, a language to write rules in, two
machines for interpreting rules (one tests, one generates), and three rule
sets: what counts (R), how to look (T), what is good (E). Everything else in
the framework is bookkeeping over this bundle.

**Hopeless uninspiration**:

    ⟦E⟧(U) = ∅

*Intuition*: nothing in the entire universe would be valued. No agent in this
universe can ever produce anything worthwhile — unfixable from inside, since
every possible output already fails. In a practice: nothing that could ever be
done would satisfy. A statement about E so global it is close to a clinical
observation rather than a design one.

**Conceptual uninspiration**:

    ⟦E⟧(⟦R⟧(U)) = ∅

*Intuition*: the rules and the taste have come apart — nothing the rules admit
is valued, though valued things may exist *outside* the rules. The remedy is to
**transform R**. In a practice: the discipline is being kept and none of it
feels worth keeping; more discipline cannot help, because the problem is what
the discipline admits.

**Generative uninspiration**:

    ⟦E⟧(⟪R, T, E⟫◊({⊤})) = ∅

*Intuition*: valued concepts exist inside the rules, but this agent's way of
searching never reaches them. The mild, common, recoverable failure. Remedy:
**transform T** (and only then consider R). In a practice: the good days are
possible and simply never arrived at — an ordering, timing or method problem,
not a rules problem. Wiggins' warning, kept verbatim in this system's review
discipline: *check which failure it is before tearing up your rules.*

**Aberration**:

    ⟪R, T, E⟫◊({⊤}) \ ⟦R⟧(U) ≠ ∅

*Intuition*: the search produced things the rules do not admit. Whether that is
a problem depends entirely on what evaluation makes of the aberrant set B:

- **Perfect aberration** — `⟦E⟧(B) = B`: everything rule-breaking is valued.
  The rules are simply drawn too tight: transform R.
- **Productive aberration** — `⟦E⟧(B) ≠ ∅`: *some* of it is valued. The
  interesting case, and the only mechanism by which R ever legitimately
  changes. It requires E to be independent of R — if taste can only approve
  what the rules already permit, no rule-breaking thing can ever be found good,
  and the system can never transform itself.
- **Pointless aberration** — `⟦E⟧(B) = ∅`: none of it is valued. Transform T
  and leave the rules alone.

**Transformational creativity as meta-level exploration** (Wiggins 2006a):

    ⟨ L*, L_L, ⟦·⟧, ⟪·,·,·⟫, R_L, T_L, E_L ⟩

*Intuition*: changing the rules is itself a search — over the space of rule
sets, L*. That search needs its own well-formedness constraints (R_L), its own
strategy (T_L), and its own account of what makes a rule-change good (E_L). The
same interpreters serve. Nothing new is needed: transformational creativity
*is* exploratory creativity, one level up. §5 identifies the reviewing agent
with T_L.

**The societal extension** (Linkola & Kantosalo 2019): a society S of agents
has aggregate rule sets **R_S** (what the society accepts), **T_S** (what it
can reach), **E_S** (what it values), standing in DIFI terms
(Csikszentmihalyi 1988) as field-filtered domain membership. *Intuition*: the
individual's E and the society's E_S are different objects, and their
divergence is measurable. §6.5 builds a named failure mode on exactly that.

## 4. The practice as an exploratory creative system

### 4.1 The three questions

**R** — validity: what counts as a valid thing at all? **E** — evaluation: of
the valid things, which are good? **T** — traversal: how does the agent
actually get around the space? (The reference implementation writes the triple
R→E→T, matching an existing pipeline's module order; the difference from
Wiggins' R, T, E ordering is notational only, and noted wherever it appears.)

The practice instantiates the septuple as:

| component | in the practice |
|---|---|
| U | every possible day of creative work |
| L | the system vocabulary: the modes, four outcomes (completed, abandoned in progress, never started, never appeared), three tiers |
| ⟦·⟧ | the tests: was this a valid instance of a mode? did this day count? |
| ⟪·,·,·⟫ | the daily cycle itself — the scheduler that deals the day's modes and the practitioner who moves through them |
| **R** | the mode set and the day's structure (fixed boundary times, one instance per mode) |
| **T** | how days actually go: the order modes are reached for, how many run at once, how long each waits before first touch, which are reached at all |
| **E** | two evaluators — see below |

### 4.2 E splits, and the split is load-bearing

The practice has two evaluation functions, and confusing them destroys the
diagnostics:

- **E_A** — the practitioner's own evaluation, operationalised as *completion*:
  the practitioner judged the day's instance done.
- **E_S** — the field's evaluation, operationalised as *reception*: stars,
  views, subscriptions, replies from outside.

In DIFI terms the practitioner is the Individual; the accumulated record — the
knowledge graph itself — is the Domain; and the audience that decides what it
values is the Field. Domain-building is therefore not bookkeeping: every
conclusion written back into the graph is an artefact entering the domain
(§7.3).

## 5. The meta level: the reviewing agent is T_L

The system includes a reviewing agent — a language-model agent with structured
access to the record — whose role the framework makes precise: **the agent is
the traversal function of the meta-level system**. The object-level system
lives one day at a time; the meta-level system searches the space of possible
practices, and the agent is how that space is walked.

This identification is what makes "consistent agentic behaviour" a
specification problem. The meta-septuple's three rule sets are written down as
plainly as the object level's:

| meta component | content | realisation |
|---|---|---|
| **R_L** | what counts as a legitimate change to the practice: mode membership is fixed; mode *semantics*, traversal habits and evaluation criteria are open; every change is confirmed by the practitioner before it is recorded, because a recorded transformation segments all trend analysis | the interaction contract |
| **T_L** | the review cadence — a weekly traversal-level review, a monthly evaluation-level review against pre-registered hypotheses, a quarterly semantics review — with entry conditions decided by a deterministic brief rather than by mood | the review protocol |
| **E_L** | what makes a change worth making: pre-registered effect margins, evidence gates, posterior decision thresholds, sampler diagnostics | the discipline document and the model priors |

### 5.1 Dialogue as traversal: the socratic specification of T_L

Naming the agent T_L says *what* it is; it does not say *how* a language-model
agent should walk a space of possible practices in conversation with the
practitioner whose practice it is. That is specified dialogically: **T_L
traverses by socratic method** (`docs/10-socratic-practice.md`). The elenchus
is traversal-as-stress-test — a belief conforming to R_L is confronted with
premises drawn from E_L's own record, the queries and posteriors, and either
survives, refines, or falls; the *aporia* that ends a failed defence is banked
in the knowledge layer as the marked site of the next transformation.
Maieutics is the complementary constraint on authorship: the agent supplies
premises, evidence and questions, and the practitioner delivers every
conclusion — which is the T_L-shaped restatement of the first corollary below,
since a transformation the agent installed rather than midwifed would be
meta-level aberration however good it looked. Questioning intensity
("hardness") is itself threshold-governed in E_L's manner: judged from the
brief's prescribed depth, the topic's proximity to transformation, and the
practitioner's engagement in debate, and overruled by explicit request in
either direction.

The epistemic ground for all of this is the practice's central motif: **all
belief is provisional**. Under that commitment, cross-examination is
partnership rather than threat — Socrates' *boêtheia* — and the knowledge
layer makes the commitment structural: a belief is a node with a status,
revised by a successor that points back at what it replaced, so the record
keeps every position the practice has ever held and the path between them.

Two corollaries:

- **Agent proposals outside R_L are meta-level aberration**, and are treated
  exactly as the object level treats aberration: evaluated, and only adopted if
  E_L values them — which is why they are surfaced for confirmation rather than
  enacted.
- **Platform development is meta-transformation.** The platform is the
  instrumentation of T_L and E_L; extending it (a new measure, a new model, a
  new analytical capability) transforms what the meta-level can see and
  evaluate. The system therefore models its own development: an agent that
  hits an instrument's limit records a *development proposal* with an explicit
  gate; approved proposals become work; completed work is recorded as a
  platform transformation linked to the measures it enables. The register of
  proposals is itself part of the domain, queryable and reviewed on cadence.

## 6. Extensions for a rate-limited practice

Wiggins' systems are always on: their failures are failures of search and
valuation at the extensional limit. A daily human practice differs in one
decisive respect — *it can simply fail to run* — and the framework needs
vocabulary for that gap. Each extension below is measurable from the record.

### 6.1 Allocation failure versus capacity failure

Generative uninspiration is one label covering two problems the record
separates for free. A mode *never started* was never attempted: an
**allocation** failure, about time, attention and ordering. A mode *started
and abandoned* was attempted and not completed: a **capacity** failure, about
reach and skill. Same CSF label; opposite remedies. Prescribing drills for an
allocation failure is how a practitioner concludes they are lazy when they are
merely oversubscribed.

### 6.2 Dormancy

A mode unattempted for k consecutive days is **not** uninspiration — nothing
failed to be reached, because nothing ran. Dormancy masquerades as generative
uninspiration and attracts the wrong prescription. Short dormancy flags an
allocation question; long dormancy (weeks) escalates to a semantics question:
if a channel has been closed for three weeks and nothing has visibly suffered,
that is evidence about the rules' content, not about discipline.

### 6.3 Adherence without production

All modes completing, output flat. On the record this reads as total success;
in CSF terms it is the harmonious case — the practitioner values exactly what
they already do, so nothing generates the tension that provokes change. It is
conceptual uninspiration in slow motion, and it is invisible without the
production tier: the practice's own ledger can only ever report that the
practice ran.

### 6.4 Observable productive aberration, under fixed membership

Production appearing on days the practice was skipped is valued output from
outside R — the empirical signature of productive aberration, and in the
original formulation the trigger for changing the mode set. This system fixes
membership by decision, which *relocates* rather than closes the question:
productive aberration now argues either that **a mode's boundary is drawn
wrong** (the valued work belonged inside an existing mode whose semantics are
too narrow) or that the finding is about T. The quarterly review asks exactly
this, mode by mode: does the substantive content of each still match what is
done and valued?

### 6.5 Evaluation divergence: E_A ≠ E_S

Consistent production with no reception is invisible to both the adherence and
production tiers. Formally it is a divergence between the individual's
evaluation and the field's — distinct from conceptual uninspiration, where R
and E diverge *within* the individual. The societal extension gives it a name
and a location: E_A ≠ E_S. The prescription is not "promote harder"; the
diagnosis says *evaluation*, so the question is what the practitioner values
and why the field disagrees — and one legitimate answer is that the field is
wrong, and to continue. Divergences of this kind rarely announce themselves in
a number alone; the socratic dialogue of §5.1 is the mechanism that surfaces
them, because "what do you value here, and why might the field not?" is a
question only the practitioner can answer.

### 6.6 Cumulative commitment against cumulative reward

The governing measurement principle: the system measures the cumulative reward
on sustained commitment, never the immediate impact of a specific effort.
Reception answers to work shipped years ago and to paths of discovery outside
any practice window; coupling it to a given day or week would manufacture a
number out of nothing. Two rules follow by design, not threshold: no
lag-correlation between practice and reception at any lag, ever; and
visibility always, inference gated.

## 7. The measurement architecture, abstractly

### 7.1 Record, derivation, and one source of analysis

The record is an append-only archive: every observation lands once, keyed to
be idempotent, and is never rewritten. Everything analytical is *derived* —
staged, enriched, judged — into a labelled property graph that is rebuildable
from the archive alone, with no external calls, verified by test. The graph is
the **sole analysis source**: every human-facing surface reads it and only it,
because two analysis paths over the same data eventually disagree. The graph
being derived is what makes it safe; the archive being primary is what makes
the graph disposable.

### 7.2 The dense grid and the dense calendar

Absence is a finding. The core analytical object is a dense grid — one row per
(day, mode) whether or not anything happened — over a dense calendar in which
a day with no activity still exists. Only a dense structure can distinguish
"the practice failed to run" from "the machinery failed to record", and the
two must never be conflated: a scheduler fault is not a missed day.

### 7.3 The knowledge layer

The agent's conclusions are captured into the same architecture: a closed
vocabulary of entity types — reviews, interpretations, prescriptions,
transformations, hypotheses, gate-openings, development proposals,
observations — validated at the moment of capture, snapshotted append-only
into the archive, and placed in the graph linked to the calendar and to the
measures they concern. Two properties carry the weight:

- **The vocabulary is closed and refused loudly.** Consistency of capture is a
  grammar, not a hope. Extending the vocabulary is itself a platform
  transformation.
- **The working set is mutable; the record is not.** The agent drafts and
  corrects in a scratch layer; promotion is content-addressed and append-only,
  so the record keeps every state a conclusion passed through while the graph
  holds the current one.

This is the domain-building loop of §4.2: review conclusions become artefacts
in the domain that future reviews retrieve, so the system accumulates history
and judgement, not just telemetry.

The socratic layer (§5.1) extends the vocabulary with the two artefact kinds
dialogue produces: a **belief** — a conviction about the practice, captured in
the practitioner's exact words with a lifecycle status (`held`, `revised`,
`retired`) — and a **reference**, an external source brought into the
dialogue. A belief is revised by a successor that points back through a
`revises` edge, evidence bears on it through `challenges` and `supports`, and
sources are joined by `cites` — so provisionality is a graph shape rather than
a disclaimer, and the accumulated belief network is a navigable record of how
the practice's self-understanding evolved.

### 7.4 The brief

Every engagement opens with a deterministic brief computed from the record:
what is stale, which review is due, what changed since anything was last
examined, **which questions have just become answerable**, and which captured
loops remain open. The brief prescribes the engagement's depth from a fixed
table. The newly-answerable question embodies the system's stance in one
mechanism: an analytics layer built on refusing under-evidenced questions owes
the practitioner an *event* at the moment a question stops being refused.

## 8. Inference: the rolling Bayesian layer

### 8.1 Why Bayesian, here

The record is small-N, cumulative and interconnected: five bounded outcomes a
day, counts that arrive in bursts, latencies censored by the day's edge. In
this regime point estimates oscillate and binary refuse/answer gates discard
what little the data does say. A posterior distribution is the honest middle:
**always visible** — a wide interval is visibility of uncertainty, not a
claim — while **decisions stay gated**. The gate matters doubly under
hierarchical pooling: at small N, shrinkage drives every mode's
lead-probability toward zero, and without an explicit "not testable yet" state
the absence of evidence would read as refutation — precisely the misreading
the framework's failure catalogue exists to prevent.

### 8.2 The models

Inference runs in a probabilistic programming language (Stan), each model a
declarative file whose priors are pre-registered in the file itself and
recorded as hypothesis entities in the knowledge layer. Sampler diagnostics —
split-R̂, bulk effective sample size, divergent transitions — are stored on
every posterior snapshot, and a fit that fails them is marked untrusted: kept
as a fact about the sampler meeting this data, never read as a result. The
sampler is held to algebra in the test suite: on a conjugate case it must
reproduce the closed-form posterior.

| model | question | CSF location |
|---|---|---|
| hierarchical completion | each mode's completion rate, partially pooled through a practice-level prior — "is this mode genuinely different?" | E_A over T |
| censored latency survival | time from a mode's appearance to first touch, right-censored at the day's end; the survival plateau **is** the allocation-failure probability, and the median is unconditional (unlike a median over started days, which conditions away the failures) | the allocation/capacity split of §6.1 |
| conditional contrasts | completion of the other modes on days a condition mode was done versus missed — the pre-registered facilitation questions | co-occurrence structure of T |
| cumulative cascade | windowed production counts against cumulative adherence, and windowed reception against cumulative production, at long horizons only, overdispersion-tolerant | §6.6, with the confounding stated every time it is read |

Daily re-fitting over cumulative data yields an evolving sequence of
posteriors per measure — the record of *beliefs over time*, retrievable from
the graph like any other history, so a review can ask not only "what do we
believe now?" but "when did we start believing it?".

### 8.3 Staged models, gated in the open

Latent-state models are registered, not built: a hidden Markov model over the
daily outcome vector — the latent regime being, formally, the state of the
creative system that the platform cannot observe — gated on accumulated days;
topic models over production and reception text, gated on corpus size; a
multivariate probit for joint mode dependence, gated with the HMM. Each lives
in the development-proposal register with its gate, so "later" is a queryable
condition rather than a memory. Graph-analytic capabilities follow the same
discipline: similarity structure (which modes travel together, which past day
most resembles today) is computed as visibility now; anything that *names*
clusters or regimes waits for its gate.

## 9. The implementation, at a high level

The reference implementation, for concreteness; the architecture is the claim,
not the toolset. What follows is not an implementation guide but a mapping:
each named technology, an intuition for what it does here, and the part of the
theoretical framework it realises. Read column three as the point of the
section — every component earns its place by giving some element of the formal
account a physical location.

| technology | what it does here | theoretical role |
|---|---|---|
| **Trello + Butler** | the daily engine: five cards dealt each morning, the unfinished swept at the day boundary, entirely on hosted automation with no local dependency | the **enumerating interpreter ⟪R,T,E⟫** — the machinery that actually runs the day — and the physical embodiment of R's day-structure |
| **JSONL archive** (newline-delimited JSON, append-only, deterministic ids) | the primary record: every observation lands exactly once and is never rewritten; the only store whose loss would lose anything | the **domain's substrate** — the accumulated record from which every other representation is derived; the guarantee that history is append-only is what makes pre-registration meaningful |
| **Python / Polars** (pure functional core, `metrics/`) | all computation as pure functions over frames: the grid fold, the gates, the diagnostics — importing nothing that fetches or persists, enforced by test | **⟦E_A⟧ and the diagnostic calculus** — the testing interpreter applied to the record; purity is what makes every judgement reproducible from arguments alone |
| **Dagster** (software-defined assets) | the dependency graph raw → staged → enriched → facts → knowledge, with lineage, run history and freshness owned by the orchestrator; one sync materialises everything | the **structure of derivation itself** — which knowledge depends on which observation is a first-class, inspectable object rather than an emergent property of scripts |
| **Neo4j** (labelled property graph, GDS) | the derived store and sole analysis source: observations, judgements, beliefs and the practice's self-record in one queryable graph, rebuildable from the archive with no network | the **domain, made navigable**: the calendar chain, the mode structure, the knowledge layer's links (review → interpretation → prescription → outcome) are relations, so the meta-level's questions are queries; GDS supplies observed *structure* (visibility) while inferential structure waits at its gates |
| **Stan / CmdStanPy** (declarative models, seed-pinned) | the rolling posterior layer: each inference a versioned model file whose priors are pre-registered in the source, refit daily over cumulative data, with the sampler's own diagnostics stored beside every result | **E_L made quantitative** — beliefs with honest widths, decision thresholds fixed in advance, and the four-way verdict (including *not testable yet*) that keeps absence of evidence from reading as refutation |
| **marimo** (reactive notebooks) | the literate surfaces: narratives readable top to bottom in which every visual is introduced, shown and read, over live graph queries | the **explanatory face of E_L** — where judgements are argued rather than merely stored; the literate contract is the discipline section applied to presentation |
| **claude.ai artifact** | the summary dashboard: one self-contained page, updated in place | the glance-level view of the same single source — visibility with no inference surface at all |
| **MCP servers** (six: graph, orchestrator, notebooks, capture, code, docs) | the agent's thinking-level access: read everything, write only through the validated capture channel | the **sensorium and pen of T_L** — what the meta-level traversal can perceive, and the one constrained channel through which its conclusions enter the domain |
| **memory MCP + taxonomy** (closed vocabulary, validated at capture) | the agent's working set, promoted append-only into the archive and graph | the **grammar of the meta-level's writes**: R_L applied to the agent's own output — an entity outside the vocabulary cannot become part of the record |
| **pytest / hypothesis suites** | offline guards (layering, equivalence, taxonomy refusal, verdict gating) and integration proofs (rebuildability with the network blocked, sampler-versus-algebra calibration) | the system's **⟦·⟧ applied to itself** — well-formedness checks in Wiggins' sense, run continuously: the platform is disproved unsound before it can lie |

How they fit together, in one motion: the enumerating interpreter (Trello)
runs the day; the archive records it; the asset graph (Dagster) derives the
domain (Neo4j) from the record; the pure core and the Stan layer apply the two
evaluations — the practitioner's and the field's — with quantified honesty;
the agent (T_L) reads all of it through its protocol servers, reasons in the
framework's vocabulary, and writes its conclusions back through the validated
channel, growing the domain the next review will read. Every arrow in that
sentence is a tested, rebuildable derivation, and the one human in the loop
sits exactly where the theory puts them: confirming transformations.

## 10. Discipline, restated as one paragraph

Hypotheses are pre-registered with their margins and priors; posteriors are
always visible; verdicts are four-way (supported, not supported, inconclusive,
not testable yet) and gated on both evidence and sampler diagnostics; nothing
is causal and coupling is reported as confounded every time; reception is
never lag-correlated with practice; absence is recorded densely so that a
system fault can never impersonate a missed day; the record is append-only and
the graph rebuildable; the agent's own conclusions enter the record through a
closed, validated vocabulary; and every change to rules, semantics or
instrument is a dated, confirmed transformation that segments all trend
analysis crossing it.

## 11. Revision log

| version | date | scope |
|---|---|---|
| 0.1.0 | 2026-08-18 | First complete account: CSF formalisation and notation guide; rate-limited extensions; agent-as-T_L and platform development as meta-transformation; measurement architecture; rolling Bayesian layer with gated verdicts; staged-model register; §9 technology-to-theory mapping. |
| 0.2.0 | 2026-08-18 | The socratic layer: §5.1 dialogue as T_L's traversal (elenchus, maieutics, judged hardness); "all belief is provisional" named as the epistemic ground; Belief/Reference join the knowledge vocabulary (§7.3) with the `revises` chain as structural provisionality; §6.5 cross-reference; socratic sources added to §12. Method in full: `docs/10-socratic-practice.md`. |

Revisions ride the same mechanism they describe: a change to the system that
alters this account is a platform transformation, and updating the paper is
part of landing it. The quarterly review checks for drift.

## 12. References

- Boden, M. A. (1990/2004). *The Creative Mind: Myths and Mechanisms*.
  Routledge.
- Candy, L. (2006). *Practice Based Research: A Guide*. CCS Report 2006-V1.0,
  University of Technology Sydney.
- Candy, L., & Edmonds, E. (2018). Practice-Based Research in the Creative
  Arts: Foundations and Futures from the Front Line. *Leonardo*, 51(1), 63–69.
- Carpenter, B., Gelman, A., Hoffman, M. D., et al. (2017). Stan: A
  Probabilistic Programming Language. *Journal of Statistical Software*,
  76(1).
- Csikszentmihalyi, M. (1988). Society, culture, and person: a systems view of
  creativity. In R. J. Sternberg (ed.), *The Nature of Creativity*. Cambridge
  University Press.
- De Dominicis, S., & Stelter, R. (2023). A new purpose for Socratic
  questioning in coaching. *Philosophy of Coaching*, 8(1), 21–32.
- Gelman, A., Carlin, J. B., Stern, H. S., Dunson, D. B., Vehtari, A., &
  Rubin, D. B. (2013). *Bayesian Data Analysis* (3rd ed.). CRC Press.
- Kaplan, E. L., & Meier, P. (1958). Nonparametric Estimation from Incomplete
  Observations. *Journal of the American Statistical Association*, 53(282),
  457–481.
- Linkola, S., & Kantosalo, A. (2019). Extending the Creative Systems
  Framework for the Analysis of Creative Agent Societies. *Proceedings of the
  Tenth International Conference on Computational Creativity (ICCC 2019)*.
- Padesky, C. A. (2019). *Action, Dialogue & Discovery: Reflections on
  Socratic Questioning 25 Years Later*. Invited address, 9th World Congress
  of Behavioural and Cognitive Therapies, Berlin.
- Paul, R., & Elder, L. (2006). *The Thinker's Guide to the Art of Socratic
  Questioning*. Foundation for Critical Thinking.
- Plato. *Theaetetus* (148e — the maieutic passage).
- South, O. (2016). *The Harmonic Algorithm*. MA thesis, University of
  Chester.
- South, O. (2018). *Data Science in the Creative Process: Composing with
  Functions*. Higher Diploma final report, Dublin Business School.
- Vlastos, G. (1982). The Socratic Elenchus. *The Journal of Philosophy*,
  79(11), 711–714.
- Wiggins, G. A. (2001). Towards a More Precise Characterisation of Creativity
  in AI. *Proceedings of the ICCBR Workshop on Creative Systems*.
- Wiggins, G. A. (2003). Categorising Creative Systems. *Proceedings of the
  IJCAI Workshop on Creative Systems*.
- Wiggins, G. A. (2006a). A preliminary framework for description, analysis
  and comparison of creative systems. *Knowledge-Based Systems*, 19(7),
  449–458.
- Wiggins, G. A. (2006b). Searching for Computational Creativity. *New
  Generation Computing*, 24(3), 209–222.
- Wiggins, G. A. (2016). *Characterising Computational Creativity* (tutorial).
  Seventh International Conference on Computational Creativity, Paris.
- Wiggins, G. A., & Forth, J. (2018). Computational Creativity and Live
  Algorithms. In A. McLean & R. T. Dean (eds.), *The Oxford Handbook of
  Algorithmic Music*. Oxford University Press.
