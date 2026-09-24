"""Load Person A event Parquet without changing decoded semantics."""

from pathlib import Path

import polars as pl

from . import schema
from ..ingestion.adapter import PERSON_A_COLUMNS, adapt, describe

REPO_ROOT = Path(__file__).resolve().parents[2]


class PersonASource:
    """One cached event snapshot per pool, for this source instance."""

    name = "person_a"

    def __init__(self, cfg):
        self.cfg = cfg
        self._cache = {}
        configured = cfg.get("data", {}).get("person_a", {})
        self.paths = {}
        for pool, value in configured.items():
            path = Path(value)
            self.paths[pool] = (
                path if path.is_absolute() else REPO_ROOT / path
            ).resolve()

    def list_pools(self):
        # Include missing configured files so errors remain visible.
        return sorted(self.paths)

    def _get(self, pool):
        if pool not in self.paths:
            raise KeyError(f"Unknown Person A event pool: {pool!r}")
        if pool not in self._cache:
            path = self.paths[pool]
            if not path.is_file():
                raise FileNotFoundError(f"Event Parquet not found: {path}")

            original = pl.read_parquet(path)
            if set(original.columns) != set(PERSON_A_COLUMNS):
                raise ValueError(
                    "Expected Person A's eight-column event table, "
                    "not raw telemetry or an already adapted table."
                )
            for column, expected in PERSON_A_COLUMNS.items():
                if original.schema[column] != expected:
                    raise ValueError(
                        f"{column}: expected {expected}, "
                        f"got {original.schema[column]}"
                    )

            events, notes = adapt(original, pool_id=pool, redecode=False)
            schema.validate_events(events)
            self._cache[pool] = events, notes
        return self._cache[pool]

    def load_pool(self, pool):
        return self._get(pool)[0]

    def pool_meta(self, pool):
        events, notes = self._get(pool)
        meta = describe(
            events,
            pool_id=pool,
            notes=notes,
            source=self.name,
            timezone=self.cfg.get("data", {}).get("timezone"),
        )
        meta["n_files"] = 1
        meta["event_file"] = str(self.paths[pool])
        return meta


def get_source(cfg):
    kind = cfg.get("data", {}).get("source")
    if kind == "person_a_pool":
        from .event_pool_source import EventPoolSource
        return EventPoolSource(cfg, repo_root=REPO_ROOT)
    if kind != "person_a":
        raise ValueError(
            "This integration requires data.source='person_a' or 'person_a_pool' "
            "and a data.person_a mapping to event Parquet files or pool manifests."
        )
    return PersonASource(cfg)
