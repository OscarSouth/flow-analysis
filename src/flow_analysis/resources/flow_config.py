"""The board contract, as a resource.

`config/board.yaml` is hand-authored intent and `config/resolved.json` is
machine-written ids; both are read here so an asset never loads them itself and
every asset in a run sees the same contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dagster import ConfigurableResource

from ..config import load_config

if TYPE_CHECKING:
    from ..config import Config


class FlowConfigResource(ConfigurableResource["FlowConfigResource"]):
    """Loads `config/board.yaml` + `config/resolved.json`.

    Not cached: the files are small, and a long-lived Dagster process must pick
    up a `flow bootstrap` that resolved new ids without being restarted.
    """

    def load(self) -> Config:
        """The merged configuration, or a `ConfigError` naming the fix."""
        return load_config()
