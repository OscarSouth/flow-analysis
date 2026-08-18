# Butler rules — the authoritative spec

**This file is the only durable record of these rules.** Trello's REST API cannot
read or write automations, so nothing here can be verified programmatically or
restored from a backup. If you change a rule in the UI, change it here too.

Board `flow` (`5a154e6d562db6cb027e211e`, renamed from `solo` 2026-08-16). Automation timezone: **Europe/London**.
Label: **`Flow`**, colour **sky**.

---

## Status — 2026-08-17: four rules, all verified

Rule 4 (five on top, in varying order) was added 2026-08-17 and verified with
**Run now**; see its section below for what Butler's action vocabulary does and
does not allow.

All three original rules were rebuilt on 2026-08-16 after the Flow / W.A.T.E.R. rename broke the old
ones (see the label-binding finding below), and the three obsolete rules were
deleted. The sweep was verified with **Run now** against a labelled test card:
it moved to `drain`, and both unlabelled long-running cards stayed put.

`flow refill` / `flow drain` remain as manual fallbacks if Butler is ever
unavailable. They read `config/board.yaml`, so they produce exactly what the
rules do.

---

## The finding: Butler binds labels by **name**, not id

This is the important thing learned, and it is not documented anywhere.

The label was renamed `Focus` → `Flow` via the API. The label **id was
unchanged** — the same label object, same cards, only the name differed. The
expectation was that rule 1 would follow it.

It did not. Rule 1's saved text still read `green "Focus"`, and triggering it
with **Run now** against a correctly-labelled test card produced:

```
16 August 2026 at 18:25
  The automation finished running.
```

No "Moved card" line — compare a working run, which logs the move explicitly.
The rule executed and matched nothing.

**Consequences:**

- Renaming a label silently breaks every rule referencing it. The failure is
  quiet: the rule still exists, still runs, still reports success, and does
  nothing.
- Same caution applies to **list names** — renaming `future`, `present`, `past`
  or `drain` breaks every rule mentioning them. This was borne out immediately:
  renaming the lists in the same session broke all three rules at once, which is
  why all three were rebuilt rather than edited.
- Rule text in the list view is the *stored* text, not a live render. If it
  disagrees with the board, the rule is stale, not the display.

**Use "Run now"** (the rocket icon on each scheduled rule) to verify any rule
against real cards. It is far better than the board-button proxy used
previously, because it exercises the actual saved rule.

---

## The four rules, exactly as saved

```
1.  every day at 4:00 am, move each card with the sky "Flow" label
    not in list "past" to list "drain"

2.  every day at 4:05 am, archive all the cards in list "drain"

3.  every day at 6:00 am,
      create a new card with title "Write"   and description "…" in list "future" and add the sky "Flow" label,
      create a new card with title "Absorb"  and description "…" in list "future" and add the sky "Flow" label,
      create a new card with title "Train"   and description "…" in list "future" and add the sky "Flow" label,
      create a new card with title "Express" and description "…" in list "future" and add the sky "Flow" label,
      create a new card with title "Reveal"  and description "…" in list "future" and add the sky "Flow" label

4.  every day at 6:05 am, shuffle the cards in list "future", and move each card
    in list "future" with the sky "Flow" label to the top of list "future"
```

Descriptions are the two-sentence texts in `config/board.yaml` — copy them from
there verbatim. Butler's create-card action **does** support a description: the
pencil icon beside the title field opens an "and description" textarea
(confirmed 2026-08-16).

Order matters only cosmetically — W-A-T-E-R so the list reads in acronym order.

---

## Rule 4: the five on top, in varying order

The day's five sit above whatever ad-hoc cards are in `future`, and not always in
W-A-T-E-R order — a nudge against always starting with Write. For variety,
explicitly **not** for inference; nothing in the analysis treats card order as
randomisation, and `pull_rank` measures the order you *chose* to work in.

Two actions, in this order, because a batch move must be last:

1. `shuffle the cards in list "future"`
2. `move each card in list "future" with the sky "Flow" label to the top of list "future"`

### What the action vocabulary actually offers

Explored 2026-08-17, and the findings constrain the design:

| action | filter? | verdict |
|---|---|---|
| `move N randomly-selected cards from list X to list Y` | **no** | unusable — it could pick an ad-hoc card |
| `shuffle the cards in list X` | **no** | usable only because step 2 re-sorts afterwards |
| `move each card […] to [the top of / the bottom of / ] list X` | **yes** | the one that carries the Flow condition |
| `create a new card … in list X` (rule 3) | n/a | **no position option at all** — hence rule 4 |

Only the `move each card` action takes a filter, so it is the only one that can be
restricted to `Flow`. That is why the shuffle has to come first and be corrected,
rather than being the whole rule.

**Both filter conditions are load-bearing.** `with the sky "Flow" label` keeps
ad-hoc cards from being repositioned; `in list "future"` keeps a Flow card that is
already in `present` from being yanked back out of your hands mid-morning. Neither
is optional.

`move each … to the top` **reverses** the order it walks, so the visible order is
the reverse of the shuffle. Irrelevant — the reverse of a shuffle is a shuffle.

### Accepted side effect

The shuffle has no filter, so ad-hoc cards in `future` have their order *among
themselves* shuffled too. They stay below the five and never change list, so
nothing is lost — but the ordering of your own queue in `future` is not stable.
Chosen deliberately on 2026-08-17 over the alternative (lift-to-top only, fixed
W-A-T-E-R order every day).

### Verified live, 2026-08-17

Three **Run now** firings against real cards:

- `future` went Write/Train/Express/Reveal → Express/Train/Reveal/Write, then
  Express/Reveal/Train/Write on a later run — the shuffle is real and varies.
- With a deliberately unlabelled `ZZ TEST ad-hoc` card placed at the **top** of
  `future`, all four Flow cards moved above it and it fell to the bottom.
- `present` was untouched throughout: the long-running unlabelled card and the
  `Absorb` card both stayed exactly where they were.

---

## Why the drain takes two rules and a scratch list

The obvious design — *archive cards in `future` and `present` that carry the
Flow label* — cannot be expressed. Trello offers exactly three archive actions
and none combines a list with a label:

| action | why it doesn't work here |
|---|---|
| `archive all the cards in list […]` | no label filter → would archive your long-running cards |
| `archive all the cards with a "…" label` | board-wide → would archive completed cards in `past`, destroying the record |
| `archive each card marked as complete` | keys off due-date completion, not this workflow |

`move each card […] to list […]` **does** take a composable filter, and its list
condition has an `in` / **`not in`** toggle. So the sweep is a single negative
condition — `not in list "past"` — which catches `future` and `present` together
without naming them.

Then a second constraint bites: **"Can't perform additional actions after a batch
card copy/move."** A batch move must be the *last* action in a command, so the
archive cannot be chained after the sweep. Hence rule 2, five minutes later,
archiving the scratch list the sweep emptied into.

`drain` therefore sits on the board permanently but holds cards only between
04:00 and 04:05.

---

## Safety: what protects your long-running cards

The `Flow` label, and nothing else. Cards without it are invisible to rule 1.

Verified on 2026-08-16 by triggering the sweep with a labelled test card present:

```
Running "ZZ TEST sweep" on board "solo"
Moved card https://trello.com/c/NHy6SO5v to list "drain".
```

One card moved — the labelled one. `Set up trello focus tickets` (in `future`) and
`Finish developing/working through snippets` (in `present`) were untouched,
as was everything in `past`.

Re-check any time with `uv run flow check`, which lists what would be swept and
what would be spared. Confirm with **Run now** after any rule change.

---

## Day boundary

04:00, not midnight. Work finished at 01:00 belongs to the previous day — the
sweep hasn't run, the card is still in `present`, and moving it to `past` is
finishing yesterday's work. `util.flow_day` uses the same boundary, so the
statistics agree with the board.

The sweep must always precede the refill. `config.py` refuses to load a config
where `drain_at >= refill_at`.

---

## Quota

Trello Free: **250 automation runs**, **2,500 operations**, 250 emails per month,
pooled across the whole Workspace.

| | runs/month | operations/month |
|---|---|---|
| Rule 1 (sweep) | 30 | ≤ 150 |
| Rule 2 (archive) | 30 | ≤ 150 |
| Rule 3 (refill) | 30 | ~150 |
| Rule 4 (top + shuffle) | 30 | ~180 |
| **Total** | **120 / 250** | **~630 / 2,500** |

### The trap: never add event-triggered rules

A rule like *"when a card is moved to `past`, …"* fires **once per card** — five
cards a day is **150 runs/month**, more than the entire remaining budget, for
statistics this repo already derives locally.

New metrics go in `report.py`. Watch consumption at Automation → **Activity**,
which shows runs and operations used this period.

---

## Card titles are a contract

Rule 3 (the refill) creates cards by literal name; `metrics/grid.py` joins on it. Changing
`activities` in `config/board.yaml` means editing rule 3 in the Trello UI too, or
the new activity records as `never_appeared` forever.

No `{date}` in the titles: Trello card ids embed their creation timestamp in the
first 8 hex characters, so every card already reports its own date.

---

## The builder outage, and how to get round it

**Deep-linking to `…/butler/schedule/new` fails; clicking "Create automation"
from the list view works.** That is the single most useful workaround found.

It recurs. On **2026-08-17** the same outage returned: the list view rendered all
three rules correctly while `…/schedule/new` and `…/schedule/edit/…` both hung on
the spinner — from a fresh click on "Create automation", from the rule's pencil
icon, and after a reload. Network showed every top-level asset at 200 and
`proxy/butler/powerup-commands` and `proxy/butler/settings` answering on the list
view but **never re-requested on the builder routes**, so the iframe hangs before
it issues its own calls. Nothing local fixes it; wait it out.

On 2026-08-16 the Butler **list** view worked normally while the **create** and
**edit** views spun indefinitely — through hard reloads, across ~3 hours, with
one brief window in which a rule could be built. Symptoms:

- `…/butler/schedule/new` and `…/butler/schedule/edit/…` show a spinner forever
- an invisible overlay sometimes intercepts clicks across the whole pane
- typing then reaches the page as Trello keyboard shortcuts — **`b` opens the
  board switcher**, which is the tell that a field never took focus

The builder is inside an **iframe**, so it does not appear in the accessibility
tree and cannot be driven by element reference — only by coordinates, which
makes it fragile if the window is resized mid-session.

Toggling rules on/off *does* work from the list view during an outage, which is
the safe way to park the system.

---

## Rebuilding from scratch

1. Board → **Automation** → **Scheduled** → **Create automation**
2. **+ Add Trigger** → clock icon on the `every day` row → set time → `+`
   (the hour defaults to whatever you last used — check it)
3. **Move Cards** (rules 1, 2) or **Add Card** (rule 3) → fill the row → blue `+`
4. Rule 1's filter: click the funnel, use the `in`/`not in` toggle, type the list
   name, press its `+`; reopen the funnel for the label condition, press its `+`.
   **The label picker defaults to an arbitrary colour — select `Flow` explicitly.**
5. Rule 3's description: pencil icon beside the title field.
6. **Save**, then read the saved text back and compare it to this file.
7. **Run now** on rule 1 with a labelled test card to confirm it matches.

Note: **Escape** closes the whole Butler modal and discards the draft — use
**Cancel**. And a list created while the modal is open won't appear in its
autocomplete until the page reloads.
