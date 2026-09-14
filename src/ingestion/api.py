"""Ingestion interface - PERSON A IMPLEMENTS THIS.

Audit finding F1: contract.pdf specifies the shape of the event table but never
the function that produces it. Every tool takes `events: pl.DataFrame` as its
first argument, so without this interface Person B cannot write a line of agent
code. This module is the agreed signature, stubbed, so that B builds against it
today and A drops the real implementation in behind it.

Contract: whatever load_pool returns must pass common.schema.validate_events.
"""

from __future__ import annotations

from ..common.schema import EVENT_COLUMNS, SCHEMA_VERSION  # noqa: F401  (re-export)


class NotImplementedByPersonA(NotImplementedError):
    """Raised by the stubs. Swap data.source to 'synthetic' until A lands WP1."""


def list_pools(cfg) -> list[str]:
    """Names of the pools defined in config, that actually have files."""
    return [name for name, files in (cfg["data"]["pools"] or {}).items() if files]


def load_pool(cfg, pool: str, *, use_cache: bool = True):
    """Load one pool as a single stitched event table.

    Files are read in timestamp order and treated as ONE continuous counter
    history, so a closure straddling a day boundary is still detected.

    Must return a Polars DataFrame conforming to common.schema.EVENT_COLUMNS.
    """
    raise NotImplementedByPersonA(
        "src/ingestion/api.load_pool is Person A's WP1 deliverable. "
        "Until it lands, set data.source: synthetic in config.yaml."
    )


def pool_meta(cfg, pool: str) -> dict:
    """Describe a pool without loading it.

    The report's 'data used' section and the orchestrator's ambiguity handling
    both read this, so it is part of the interface, not a convenience.

    Expected keys:
        pool, n_files, n_events, ts_min, ts_max, machines, heads,
        timezone, rows_read, rows_after_cleaning, duplicates_removed, warnings
    """
    raise NotImplementedByPersonA(
        "src/ingestion/api.pool_meta is Person A's WP1 deliverable."
    )
