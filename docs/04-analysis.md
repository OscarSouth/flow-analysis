# Data model and metrics

## The store

Three files in `data/` (gitignored), all append-only:

| file | contents | dedup key |
|---|---|---|
| `actions.jsonl` | raw Trello board actions, verbatim | action id (immutable) |
| `cards.jsonl` | card snapshots, open and archived, with `observed_at` | content fingerprint |
| `state.json` | sync watermarks and coverage endpoints | — |

Cards are only re-appended when their meaningful state changes (list, name,
labels, closed, due), so a weekly full pull costs almost nothing on disk while
still preserving the full trajectory of every card.

## Why coverage can be trusted

Trello serves actions newest-first. Every fetch either extends the **newest** end
(`since=<newest action id>`) or the **oldest** end (`before=<oldest action id>`),
and both walk contiguously. The covered region is therefore **a single unbroken
interval by construction** — there is no interval-merging to get wrong, and
integrity reduces to comparing two endpoints against the requested span.

`flow sync` prints that check on every run, and `flow report` re-prints it as a
warning if the store is short, so a truncated history can never quietly appear as
a broken streak.

```bash
uv run flow sync                        # forward, plus backfill to start_date
uv run flow sync --backfill --since 2026-08-01
```

## Folding actions into rows

`metrics.grid.fold_rows` emits **one row per (flow day, activity)** — a dense grid, so
a day when the refill rule failed to fire appears explicitly rather than vanishing.

| field | meaning |
|---|---|
| `day` | flow day (see boundary below) |
| `activity` | Write / Absorb / Train / Express / Reveal (W.A.T.E.R.) |
| `outcome` | `completed`, `abandoned_in_progress`, `never_started`, `never_appeared` |
| `appeared_at` | from the card id's embedded timestamp |
| `started_at` | first move into `present` |
| `completed_at` | first move into `past` |
| `archived_at` | when the drain took it |
| `minutes_to_start`, `minutes_to_complete` | latencies from card creation |

**Membership**: a card counts as a flow card only if it carries the `Flow`
label *and* its name is one of the configured activities. Requiring both keeps a
stray hand-labelled card, or a long-running card that happens to be called
"Absorb", out of the statistics.

**Duplicates**: if a (day, activity) has more than one card — say the rule fired
and you also made one by hand — the better outcome wins, so a manual completion
still counts.

## The day boundary

The flow day runs **drain-time to drain-time** (04:00 by default), not midnight
to midnight. A completion at 01:00 is attributed to the previous day.

This is not a stylistic choice: it's what the board actually does. At 01:00 the
drain hasn't run, the card is still sitting in `present`, and moving it to
`past` is finishing yesterday's work. Any other boundary would make the numbers
disagree with the board.

## Metrics

`flow report` computes, from the rows alone:

- **Per activity**: completion count, days observed, rate, current streak, longest streak
- **Perfect days**: all five completed; count, current streak, longest streak
- **Outcome mix**: how failures split between never-started and abandoned-in-progress
- **Rolling 7 / 28-day rates**
- **Weekday effects**: completion rate by day of week
- **Latency**: median minutes creation→start and creation→done
- **Completions by local hour**: a histogram of when work actually lands

```bash
uv run flow report                          # human-readable
uv run flow report --json                   # summary as JSON
uv run flow report --rows                   # the raw grid as JSON
uv run flow report --export data/flow.parquet
uv run flow report --export data/flow.csv
```

## Surfaces

Three, all reading the graph through `graph/loaders.py` so they cannot
disagree:

1. the **CLI** — `flow report` / `flow evidence`, with the posterior snapshot;
2. the **summary dashboard** — `flow publish`, delivered as a claude.ai
   artifact and updated in place;
3. the **literate notebooks** — `flow.py` (practice narrative, the one
   permitted dashboard mirror) and `graph.py` (the guide to the graph),
   authored under `notebooks/README.md`:

```bash
uv run marimo edit notebooks/flow.py      # exploratory, interactive, 10 plots
uv run flow publish                       # static snapshot -> reports/dashboard.html
uv run flow publish --fixture 120         # the same page, on fabricated data
```

`flow publish` writes one self-contained HTML file, which is then published as an
artifact: private by default, one stable URL, nothing to host. Re-running and
re-publishing to the same URL updates the snapshot.

Two constraints shaped it, both worth knowing before editing `dashboard.py`:

- **The artifact runtime blocks external hosts.** A Vega-Lite CDN `<script>`
  renders nothing at all, silently. Charts are converted to inline SVG with
  `vl_convert` at render time.
- **Inline SVG cannot restyle itself for dark mode** — axis text, gridlines and
  series colours are baked in. Every chart is therefore rendered twice, once per
  theme, and CSS reveals the matching pair. The dark steps are their own
  validated values, not an inversion of the light ones.

`--fixture` writes its fabricated rows through `store.redirect()` into a
throwaway directory. It must stay that way: the store dedupes on id and only
appends, so fixture rows in `data/` can only be removed by editing the files.

## External signals

Three tiers, and the boundary between them is load-bearing — see
`docs/06-diagnostics.md`:

| tier | what it is | sources |
|---|---|---|
| `production` | what you put out | your forum posts, your uploads |
| `reception` | what came back | stars, traffic, subscribers, outsiders' posts |
| `internal_other` | an org-mate's output | counted as neither |

`metrics.production.production_by_day()` filters on the tier. Without that filter a
stranger's star would be read as your own output and
`adherence_without_production` — the one measure that detects quiet stagnation —
would say the opposite of the truth. `tests/test_production.py` pins it.

```bash
uv run flow auth github        # store a credential; input hidden, never in shell history
uv run flow probe github       # what the credential actually unlocks, endpoint by endpoint
uv run flow sync --signals     # poll every configured source
```

Sources are polled independently and a failure in one is reported rather than
raised, so a lapsed credential never costs you the others.

### GitHub, and its two traps

**Traffic is retained for 14 days.** A day not polled is gone for good. This is
the only genuinely time-sensitive thing in the repo — stars backfill whenever we
get to them, traffic does not.

**Today's traffic is skipped on purpose.** The counts are still accumulating, and
the store dedupes on id and never updates, so writing a partial figure would
freeze that day as permanently quieter than it was. A later sync collects it once
complete.

Both the per-day rows and GitHub's own 14-day window totals are stored. Prefer
the window for `uniques`: it is a true distinct-visitor count, whereas summing
daily uniques counts anyone who returned more than once.

## Reviews

`flow evidence` emits a compact brief — per-mode rates against the prior window,
which rows of the diagnostic table fire and on what numbers, the extension
measures, the pre-registered verdicts, and an explicit adequacy section.

```bash
uv run flow evidence --window 28          # the pack, as markdown
uv run flow evidence --window 28 --json   # the same, structured
uv run flow evidence --fixture 120        # on fabricated data
```

The split it enforces: **deterministic work in Python, judgement in the prompt.**
Nothing downstream recomputes a rate or eyeballs a trend from raw rows.

Three prepared reviews read it, as slash commands in `.claude/commands/`:

| | window | asks |
|---|---|---|
| `/flow-weekly` | 7d | what moved, what stalled, one change. Forbidden from naming a failure mode. |
| `/flow-monthly` | 28d | the three pre-registered hypotheses and the diagnostic table. |
| `/flow-quarterly` | 90d | the R-transformation review — should these still be the five? |

They are triggered by hand, never scheduled. A review that runs whether or not
anyone reads it is just noise with a timestamp.

## Taking it further

The exported grid is the natural handoff point. `outcome` is ordinal
(`never_appeared` < `never_started` < `abandoned_in_progress` < `completed`), so
it supports ordered-logit style modelling; `minutes_to_start` is the more
interesting continuous signal — it measures hesitation, and it is the quantity
most likely to lead a lapse.

Questions worth asking of the data:

- Does a miss on one activity predict a miss on another the same day, or the next?
- Does `minutes_to_start` drift upwards in the days before a streak breaks?
- Are the weekday effects real, or a handful of unusual weeks?
- Does the order you pull cards from `future` correlate with completion?
  (`actions.jsonl` has the exact sequence; the grid does not.)

The raw actions are kept verbatim precisely so questions the grid can't answer
stay answerable without going back to the API.

**`05-water.md` states the hypotheses worth testing** — the imbalance patterns of
the W.A.T.E.R. framework, written as claims about this grid rather than as
advice. They were fixed in advance deliberately: it is far too easy to find a
flattering pattern in a habit tracker after the fact.

## Embodiment

Apple Health is a **second observer of `Train`**, never a score. `Train` is one
lane — discipline-based embodiment — and nothing here splits it; the strength vs
instrumental distinction is for troubleshooting an output, not for scoring a day.

Drop an export at `ingest/export.zip` (iPhone Health app → profile → Export All
Health Data) and `flow sync --signals` picks it up. The file is ~750 MB of XML
inside the zip, so it is streamed with `iterparse` and cleared element by element.
Ids are deterministic fingerprints of `(type, start, value)`, so re-importing an
overlapping export costs nothing.

**Explicit workouts, body measurements and each workout's heart-rate series are
read.** Step counts, stand hours and activity rings are excluded: the watch is
worn while exercising or out of the house, so daily totals are
missing-not-at-random.

The heart-rate series (added 2026-08-21, devproposal:2026-08-21:
workout-intensity) lands as one `workout_hr` row per workout, paired 1:1 by the
workout's own fingerprint. HR records are top-level in the XML and precede the
Workouts, so the parse is two-pass: windows first, then the series, matched by
time window. The series is dense (~5 s cadence, 1,000+ samples) only for
sessions the watch itself tracked; other workouts carry a handful of background
readings, and the per-session statistics Apple embeds in the Workout element
(average/min/max HR, METs, active energy) ride the same row and speak for them.
The intensity features (`metrics/embodiment.py`: active span from first to last
sample at ≥70% of that session's max; mean/min within the span; capped
time-in-zone for cardio; refused below 30 samples or above a 60 s median
inter-sample gap) are computed at read time from the archived series, so the
provisional definitions can be revised without a fresh export. Measured on the
2026-08-21 import: 273 `workout_hr` rows, 15 of them usable — all 2026, the
watch-tracked era. The density gate earned its place immediately: a
forgotten-running 34-hour "hike" carried 85 background samples and drew a
2,058-minute active span on the first rendered surface.

Two findings from the first real import, 2026-08-17:

- Strength training records as **`FunctionalStrengthTraining`** — 208 sessions.
  `TraditionalStrengthTraining` appears **zero** times. Filtering on the obvious
  constant would have matched nothing and reported that no strength training had
  ever happened.
- Workouts stop at 2026-05-31 while body mass continues to the present day, so
  the export is current and the watch simply stopped logging. That is a gap in
  **measurement** — Oscar confirmed he trained and logged the card without
  wearing it. The surface refuses to read silence as absence.
