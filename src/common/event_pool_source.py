"""Read the requested event scope from an existing partitioned pool."""
from copy import deepcopy
from pathlib import Path
import json

import polars as pl

from . import registry, schema
from ..analytics.event_filters import filter_events
from ..analytics.torque_stats import _apply_status_filter
from ..ingestion.adapter import PERSON_A_COLUMNS, adapt, describe
from ..ingestion.event_pool import scan_event_pool

SUPPORTED_TOOLS = frozenset({"torque_stats", "torque_distribution", "torque_trend",
                             "detect_torque_anomalies", "head_correlation"})


class ScopeTooLarge(ValueError):
    """The requested scope exceeds the configured materialization limit."""


def _read_parameters(calls):
    # Validate one call at a time; _read_plan checks the complete combination
    # and rejects different scopes before opening any event data.
    if not isinstance(calls, (list, tuple)) or len(calls) != 1:
        raise ValueError("Partitioned event loading currently requires exactly one analysis")
    call = calls[0]
    if not isinstance(call, (list, tuple)) or len(call) != 2:
        raise ValueError("Invalid planned tool call")
    name, arguments = call
    if not isinstance(name, str) or name not in SUPPORTED_TOOLS:
        raise ValueError("This event source supports the five verified torque tools only")
    spec = registry.get(name)
    if spec is None:
        raise ValueError(f"Tool is not registered: {name}")
    if not isinstance(arguments, dict) or any(not isinstance(key, str) for key in arguments):
        raise ValueError("Tool arguments must be a dictionary with string keys")
    args = deepcopy(arguments)
    unknown = set(args) - set(spec.params)
    missing = set(spec.required) - set(args)
    if unknown or missing:
        raise ValueError(f"Invalid tool arguments: unsupported={sorted(unknown)}, missing={sorted(missing)}")
    checked, notes, errors = registry.coerce_params(args)
    if errors or notes or checked != args:
        raise ValueError("Read scope must use valid canonical parameters without coercion: "
                         + "; ".join(errors + notes))
    status = args.get("status_filter")
    if status is not None and not (type(status) is int or status == "successful"):
        raise ValueError("status_filter must be an integer or 'successful'")
    scope = {key: args[key] for key in ("start", "end", "head_id", "machine_id") if key in args}
    if name == "head_correlation":
        if args["head_a"] == args["head_b"]:
            raise ValueError("Head comparison requires distinct heads")
        scope["head_id"] = [args["head_a"], args["head_b"]]
    return name, args, scope, status


COMBINED_TOOLS = {
    frozenset({"torque_stats", "torque_distribution"}),
    frozenset({"torque_trend", "detect_torque_anomalies"}),
}


def _read_plan(calls):
    if not isinstance(calls, (list, tuple)) or len(calls) not in (1, 2):
        raise ValueError("Use exactly one analysis or one supported two-tool combination")
    parsed = [_read_parameters([call]) for call in calls]
    if len(parsed) == 2:
        if frozenset(item[0] for item in parsed) not in COMBINED_TOOLS:
            raise ValueError("Use exactly one analysis or a supported statistics/distribution or trend/anomalies pair")
        if parsed[0][2:] != parsed[1][2:]:
            raise ValueError("Combined analyses must use exactly the same head, machine, time and status scope")
    return parsed


def _stat_signature(paths):
    return [(str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in paths]


class EventPoolSource:
    """No whole-pool frame cache; each plan loads only its requested scope.

    All partition schemas are checked. Parquet predicate pushdown controls
    physical reads; no partition is skipped using unverified manifest dates.
    Hash verification is optional because it reads all partition bytes.
    """
    name = "person_a_pool"

    def __init__(self, cfg, *, repo_root):
        self.cfg = deepcopy(cfg)
        self.paths = {}
        for pool, value in cfg.get("data", {}).get("person_a", {}).items():
            path = Path(value)
            self.paths[pool] = (path if path.is_absolute() else Path(repo_root) / path).resolve()
        self.max_events = cfg.get("data", {}).get("max_loaded_events", 1_000_000)
        if type(self.max_events) is not int or self.max_events < 1:
            raise ValueError("data.max_loaded_events must be a positive integer")
        self.verify_hashes = cfg.get("data", {}).get("verify_pool_hashes", False)
        if type(self.verify_hashes) is not bool:
            raise ValueError("data.verify_pool_hashes must be a boolean")

    def list_pools(self):
        return sorted(self.paths)

    def load_for_plan(self, pool, calls):
        parsed = _read_plan(calls)
        name, args, scope, status = parsed[0]
        # Validate the complete filter on an empty schema before opening data.
        filter_events(pl.DataFrame(schema=PERSON_A_COLUMNS).lazy(), **scope)
        if pool not in self.paths:
            raise KeyError(f"Unknown Person A event pool: {pool!r}")
        manifest_path = self.paths[pool]
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        lazy = scan_event_pool(manifest_path, verify_hashes=self.verify_hashes)
        total = manifest["summary"]["observed_events"]
        partitions = manifest["partitions"]
        counts = [entry["observed_events"] for entry in partitions]
        if (type(total) is not int or total < 0 or any(type(n) is not int or n < 0 for n in counts)
                or sum(counts) != total):
            raise ValueError("Manifest event totals are inconsistent")
        paths = [(manifest_path.parent / entry["event_parquet"]).resolve() for entry in partitions]
        signatures = _stat_signature(paths)
        selected, _ = filter_events(lazy, **scope)
        selected = _apply_status_filter(selected, status)
        n_selected = selected.select(pl.len()).collect().item()
        if n_selected > self.max_events:
            raise ScopeTooLarge(
                f"Requested scope contains {n_selected:,} observed events; the configured "
                f"limit is {self.max_events:,}. Specify a narrower head, machine or time scope."
            )
        # The extra limit also bounds the collected result if underlying files
        # change between the count and the read. Such changes are rejected below.
        original = selected.limit(self.max_events + 1).collect()
        if (manifest_path.read_bytes() != manifest_bytes or _stat_signature(paths) != signatures
                or len(original) != n_selected):
            raise ValueError("Event pool changed during the scoped read; no analysis was run")
        events, notes = adapt(original, pool_id=pool, redecode=False)
        schema.validate_events(events)
        if events.is_empty():
            notes.append("No observed events matched the requested scope. Counter discontinuities "
                         "are not reconstructed; total production completeness is not measured.")
        meta = describe(events, pool_id=pool, notes=notes, source=self.name,
                        timezone=self.cfg.get("data", {}).get("timezone"))
        selection = dict(scope)
        if "status_filter" in args:
            selection["status_filter"] = status
        meta.update({
            "n_files": len(partitions), "event_manifest": str(manifest_path),
            "pool_total_events": total, "loaded_events": len(events),
            "selection_parameters": selection, "planned_tool": name if len(parsed) == 1 else None,
            "planned_arguments": args if len(parsed) == 1 else None,
            "planned_calls": [(item[0], item[1]) for item in parsed], "max_loaded_events": self.max_events,
            "materialization": "requested scope only", "verified_partition_hashes": self.verify_hashes,
        })
        return events, meta
