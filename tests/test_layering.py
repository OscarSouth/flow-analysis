"""The dependency direction, enforced rather than documented.

`metrics/` is Layer B: pure functions that take data as arguments and return
computed results. It must not import Layer A (fetching) or Layer C (persistence
and interface). A and C may import from B; the arrow never points back.

**This file previously used a blacklist and reported green while Layer B was not
pure at all.** `metrics.diagnostics` reached `store` through `model`, and
`metrics.reception` reached `httpx` through `signals` — neither of which was on
the forbidden list, because the list named the modules someone thought of rather
than the ones that existed. Two checks replace it:

1. an **allowlist** of what `metrics/` may import, so a new module cannot slip
   through by not having been anticipated; and
2. a **transitive** check, because the breach was never a direct import. This is
   the one that would have failed.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

PACKAGE = pathlib.Path(__file__).resolve().parents[1] / "src" / "flow_analysis"
METRICS = PACKAGE / "metrics"

# Everything Layer B is permitted to reach for, besides its own siblings and the
# standard library. All three are leaves: vocabulary, small helpers, and the
# parsed config. None of them fetch or persist.
ALLOWED_SIBLINGS = {"util", "config", "tiers"}

# Nothing in Layer B may cause these to be imported, at any depth.
FORBIDDEN_AT_RUNTIME = ("flow_analysis.store", "flow_analysis.sources", "httpx")


def _metrics_modules() -> list[pathlib.Path]:
    return sorted(p for p in METRICS.glob("*.py") if p.stem != "__init__")


def _package_imports(path: pathlib.Path) -> set[str]:
    """Names this module pulls in from its own package, at any nesting.

    Covers `from ..x import y`, `from .. import x`, and the lazy in-function
    forms of both — which is the shape every violation has actually taken.
    """
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0 and not (node.module or "").startswith("flow_analysis"):
                continue  # third party or stdlib
            if node.module:
                names.add(node.module.split(".")[-1 if node.level else 0])
            else:
                names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("flow_analysis"):
                    names.add(alias.name.split(".")[-1])
    return names


def test_metrics_package_is_populated():
    """Sanity: the checks below are worthless if they scan an empty directory."""
    assert len(_metrics_modules()) >= 5


def test_layer_b_imports_only_what_it_is_allowed_to():
    """An allowlist, so an unanticipated module fails closed rather than open."""
    siblings = {p.stem for p in _metrics_modules()} | {"metrics"}
    permitted = siblings | ALLOWED_SIBLINGS

    offenders: dict[str, set[str]] = {}
    for module in _metrics_modules():
        breaches = _package_imports(module) - permitted
        if breaches:
            offenders[module.name] = breaches
    assert not offenders, f"metrics/ reached outside Layer B: {offenders}"


def test_importing_layer_b_never_loads_layer_a_or_c():
    """The transitive check — the one the blacklist version could not make.

    Runs in a subprocess so nothing another test already imported can mask a
    breach: `sys.modules` is process-wide, and by the time this file runs the
    rest of the suite has loaded the whole package.
    """
    offenders: dict[str, list[str]] = {}
    for module in _metrics_modules():
        dotted = f"flow_analysis.metrics.{module.stem}"
        probe = (
            f"import sys; import {dotted}; "
            f"print(' '.join(m for m in sys.modules if m in {FORBIDDEN_AT_RUNTIME!r} "
            f"or m.startswith('flow_analysis.sources')))"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=PACKAGE.parents[1],
        )
        assert result.returncode == 0, f"{dotted} failed to import: {result.stderr}"
        loaded = result.stdout.split()
        if loaded:
            offenders[dotted] = loaded
    assert not offenders, f"Layer B pulled in Layer A/C at runtime: {offenders}"


def test_the_allowlist_would_catch_a_lazy_breach(tmp_path):
    """A guard that cannot fail is not a guard.

    The lazy, inside-a-function import is the form both real violations took, so
    that is the form the negative control uses.
    """
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def summarise(cfg):\n"
        "    from .. import store\n"
        "    return store.load_signals()\n"
    )
    siblings = {p.stem for p in _metrics_modules()} | {"metrics"} | ALLOWED_SIBLINGS
    assert _package_imports(planted) - siblings == {"store"}


def test_the_allowlist_would_catch_a_top_level_breach(tmp_path):
    """The other form: `model.py` imported `store` in its import block."""
    planted = tmp_path / "planted.py"
    planted.write_text("from ..sources import github\n\ndef f():\n    return github\n")
    siblings = {p.stem for p in _metrics_modules()} | {"metrics"} | ALLOWED_SIBLINGS
    assert _package_imports(planted) - siblings == {"sources"}
