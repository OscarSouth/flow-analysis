# The W.A.T.E.R. system

Five modes of engagement, one card each, every day. Not a to-do list — a check
that all five channels are still open.

| | mode | the nature of it |
|---|---|---|
| **W** | Write | Documenting or organising thoughts and actions. Planning, composing, journaling, outlining, structured notes. |
| **A** | Absorb | Absorbing new knowledge or information. Deliberate, focused input of knowledge or repertoire. |
| **T** | Train | Internalising through disciplined practice. Scales, drills, workouts — practice should be difficult so that performance is easy. |
| **E** | Express | Acting on unfiltered, authentic impulse and free association. Improvising, singing, sketching — no self-control. |
| **R** | Reveal | Exposing thoughts or actions to the broader culture. Live performance, streaming, publishing — leaving a documented record. |

The name came from the letters, but the metaphor holds: this is about **flow**,
and about noticing where flow has stopped. Water that stops moving stagnates.

## Why these five

A musical life is the clearest case, because all five are visibly distinct
practices and neglecting any one of them is immediately audible.

### Write — synthesis and logistics

Getting material out of working memory and into a form you can look at
objectively. Composition and notation sit here, as does the unglamorous half:
planning the week, outlining a project, structured notes on something just
learned.

*Neglected:* you become reactive and disorganised, busy but ineffective, with
ideas that never survive contact with the next day.

### Absorb — high-quality input

Deliberate consumption. Learning repertoire, active listening to a complex
piece, reading, studying a technical manual. The distinguishing feature is
attention: this is not background listening or scrolling.

*Neglected:* output goes stale and self-referential. You repeat yourself because
you are drawing from an empty well.

### Train — building capacity

Friction on purpose. Scales, drills, targeted workouts, language mechanics.
**Practice should be difficult so that performance is easy** — the point is to
raise the floor, not to enjoy the hour.

*Neglected:* you plateau. Still creating, but the technical ceiling stops
rising, and eventually ideas arrive that you cannot execute.

### Express — unstructured output

The editor off. Improvising, singing, freewriting, sketching, brainstorming.
No product, no self-control, no audience. This is where training and absorption
recombine into something you did not plan.

*Neglected:* the work turns rigid and mechanical. Technically clean, no spark.

### Reveal — structured output and feedback

Shipping. Live performance, streaming, publishing, pushing code, a difficult
honest conversation. The defining property is that it leaves a **documented
record** and meets an audience that did not have to be kind.

*Neglected:* perfectionism. A closed system, endlessly refining work nobody has
seen, increasingly afraid of the moment it is seen.

## The flow between them

They feed each other in a rough cycle — Absorb supplies Train, Train enables
Express, Express feeds Write, Write structures Reveal, Reveal creates the
pressure and feedback that sends you back to Absorb — but the cycle is not the
point. The point is that all five run *daily*, because they decay at different
rates and the ones that decay quietly (Absorb, Express) are the ones that take
the whole system down with them.

## Imbalance patterns — as analysis, not advice

The framework's real use here is diagnostic, and this repo already records
enough to test it. These are **hypotheses about the data**, phrased so that
`report.py` and the exported grid can settle them. They are not prescriptions to
follow; they are what to go looking for once there is a few months of history.

| pattern | the felt symptom | CSF mode | the claim, stated so data can test it |
|---|---|---|---|
| high Absorb / low Reveal | perpetual student — you know a lot, finished nothing | generative uninspiration (Reveal) | Absorb and Reveal completion rates diverge persistently over a rolling window |
| high Reveal / low Absorb | burnout, repeating yourself | approaching conceptual uninspiration | a Reveal streak precedes a fall in overall completion rate |
| high Train / low Express | technically strong, joyless | conceptual uninspiration | Express carries the longest median `minutes_to_start` of the five |
| high Express / low Train | good ideas, can't execute them | generative uninspiration | Train is the most frequent `never_started` outcome |
| Write neglected | anxious, dropped plates, busy but ineffective | traversal degradation, all modes | days where Write is missed show lower completion across the other four |

All five are joins and lags over the existing per-(day, activity) grid —
`outcome`, `minutes_to_start`, `minutes_to_complete` — not new instrumentation.
See `04-analysis.md` for the schema and `flow report --export`.

The reason to write these down now, before there is data, is to keep later
analysis honest: it is easy to find a pattern in a habit tracker after the fact.
These are the questions worth asking, fixed in advance.

**[06-diagnostics.md](06-diagnostics.md) takes this further**: it names which of
R, E or T each failure implicates — so the prescription follows from the diagnosis
rather than from mood — and adds the modes Wiggins has no vocabulary for, because
his systems are always running and a daily practice can simply fail to run:
allocation vs capacity failure, dormancy, adherence without production, and
observable productive aberration.

## Rules of the system

- **Five cards, every day**, refilled into `future` at 06:00 in W-A-T-E-R order.
- **Unfinished cards are archived at 04:00**, not carried over. A missed day is
  data, not debt — the point is the rate, not the backlog.
- **The day boundary is 04:00, not midnight**, so late-night work counts toward
  the day it belonged to.
- **Long-running work shares the same board** and is never touched, because it
  carries no `Flow` label.
