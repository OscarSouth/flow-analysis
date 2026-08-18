"""External signal sources, one module per origin.

Each exposes `probe()` — a read-only capability check that reports what the
account actually returns — and one or more generators yielding store rows. Every
row declares its `tier`; see `tiers.py` for why that matters.
"""
