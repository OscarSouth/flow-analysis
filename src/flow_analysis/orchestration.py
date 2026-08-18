"""Running the raw assets from the CLI, in this process.

`flow sync` materialises assets rather than shelling out to `dagster asset
materialize`, for two reasons: the CLI keeps its own summary and its non-zero
exit on incomplete history, which scripts depend on; and the run is recorded in
the Dagster instance under `DAGSTER_HOME`, so it shows up in `dagster dev` and to
the MCP server alongside runs launched from the UI.

Layer C. Assets and the IO manager do the work; this only decides which of them
to run and reads back what happened.
"""

from __future__ import annotations

import contextlib
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from dagster import DagsterInstance, RunConfig, materialize

from .assets import ALL_ASSETS, GRAPH_ASSETS, RAW_ASSETS
from .assets.raw import ActionWalkConfig
from .config import REPO_ROOT, read_env
from .definitions import defs

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import date


# The board is the practice's own record; the rest is what the world did with it.
BOARD_ASSETS = ("raw_trello_actions", "raw_trello_cards")

DEFAULT_DAGSTER_HOME = REPO_ROOT / ".dagster_home"


@contextlib.contextmanager
def _instance() -> Iterator[DagsterInstance]:
    """The instance runs are recorded in, or an ephemeral one.

    `DAGSTER_HOME` lives in `.env` — the Justfile and the Dagster CLI load it,
    a bare `uv run flow sync` does not — so it is read from there too. Falling
    back to ephemeral keeps sync working on a machine that has never run
    `dagster dev`; the archive is the point, and the run history is a
    convenience.
    """
    home = os.environ.get("DAGSTER_HOME") or read_env().get("DAGSTER_HOME")
    if not home and DEFAULT_DAGSTER_HOME.is_dir():
        home = str(DEFAULT_DAGSTER_HOME)
    if not home:
        with DagsterInstance.ephemeral() as instance:
            yield instance
        return
    os.environ["DAGSTER_HOME"] = home
    with DagsterInstance.get() as instance:
        yield instance


def _select(with_signals: bool) -> list[str]:
    """Which assets a given `flow sync` invocation covers.

    The graph layers are always included: Docker is a standing requirement by
    decision (2026-08-18), and analysis reads the graph and only the graph — a
    sync that left the graph behind the archive would make every surface stale
    the moment it finished.
    """
    if with_signals:
        raw = [a.key.to_user_string() for a in RAW_ASSETS]
    else:
        raw = list(BOARD_ASSETS)
    return raw + [a.key.to_user_string() for a in GRAPH_ASSETS]


def materialise_raw(
    *,
    with_signals: bool = False,
    backfill_from: date | None = None,
    all_actions: bool = False,
) -> dict[str, dict[str, Any]]:
    """Run the raw assets and report what each one wrote.

    Returns per-asset metadata — rows fetched, rows appended — read back from the
    materialisations rather than counted here, so the numbers reported are the
    ones the IO manager actually produced.

    A source failing does not stop the others: GitHub traffic is retained for 14
    days only, so losing an unrelated stream to one lapsed credential would cost
    data that cannot be re-fetched.
    """
    selected = _select(with_signals)
    with _instance() as instance:
        result = materialize(
            ALL_ASSETS,
            selection=selected,
            resources=defs.resources,
            instance=instance,
            run_config=RunConfig(
                ops={
                    "raw_trello_actions": ActionWalkConfig(
                        backfill_from=(
                            backfill_from.isoformat() if backfill_from else None
                        ),
                        all_actions=all_actions,
                    )
                }
            ),
            raise_on_error=False,
        )

    written: dict[str, dict[str, Any]] = {}
    for name in selected:
        written[name] = {"ok": False, "rows_fetched": 0, "rows_appended": 0}
    for event in result.get_asset_materialization_events():
        materialisation = event.step_materialization_data.materialization
        name = materialisation.asset_key.to_user_string()
        values = {k: v.value for k, v in materialisation.metadata.items()}
        written[name] = {
            "ok": True,
            # Raw assets report fetched/appended; graph assets report
            # rows_written. One summary shape covers both.
            "rows_fetched": values.get("rows_fetched", values.get("rows_written", 0)),
            "rows_appended": values.get("rows_appended", values.get("rows_written", 0)),
            "stream": values.get("stream"),
        }
    return written


def latest_materialisations() -> dict[str, datetime]:
    """When each asset last landed, from the Dagster instance.

    Freshness comes from the orchestrator's own records rather than a second
    bookkeeping system — Dagster already knows, and reimplementing staleness
    would eventually disagree with it.
    """
    from .assets import ALL_ASSETS

    out: dict[str, datetime] = {}
    with _instance() as instance:
        for asset_def in ALL_ASSETS:
            key = asset_def.key
            record = instance.get_latest_materialization_event(key)
            if record is not None:
                out[key.to_user_string()] = datetime.fromtimestamp(
                    record.timestamp, tz=UTC
                )
    return out


def last_run_failures() -> list[str]:
    """Step failures from the most recent run, for the brief's health check.

    Reads the orchestrator's own event log rather than any bookkeeping of ours:
    Dagster already knows what failed.
    """
    with _instance() as instance:
        runs = instance.get_runs(limit=1)
        if not runs:
            return []
        return sorted(
            {
                event.step_key
                for event in instance.all_logs(runs[0].run_id)
                if event.dagster_event is not None
                and event.dagster_event.event_type_value == "STEP_FAILURE"
                and event.step_key is not None
            }
        )


def render_raw(written: dict[str, dict[str, Any]]) -> str:
    """One line per asset: what it fetched, what was new, or that it failed."""
    lines = []
    for name in sorted(written):
        entry = written[name]
        if not entry["ok"]:
            lines.append(f"  {name}: FAILED — see the run log above")
            continue
        lines.append(
            f"  {name}: {entry['rows_appended']} new of {entry['rows_fetched']} fetched"
        )
    return "\n".join(lines)
