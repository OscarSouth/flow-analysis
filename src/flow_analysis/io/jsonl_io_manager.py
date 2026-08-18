"""The archive, behind a Dagster IO manager.

`data/*.jsonl` is the truth — the only copy of history older than Trello's
1,000-action export cap — so this deliberately owns no writing logic of its own.
It dispatches to the same `store.append_*` functions the CLI has always used, in
order to keep the dedupe semantics (and therefore the bytes on disk) identical.

Each raw asset names its stream in `@asset(metadata={"jsonl_stream": ...})`,
co-located with the asset rather than configured here, so reading the asset tells
you where its rows land.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dagster import ConfigurableIOManager, InputContext, OutputContext

from .. import store
from .streams import STREAMS, RawStream

if TYPE_CHECKING:
    from collections.abc import Mapping


class JsonlIOManager(ConfigurableIOManager):
    """Append rows to the archive, then advance the watermark — in that order.

    Never truncates and never rewrites: every append dedupes on the stream's own
    key, so materialising twice adds nothing and a re-run over an overlapping
    window is free.
    """

    def handle_output(self, context: OutputContext, obj: RawStream) -> None:
        """Persist one stream's rows, and any watermark they justify.

        The watermark is saved *after* the rows land. Reversing that would let a
        failed write leave `state.json` claiming coverage the archive does not
        have — and `sync.integrity()` reads the watermark, so the gap would
        report as OK.
        """
        stream = _stream_name(context.definition_metadata, context)
        added = STREAMS[stream].append(obj.rows)

        if obj.state is not None:
            store.save_state(obj.state)

        context.add_output_metadata(
            {
                "stream": stream,
                "rows_fetched": len(obj.rows),
                "rows_appended": added,
                "path": str(STREAMS[stream].path()),
            }
        )

    def load_input(self, context: InputContext) -> list[dict[str, Any]]:
        """Read a stream back out of the archive.

        Reads the whole stream rather than only what the upstream run fetched:
        downstream layers model history, and an incremental sync legitimately
        adds nothing.
        """
        upstream = context.upstream_output
        if upstream is None:  # pragma: no cover - Dagster always sets this
            raise ValueError("load_input called without an upstream output")
        stream = _stream_name(upstream.definition_metadata, context)
        return STREAMS[stream].load()


def _stream_name(
    metadata: Mapping[str, Any] | None, context: InputContext | OutputContext
) -> str:
    """Which archive file this asset belongs to.

    Declared per asset in metadata. Failing loudly here beats defaulting to a
    file: a typo would otherwise write one stream's rows into another's.
    """
    name = (metadata or {}).get("jsonl_stream")
    if name not in STREAMS:
        raise ValueError(
            f"{context!r}: metadata['jsonl_stream'] must be one of "
            f"{sorted(STREAMS)}, got {name!r}"
        )
    return str(name)
