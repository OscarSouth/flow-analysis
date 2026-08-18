# Trello API notes

Everything here was verified against Atlassian's own documentation in August 2026.
Much of what's written about Trello automation online is pre-2019 and wrong.

## What the API can and cannot do

| | |
|---|---|
| Boards, lists, labels, cards, checklists, comments, custom fields | Full CRUD |
| Board action history | Read, paginated |
| Archived ("closed") cards | Readable indefinitely |
| **Butler / automation rules** | **No endpoint at all.** Cannot be created, read, listed, or exported. |

There is no public API for automations — not a permissions issue, the endpoints
don't exist. Any workflow that needs rules under version control has to keep a
written spec instead; ours is `02-butler-rules.md`.

### Butler's own limits (found the hard way, not documented by Atlassian)

- **A batch `move each card` must be the last action in a command.** Adding
  anything after it fails with *"Can't perform additional actions after a batch
  card copy/move."*
- **No archive action accepts a list and a label together.** The three on offer
  are list-only, label-only (board-wide), or due-date-completion.
- **Card filters do support negation**: the list condition has an `in` / `not in`
  toggle, and conditions combine with AND.
- **Escape closes the whole Butler modal** and discards the draft.
- **A list created while the modal is open** won't appear in its autocomplete
  until the page reloads.
- **Butler binds labels by NAME, not id.** Renaming a label via the API — same
  id, same cards, new name — silently breaks every rule referencing it. The rule
  still runs and still logs success; it just matches nothing. Verified
  2026-08-16; assume the same for list names. See `02-butler-rules.md`.
- **"Run now"** (rocket icon on a scheduled rule) triggers the real saved rule on
  demand. This is the only reliable way to test a rule, and it beats building a
  board-button proxy.
- **The rule builder lives in an iframe**, so it is invisible to the
  accessibility tree and can only be driven by screen coordinates.

Together these force the drain into two rules plus a scratch list; see
`02-butler-rules.md`.

## Quotas (Free plan)

| | Free | Standard | Premium |
|---|---|---|---|
| Automation **runs**/month | 250 | 1,000 | unlimited |
| **Operations**/month | 2,500 | 20,000 | 150,000+ |
| Emails/month | 250 | 1,000 | — |

Pooled across the whole **Workspace**, not per board or per user. Total automation
definition size is capped at 64,000 characters across all rules.

**Run vs operation** is the distinction that decides whether a design fits:

- A **run** is one firing of one command, regardless of how many actions it has.
- An **operation** is one action taken during that run. A `for each card` action
  costs one operation per card it touches.

So five chained "create card" actions in one scheduled command = **1 run, 5
operations**. Five separate event-triggered rules = **5 runs**. On a 250-run
budget, that difference is the whole design.

Scheduled ("calendar") commands *are* available on Free. Sources claiming
otherwise describe Butler's pre-2019 pricing.

## Rate limits

- 300 requests / 10s per **API key**
- 100 requests / 10s per **token**

`client.py` retries 429 and 5xx with exponential backoff, honouring `Retry-After`.
This tool's volume is a few requests per weekly sync, so limits never bind.

## Action history

- `GET /1/boards/{id}/actions` returns **newest first**, max **1,000 per request**.
- `before=<action-id or ISO date>` walks backwards; `since=` bounds the newest end.
- The board's **JSON export** (Board menu → Print, export, and share) caps at the
  **1,000 most recent actions** and is therefore useless as a history source.
  `flow sync` uses the paginated API instead.
- Action ids are immutable, which is what makes the local store idempotent.

### Action shapes this project reads

```jsonc
// card created
{"type": "createCard",
 "data": {"card": {"id": "...", "name": "Read"}, "list": {"id": "..."}}}

// card moved between lists  <- this is a completion when listAfter is Out
{"type": "updateCard",
 "data": {"card": {"id": "...", "name": "Read"},
          "listBefore": {"id": "..."}, "listAfter": {"id": "..."}}}

// card archived  <- this is the drain
{"type": "updateCard",
 "data": {"card": {"id": "...", "closed": true}, "old": {"closed": false}}}
```

## Card ids carry their creation time

Trello object ids are Mongo ObjectIds: the **first 8 hex characters are the Unix
epoch of creation**.

```python
datetime.fromtimestamp(int(card_id[:8], 16), tz=timezone.utc)
```

Every card therefore self-reports its creation time with no API call and no date
baked into the card name. `util.card_created_at` does this.

## Auth

- Key: public, identifies the app.
- Token: full read/write to everything the granting member can see, no expiry
  unless requested. Revoke at <https://trello.com/my/account> → Applications.
- Both are passed as query parameters (`?key=…&token=…`), so never log a full
  request URL.

## Retention

Archived cards persist indefinitely unless explicitly deleted, so the nightly
drain loses nothing — `flow sync` pulls `/cards/closed` alongside open cards.
Board action history is not contractually retained forever, which is the reason
this repo keeps its own append-only copy.
