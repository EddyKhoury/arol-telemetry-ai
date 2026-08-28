"""Where the event table comes from.

Audit finding F1 made concrete: the orchestrator never imports a loader
directly, it asks for a source. `data.source` in config.yaml picks which one.
That single key is the Phase-5 swap from synthetic to real telemetry - the
promise the whole placeholder handshake rests on.
"""

from __future__ import annotations

from pathlib import Path

from . import schema


class DataSource:
    """Interface both sources satisfy."""

    name = "abstract"

    def list_pools(self) -> list[str]:
        raise NotImplementedError

    def load_pool(self, pool: str):
        raise NotImplementedError

    def pool_meta(self, pool: str) -> dict:
        raise NotImplementedError


class SyntheticSource(DataSource):
    """Generated events with known injected faults. Person B builds on this."""

    name = "synthetic"

    def __init__(self, cfg):
        self.cfg = cfg
        self._cache: dict[str, tuple] = {}

    def list_pools(self) -> list[str]:
        return ["synthetic"]

    def _get(self, pool: str):
        if pool not in self._cache:
            from ..testing import synth
            self._cache[pool] = synth.generate_from_config(self.cfg, pool_id=pool)
        return self._cache[pool]

    def load_pool(self, pool: str = "synthetic"):
        return self._get(pool)[0]

    def ground_truth(self, pool: str = "synthetic") -> dict:
        """Only the synthetic source has this. The evaluation harness uses it."""
        return self._get(pool)[1]

    def pool_meta(self, pool: str = "synthetic") -> dict:
        events, gt = self._get(pool)
        return {
            "pool": pool,
            "source": "synthetic",
            "n_files": 0,
            "n_events": int(len(events)),
            "ts_min": events["ts"].min().isoformat(),
            "ts_max": events["ts"].max().isoformat(),
            "machines": sorted(events["machine_id"].dropna().unique().tolist()),
            "heads": sorted(events["head_id"].dropna().unique().tolist()),
            "timezone": self.cfg["data"].get("timezone"),
            "rows_read": int(len(events)),
            "rows_after_cleaning": int(len(events)),
            "duplicates_removed": 0,
            "schema_version": schema.SCHEMA_VERSION,
            "warnings": ["SYNTHETIC DATA - not real telemetry. "
                         f"{len(gt['faults'])} faults injected on purpose."],
        }


class RealSource(DataSource):
    """Person A's WP1 pipeline. Stubbed until it lands."""

    name = "real"

    def __init__(self, cfg):
        self.cfg = cfg

    def list_pools(self) -> list[str]:
        from ..ingestion import api
        return api.list_pools(self.cfg)

    def load_pool(self, pool: str):
        from ..ingestion import api
        events = api.load_pool(self.cfg, pool,
                               use_cache=self.cfg["data"].get("use_cache", True))
        # The one assertion that makes the swap safe.
        schema.validate_events(events)
        return events

    def pool_meta(self, pool: str) -> dict:
        from ..ingestion import api
        return api.pool_meta(self.cfg, pool)


def get_source(cfg) -> DataSource:
    kind = (cfg.get("data", {}).get("source") or "synthetic").lower()
    if kind == "synthetic":
        return SyntheticSource(cfg)
    if kind == "real":
        return RealSource(cfg)
    raise ValueError(f"data.source must be 'synthetic' or 'real', got {kind!r}")
