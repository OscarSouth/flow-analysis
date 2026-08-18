# Setup

## 1. Mint an API key and token

Trello ties API keys to Power-Ups, so creating one is a required formality even
though no Power-Up gets published.

1. Go to <https://trello.com/power-ups/admin>.
2. Create a Power-Up (name it `trello-flow`, any workspace, no URLs needed).
3. Open it → **API Key** tab → **Generate a new API Key**. Copy the key.
4. On that same page, follow the **Token** link, or visit this URL with your key
   substituted:

   ```
   https://trello.com/1/authorize?expiration=never&scope=read,write&response_type=token&key=YOUR_KEY&name=trello-flow
   ```

   Approve, then copy the token.

**Which of these is a secret:** the API key alone grants access to nothing and is
safe to expose. The **token** grants full read/write to every board you can see,
now and in the future, and never expires. Treat it like a password.

## 2. Store the credentials

```bash
cp .env.example .env
chmod 600 .env
$EDITOR .env          # paste key and token
```

`.env` and `data/` are gitignored. Nothing in this repo should ever contain the
token — if you paste it into a file, it belongs in `.env` and nowhere else.

## 3. Install

```bash
uv sync                          # core
uv sync --extra analysis         # adds polars + pyarrow for parquet export
uv run flow --help
```

## 4. Register the MCP server (for ad-hoc, prompt-driven Trello work)

```bash
claude mcp add trello -s user \
  --env TRELLO_API_KEY=your-key \
  --env TRELLO_TOKEN=your-token \
  -- npx -y @delorenj/mcp-server-trello
```

`-s user` matters: it writes the config to `~/.claude.json` rather than into this
project directory, so the token never lands next to the code.

Restart Claude Code, then check `/mcp` lists `trello` as connected. That server
exposes ~57 tools covering cards, lists, labels, boards, checklists, comments,
custom fields, and board activity. It cannot touch Butler automations — nothing
can, see `03-api-notes.md`.

## 5. Select the board

```bash
uv run flow discover                       # lists your boards with ids
uv run flow discover --select <board-id>   # records the choice
```

`--select` writes `config/resolved.json` and reports how the board's existing
lists and labels map onto the roles declared in `config/board.yaml`. If your
lists are named something other than future / present / past, edit the names in
`board.yaml` and re-run — bootstrap will map to yours rather than create new ones.

## 6. Prepare the board

```bash
uv run flow bootstrap            # dry run: prints exactly what it would add
uv run flow bootstrap --apply    # creates any missing list / the Flow label
```

Bootstrap only ever adds. It never renames, moves, or archives anything, because
the target board already holds real work.

Set `history.start_date` in `config/board.yaml` to today's date — the first day
the system is live. `flow sync` uses it to know how far back completeness must
be guaranteed.

## 7. Deploy the Butler rules

See `02-butler-rules.md`. These must be created by hand in the Trello web UI (or
by driving a browser); there is no API for them.

## Verify

```bash
uv run flow discover     # board, lists, labels all resolve
uv run flow check        # what the drain would archive vs spare — read this
uv run flow sync         # pulls history, reports integrity
uv run flow report       # metrics
uv run pytest -q          # offline tests of the folding + metrics
```
