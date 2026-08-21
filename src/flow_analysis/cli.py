"""flow — command line entry point."""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from . import bootstrap as bootstrap_mod
from . import discover as discover_mod
from . import orchestration, store
from . import report as report_mod
from . import sync as sync_mod
from .assets import raw as raw_assets
from .client import TrelloClient, client_from_env
from .config import Config, ConfigError, load_config
from .graph import loaders
from .metrics import diagnostics
from .metrics.grid import fold_rows, to_dicts
from .metrics.production import production_by_day

if TYPE_CHECKING:
    from collections.abc import Callable

    from .metrics.grid import FlowRow


def _ctx() -> tuple[TrelloClient, Config]:
    return client_from_env(), load_config()


def _grid() -> list[FlowRow]:
    """The flow grid, read out of the graph.

    Analysis reads Neo4j and only Neo4j — the archive stays the truth the graph
    is built from, but two analysis paths over the same data would eventually
    disagree. Raises loudly when the graph is down or empty.
    """
    return loaders.flow_rows()


def cmd_discover(args: argparse.Namespace) -> int:
    """Find the board, or describe the one already selected."""
    client, cfg = _ctx()
    with client:
        me = client.whoami()
        print(f"Authenticated as {me.get('username')} ({me.get('fullName')})\n")

        if args.select:
            detail = discover_mod.select_board(client, cfg, args.select)
            print(discover_mod.render_board(detail, cfg))
            print("\nSaved board selection to config/resolved.json")
            return 0

        if cfg.board_id:
            detail = discover_mod.describe_board(client, cfg.board_id)
            print(discover_mod.render_board(detail, cfg))
            return 0

        print(discover_mod.render_boards(discover_mod.list_boards(client)))
        return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Create whatever the board is missing — a list, the label — and resolve ids.

    Dry run by default. This and `refill` are the only writes this repo makes to
    Trello; the daily cycle belongs to Butler.
    """
    client, cfg = _ctx()
    with client:
        if args.apply:
            actions = bootstrap_mod.apply(client, cfg, adopt=args.adopt_label)
            print("Applied:")
        else:
            actions = bootstrap_mod.plan(client, cfg, adopt=args.adopt_label)
            print("Dry run (nothing changed). Re-run with --apply to commit:")
        for action in actions:
            print(action)

        if args.apply:
            print("\nIds written to config/resolved.json\n")
            print(bootstrap_mod.render_safety(bootstrap_mod.safety_check(client, cfg)))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Pre-flight the purge rule: what would it archive, what would survive."""
    client, cfg = _ctx()
    with client:
        print(bootstrap_mod.render_safety(bootstrap_mod.safety_check(client, cfg)))
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Pull the board into the archive, then report on what is missing.

    Runs the raw assets through Dagster in this process, so the run is recorded
    in the instance and visible in `dagster dev` — while the summary and the
    non-zero exit stay here, because scripts depend on them.

    Exits non-zero when history is incomplete rather than printing a clean
    summary over a gap: the archive is the only copy of anything older than
    Trello's 1,000-action cap, so an unnoticed hole is unrecoverable.
    """
    cfg = load_config()

    backfill = None
    if args.backfill:
        backfill = args.since or cfg.start_date
        if backfill is None:
            print(
                "--backfill needs either --since <YYYY-MM-DD> or "
                "history.start_date set in config/board.yaml",
                file=sys.stderr,
            )
            return 2

    written = orchestration.materialise_raw(
        with_signals=args.signals,
        backfill_from=backfill,
        all_actions=args.all_actions,
    )
    print()
    print("Sync complete.")
    print(orchestration.render_raw(written))

    report = sync_mod.integrity(cfg)
    print()
    print("Integrity:")
    if report.get("ok"):
        for note in report.get("notes", []):
            print(f"  OK — {note}")
    else:
        for problem in report.get("problems", []):
            print(f"  PROBLEM — {problem}", file=sys.stderr)

    # An export is a delivery mechanism, not a store. Once its rows are in
    # data/signals.jsonl the zip is dead weight, personal data left in a working
    # directory, and easy to commit by accident. Purge only after the import
    # actually succeeded — never after a failure, or the data would be lost.
    if written.get("raw_health_signals", {}).get("ok"):
        for removed in raw_assets.purge_consumed_export(cfg):
            print(f"  purged consumed export: {removed}")

    failed = [name for name, entry in written.items() if not entry["ok"]]
    if failed:
        print(
            f"\n  {len(failed)} asset(s) failed: {', '.join(sorted(failed))}",
            file=sys.stderr,
        )

    return 0 if report.get("ok") and not failed else 1


def cmd_memory_restore(args: argparse.Namespace) -> int:
    """Rebuild the memory MCP's working set from the archive.

    The archive is the truth; the working set is the MCP-owned fast store.
    Lossless by construction — observations are archived verbatim — so a
    re-snapshot of the restored file appends nothing.
    """
    entities, relations = raw_assets.restore_working_set(force=args.force)
    print(
        f"Restored {entities} entit(ies) and {relations} relation(s) to "
        f"{raw_assets.MEMORY_FILE}"
    )
    print(
        "Note: a running memory MCP server may need a session restart to "
        "pick up the rebuilt file."
    )
    return 0


def cmd_auth(args: argparse.Namespace) -> int:
    """Capture a credential without it passing through the shell.

    Verifies before saving: a token that cannot read what it needs is worse than
    no token, because the failure would otherwise surface days later as quietly
    missing data.
    """
    from . import auth as auth_mod

    cfg = load_config()
    if args.source == "github":
        from .sources import github as github_mod

        gh_source = github_mod.source_from_config(cfg)
        if gh_source is None:
            print("No signals.github block in config/board.yaml.", file=sys.stderr)
            return 2

        token = auth_mod.prompt_secret("GitHub token")
        if not token:
            print("Cancelled; nothing written.")
            return 1

        print("\nChecking what it unlocks…")
        probed = github_mod.GitHubSource(
            owner=gh_source.owner, repo=gh_source.repo, token=token
        ).probe()
        endpoints = probed["endpoints"]
        for name, entry in endpoints.items():
            mark = "ok  " if entry.get("ok") else "FAIL"
            print(f"  [{mark}] {name:22} {entry.get('status', '')}")

        if not endpoints.get("repo", {}).get("ok"):
            print(
                "\nThat token cannot read the repo. Nothing written.", file=sys.stderr
            )
            return 1
        if not endpoints.get("traffic_views", {}).get("ok"):
            print(
                "\nThe repo reads, but traffic does not — the token is missing the "
                "`public_repo` scope. Traffic is retained for 14 days only, so this "
                "is worth fixing now rather than later.",
                file=sys.stderr,
            )

        outcome = auth_mod.set_env_value("GITHUB_TOKEN", token)
        print(f"\nGITHUB_TOKEN {outcome} in .env (chmod 600, gitignored).")
        print("Next: uv run flow sync --signals")
        return 0

    if args.source == "youtube":
        from .sources import youtube as youtube_mod

        yt_source = youtube_mod.source_from_config(cfg)
        if yt_source is None:
            print("No signals.youtube block in config/board.yaml.", file=sys.stderr)
            return 2

        client_id = auth_mod.prompt_secret("YouTube OAuth client ID")
        if not client_id:
            print("Cancelled; nothing written.")
            return 1
        client_secret = auth_mod.prompt_secret("YouTube OAuth client secret")
        if not client_secret:
            print("Cancelled; nothing written.")
            return 1

        try:
            refresh = auth_mod.oauth_loopback(
                auth_url=youtube_mod.AUTH_URL,
                token_url=youtube_mod.TOKEN_URL,
                client_id=client_id,
                client_secret=client_secret,
                scopes=youtube_mod.SCOPES,
            )
        except RuntimeError as exc:
            print(f"\n{exc}", file=sys.stderr)
            return 1

        auth_mod.set_env_value("YOUTUBE_CLIENT_ID", client_id)
        auth_mod.set_env_value("YOUTUBE_CLIENT_SECRET", client_secret)
        outcome = auth_mod.set_env_value("YOUTUBE_REFRESH_TOKEN", refresh)
        print(f"\nYOUTUBE_REFRESH_TOKEN {outcome} in .env (chmod 600, gitignored).")
        print("Next: uv run flow probe youtube")
        return 0

    print(f"Unknown source: {args.source}", file=sys.stderr)
    return 2


def cmd_probe(args: argparse.Namespace) -> int:
    """Report what a source's credentials actually permit.

    The docs say what is possible; this says what is permitted for this account.
    Run it before building anything on a new source.
    """
    cfg = load_config()
    if args.source == "github":
        from .sources import github as github_mod

        gh_source = github_mod.source_from_config(cfg)
        if gh_source is None:
            print("No signals.github block in config/board.yaml.", file=sys.stderr)
            return 2
        result = gh_source.probe()
        print(
            f"github {result['slug']}  authenticated={result['authenticated']}  "
            f"rate_limit_remaining={result.get('rate_limit_remaining')}\n"
        )
        for name, entry in result["endpoints"].items():
            mark = "ok  " if entry.get("ok") else "FAIL"
            detail = entry.get("sample") if entry.get("ok") else entry.get("message")
            print(f"  [{mark}] {name:22} {entry.get('status', '')}  {detail}")
        if not result["authenticated"]:
            print(
                "\nNo GITHUB_TOKEN in .env — star timestamps and all traffic "
                "endpoints require one (classic PAT, public_repo scope)."
            )
        return 0

    if args.source == "youtube":
        from .sources import youtube as youtube_mod

        yt_source = youtube_mod.source_from_config(cfg)
        if yt_source is None:
            print("No signals.youtube block in config/board.yaml.", file=sys.stderr)
            return 2
        result = yt_source.probe()
        print(f"youtube {result['channel_id']}  configured={result['configured']}\n")
        if not result["configured"]:
            print("Not authorised yet. Run: uv run flow auth youtube")
            return 0
        for name, entry in result["endpoints"].items():
            mark = "ok  " if entry.get("ok") else "FAIL"
            detail = entry.get("sample") if entry.get("ok") else entry.get("message")
            print(f"  [{mark}] {name:18} {entry.get('status', '')}  {detail}")
        return 0

    print(f"Unknown source: {args.source}", file=sys.stderr)
    return 2


def cmd_report(args: argparse.Namespace) -> int:
    """Print the practice, reception and embodiment surfaces."""
    cfg = load_config()
    rows = _grid()

    if args.export:
        print(report_mod.export(rows, Path(args.export)))
        if not args.print:
            return 0

    if args.json:
        print(json.dumps(report_mod.summarise(cfg, rows), indent=2, default=str))
    elif args.rows:
        print(json.dumps(to_dicts(rows), indent=2))
    else:
        print(report_mod.render(report_mod.summarise(cfg, rows), cfg))
        if rows:
            production = loaders.production_by_day()
            print()
            print(
                report_mod.render_diagnostics(
                    diagnostics.run_all(cfg, rows, production)
                )
            )
            latest = loaders.posteriors()
            if not latest.is_empty():
                last_day = latest["day"].max()
                snapshot = latest.filter(pl.col("day") == last_day).to_dicts()
                print()
                print(report_mod.render_posteriors(snapshot))
        # Reception is shown whether or not there is practice history: a
        # cumulative total is a fact and needs no N behind it.
        from .metrics import reception as reception_mod

        signal_rows = loaders.signal_dicts()
        summary = reception_mod.summarise(cfg, signal_rows)
        if summary["counters"] or summary["external_posts"]["total"]:
            print()
            print(reception_mod.render(summary))

        from .metrics import embodiment as embodiment_mod

        body = embodiment_mod.render(embodiment_mod.summarise(cfg, signal_rows))
        if body:
            print()
            print(body)

    integrity = sync_mod.integrity(cfg)
    if not integrity.get("ok"):
        print(
            "\nWARNING — history is incomplete, metrics may understate:",
            file=sys.stderr,
        )
        for problem in integrity.get("problems", []):
            print(f"  {problem}", file=sys.stderr)
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    """What deserves attention, and how deep to go — the conversation opener.

    Deterministic: the same state produces the same brief, so agent behaviour
    cannot drift between sessions. `--json` is the agent's form; prose is yours.
    """
    from datetime import date as _date

    from . import orchestration
    from .metrics import brief as brief_mod

    cfg = load_config()

    knowledge = loaders.knowledge_entities()
    last_reviews: dict[str, _date] = {}
    for entity in knowledge:
        if entity["entity_type"] == "Review" and entity.get("cadence"):
            day = _date.fromisoformat(entity["day"])
            cadence = entity["cadence"]
            if cadence not in last_reviews or day > last_reviews[cadence]:
                last_reviews[cadence] = day

    gates = {
        entity["measure"]
        for entity in knowledge
        if entity["entity_type"] == "GateOpened" and entity.get("measure")
    }

    posterior_frame = loaders.posteriors()
    untrusted: list[str] = []
    if not posterior_frame.is_empty():
        last_day = posterior_frame["day"].max()
        untrusted = posterior_frame.filter(
            (pl.col("day") == last_day) & ~pl.col("trusted")
        )["measure"].to_list()

    inputs = brief_mod.BriefInputs(
        today=_date.today(),
        epoch=cfg.start_date,
        materialised_at=orchestration.latest_materialisations(),
        last_reviews=last_reviews,
        days=loaders.day_adherence().to_dicts(),
        measures=loaders.measures().to_dicts(),
        gates_recorded=gates,
        knowledge=knowledge,
        outcomes_recorded=loaders.outcome_targets(),
        untrusted_today=untrusted,
        archive_signals=len(store.known_signal_ids()),
        graph_signals=loaders.signals_frame().height,
        archive_entity_names=set(store.latest_notes(store.load_notes())),
        working_set_entity_names=raw_assets.working_set_entity_names(),
        last_sync_failed=orchestration.last_run_failures(),
    )
    result = brief_mod.build(inputs)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(brief_mod.render(result))
    return 0


def cmd_refill(args: argparse.Namespace) -> int:
    """Manual fallback for the Butler spawn rule (e.g. a day it failed to fire)."""
    client, cfg = _ctx()
    with client:
        list_id = cfg.require_list_id("future")
        label_id = cfg.require_label()
        # Shuffled for variety, so the order you meet them is not the order they
        # are listed in — explicitly NOT for inference. Nothing in the analysis
        # treats this as randomisation; `pull_rank` records the order you chose
        # to work in, and the card order is a nudge against always starting with
        # Write. Creating each at the top means the last one created lands first,
        # so this reverses on the board — irrelevant, since it is shuffled.
        order = list(cfg.activities)
        random.shuffle(order)
        for activity in order:
            desc = cfg.descriptions.get(activity)
            if args.dry_run:
                print(f"  would create {activity!r} in {cfg.lists['future'].name}")
                if desc:
                    print(f"      desc: {desc}")
            else:
                card = client.create_card(list_id, activity, [label_id], desc=desc)
                print(f"  created {activity!r} -> {card['shortUrl']}")
    return 0


def cmd_drain(args: argparse.Namespace) -> int:
    """Manual fallback for the Butler drain rules.

    The API has no equivalent of Butler's "batch move must be last action"
    constraint, so this archives directly rather than staging through 'drain'.
    The effect on the history is identical: the card ends up closed, having
    never reached 'past'.
    """
    client, cfg = _ctx()
    with client:
        report = bootstrap_mod.safety_check(client, cfg)
        if not report["would_archive"]:
            print("Nothing to drain.")
            return 0
        for card in report["would_archive"]:
            if args.dry_run:
                print(f"  would archive [{card['list']}] {card['name']}")
            else:
                client.archive_card(card["id"])
                print(f"  archived [{card['list']}] {card['name']}")
        if report["would_survive"]:
            print("\nUntouched (no Flow label):")
            for card in report["would_survive"]:
                print(f"  [{card['list']}] {card['name']}")
    return 0


def _fixture_context(days: int) -> tuple[Config, list[FlowRow], dict[str, int]]:
    """Build a config/rows/production triple from fabricated data.

    Everything is written through `store.redirect` into a throwaway directory —
    the real store is append-only and dedupes on id, so fixture rows landing in
    `data/` could only be removed by hand-editing the files.
    """
    import tempfile

    from . import fixtures as fixtures_mod

    with (
        tempfile.TemporaryDirectory(prefix="flow-fixture-") as tmp,
        store.redirect(Path(tmp)),
    ):
        fx = fixtures_mod.synthesize(days=days)
        store.append_actions(fx.actions, store.known_action_ids())
        store.append_cards(fx.cards, store.known_card_fingerprints())
        cfg = fixtures_mod.fixture_config(fx.days[0])
        production = production_by_day(
            cfg, [{"id": p["id"], "created_at": p["created_at"]} for p in fx.forum]
        )
        # Fixture rows are folded straight from the redirected throwaway store:
        # fabricated data must never pass through (or into) the real graph.
        rows = fold_rows(cfg, store.load_cards_latest(), store.load_actions())
        return cfg, rows, production


def cmd_evidence(args: argparse.Namespace) -> int:
    """Emit the review pack. Deterministic work here; judgement in the prompt."""
    from . import evidence as evidence_mod

    if args.fixture:
        cfg, rows, production = _fixture_context(args.fixture)
    else:
        cfg = load_config()
        rows = _grid()
        production = loaders.production_by_day()

    posterior_frame = pl.DataFrame() if args.fixture else loaders.posteriors()
    snapshot: list[dict[str, object]] = []
    contract_history: list[dict[str, object]] = []
    if not posterior_frame.is_empty():
        last_day = posterior_frame["day"].max()
        snapshot = posterior_frame.filter(pl.col("day") == last_day).to_dicts()
        # The persistence rule reads verdict runs across snapshot days, so the
        # contract rows travel with their whole history, not just today.
        contract_history = posterior_frame.filter(
            pl.col("measure").str.starts_with("contract:")
        ).to_dicts()
    pack = evidence_mod.build(
        cfg,
        rows,
        production,
        loaders.signal_dicts(),
        snapshot,
        window=args.window,
        contract_history=contract_history,
    )
    if args.json:
        print(json.dumps(pack, indent=2, default=str))
    else:
        print(evidence_mod.render(pack))

    if not args.fixture:
        integrity = sync_mod.integrity(cfg)
        if not integrity.get("ok"):
            print(
                "\nWARNING — history is incomplete, so these numbers may understate:",
                file=sys.stderr,
            )
            for problem in integrity.get("problems", []):
                print(f"  {problem}", file=sys.stderr)
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    """Render the static dashboard. Publishing the file is a separate step."""
    from . import dashboard as dashboard_mod

    if args.fixture:
        cfg, rows, production = _fixture_context(args.fixture)
    else:
        cfg = load_config()
        rows = _grid()
        production = loaders.production_by_day()

    html = dashboard_mod.render(
        cfg,
        rows,
        production,
        loaders.signal_dicts(),
        fabricated=bool(args.fixture),
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out} ({len(html):,} bytes)")
    print("Publish it with the Artifact tool, or open it locally.")
    return 0


def _date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    """Every subcommand, with its help text.

    Help strings are the documentation people actually read, so they say what a
    command does to the board rather than restating its name.
    """
    parser = argparse.ArgumentParser(
        prog="flow", description="Trello daily W.A.T.E.R. flow automation and history"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="list boards, or describe the selected one")
    p.add_argument(
        "--select", metavar="BOARD_ID", help="record this board as the target"
    )
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("bootstrap", help="ensure lists and the Flow label exist")
    p.add_argument(
        "--apply", action="store_true", help="commit changes (default is dry run)"
    )
    p.add_argument(
        "--adopt-label",
        metavar="ID_OR_COLOUR",
        help=(
            "name an existing *unnamed* label instead of adding another, "
            "e.g. --adopt-label green"
        ),
    )
    p.set_defaults(func=cmd_bootstrap)

    p = sub.add_parser("check", help="show what the drain rule would archive vs spare")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser(
        "brief",
        help="what is stale, due, changed and newly answerable — start here",
    )
    p.add_argument("--json", action="store_true", help="structured, for the agent")
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("sync", help="pull new history into the local store")
    p.add_argument(
        "--backfill", action="store_true", help="also extend history backwards"
    )
    p.add_argument(
        "--since", type=_date, metavar="YYYY-MM-DD", help="backfill target date"
    )
    p.add_argument("--all-actions", action="store_true", help="store every action type")
    p.add_argument(
        "--signals",
        action="store_true",
        help="also pull external production signal (forum posts)",
    )
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("memory", help="working-set tooling for the memory MCP's file")
    memory_sub = p.add_subparsers(dest="memory_command", required=True)
    restore = memory_sub.add_parser(
        "restore",
        help="rebuild .claude/memory.jsonl from the archive's current state",
    )
    restore.add_argument(
        "--force",
        action="store_true",
        help="overwrite a non-empty working set (otherwise refused)",
    )
    restore.set_defaults(func=cmd_memory_restore)

    p = sub.add_parser("auth", help="store a credential securely in .env")
    p.add_argument(
        "source", choices=["github", "youtube"], help="which credential to set"
    )
    p.set_defaults(func=cmd_auth)

    p = sub.add_parser("probe", help="report what a signal source's credentials permit")
    p.add_argument(
        "source", choices=["github", "youtube"], help="which source to probe"
    )
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("report", help="regularity metrics")
    p.add_argument("--json", action="store_true", help="emit the summary as JSON")
    p.add_argument("--rows", action="store_true", help="emit the per-day rows as JSON")
    p.add_argument("--export", metavar="PATH", help="write rows to .csv or .parquet")
    p.add_argument("--print", action="store_true", help="also print after exporting")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("refill", help="manually create today's five W.A.T.E.R. cards")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_refill)

    p = sub.add_parser(
        "drain", help="manually archive unfinished Flow cards (Butler fallback)"
    )
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_drain)

    p = sub.add_parser("evidence", help="emit the review pack for a prepared analysis")
    p.add_argument(
        "--window", type=int, default=28, metavar="DAYS", help="window length"
    )
    p.add_argument("--json", action="store_true", help="emit the pack as JSON")
    p.add_argument(
        "--fixture",
        type=int,
        metavar="DAYS",
        help="build from fabricated data instead of the real store",
    )
    p.set_defaults(func=cmd_evidence)

    p = sub.add_parser(
        "publish", help="render the static dashboard as self-contained HTML"
    )
    p.add_argument("--out", default="reports/dashboard.html", help="output path")
    p.add_argument(
        "--fixture",
        type=int,
        metavar="DAYS",
        help="render from fabricated data instead of the real store",
    )
    p.set_defaults(func=cmd_publish)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch to a subcommand and turn any error into an exit code."""
    args = build_parser().parse_args(argv)
    # argparse hands back a Namespace, so `func` is untyped by construction;
    # every `set_defaults(func=…)` above binds a `(Namespace) -> int`.
    handler: Callable[[argparse.Namespace], int] = args.func
    try:
        return handler(args)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    # The CLI's last line: broad, so anything unhandled leaves as a message and
    # a non-zero exit rather than a traceback. The exit code is the contract —
    # `sync` is scripted against it.
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
