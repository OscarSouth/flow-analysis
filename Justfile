# flow-analysis — task runner
# Install just: brew install just
#
# Usage: just <recipe>   ·   List all: just --list
#
# Ports are offset from ~/dataplatform-template and ~/portfolio-analysis (which
# share 7475/7688/3000 and so cannot run at the same time as each other). This
# project uses 7476/7689/3001 and can run alongside either of them.

set dotenv-load

# ──────────────────────────────────────────────
# Platform lifecycle
# ──────────────────────────────────────────────

# First-time setup: install deps, start Neo4j, apply schema
setup:
    uv sync --all-groups
    @just up
    @echo ""
    @echo "Setup complete. Next steps:"
    @echo "  just dagster   # Pipeline UI (localhost:3001)"
    @echo "  just notebook  # Notebook editor (localhost:2719)"

# Start platform infrastructure (Neo4j + schema)
up:
    docker compose up -d neo4j
    @just _wait-neo4j
    @just schema
    @echo "Neo4j ready — Browser: http://localhost:7476 | Bolt: bolt://localhost:7689"

# Apply graph constraints and indexes (idempotent; `just up` runs it for you)
schema:
    uv run python -m flow_analysis.graph

# Stop all platform infrastructure
down:
    docker compose down

# ──────────────────────────────────────────────
# The daily loop
# ──────────────────────────────────────────────

# Pull every source into the append-only archive
sync:
    uv run flow sync --signals

# Practice, reception and embodiment surfaces
report:
    uv run flow report

# The review pack for a prepared analysis
evidence window="28":
    uv run flow evidence --window {{window}}

# Render the static dashboard
publish:
    uv run flow publish

# ──────────────────────────────────────────────
# Development servers (run in separate terminals)
# ──────────────────────────────────────────────

# Start Dagster dev server (pipeline UI at localhost:3001)
dagster:
    DAGSTER_HOME="{{justfile_directory()}}/.dagster_home" uv run dagster dev -p 3001

# Start Marimo notebook editor (localhost:2719)
#
# `--mcp` is a hidden flag: without it marimo serves no MCP endpoint and the
# `marimo` entry in .mcp.json fails with "Missing server token". Skew protection
# stays on — it does not block the MCP endpoint, only stale browser clients.
notebook:
    uv run marimo edit notebooks/ -p 2719 --mcp

# ──────────────────────────────────────────────
# Quality & verification
# ──────────────────────────────────────────────

# Run full verification suite (typecheck + lint + test)
check: typecheck lint test
    @echo "All checks passed."

# Run test suite (pass extra args like: just test -k "epoch")
test *args:
    uv run pytest {{args}}

# Run the integration suite (needs `just up` — Neo4j on 7689)
test-integration *args:
    uv run pytest -m integration {{args}}

# Install the CmdStan toolchain (one-off; the inference layer samples with it)
install-cmdstan:
    uv run python -m cmdstanpy.install_cmdstan --cores 4

# Run type checker
typecheck:
    uv run mypy src/

# Run linter and format checker
lint:
    uv run ruff check . && uv run ruff format --check .

# Auto-fix lint and format issues
fix:
    uv run ruff check --fix . && uv run ruff format .

# Validate Dagster definitions
validate:
    DAGSTER_HOME="{{justfile_directory()}}/.dagster_home" uv run dagster definitions validate

# ──────────────────────────────────────────────
# Board operations (Butler fallbacks — see docs/02-butler-rules.md)
# ──────────────────────────────────────────────

# Show what the drain rule would archive vs spare
board-check:
    uv run flow check

# ──────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────

_wait-neo4j:
    #!/usr/bin/env bash
    for i in {1..30}; do
        curl -s http://localhost:7476 > /dev/null 2>&1 && exit 0
        sleep 1
    done
    echo "Neo4j failed to start after 30s" && exit 1
