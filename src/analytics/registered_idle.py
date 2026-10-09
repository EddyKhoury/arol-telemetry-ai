"""Conservative, all-head No Load intervals from raw status observations."""

from datetime import timedelta

import polars as pl

from ..common.envelope import data_window, envelope
from ..common.registry import tool
from ..common.runtime import current_config
from .event_filters import _bound


def find_idle_periods(readings: pl.DataFrame, threshold_seconds: int) -> dict:
    """Require one consecutive, all-head No Load reading per second.

    An absent, duplicated or irregular timestamp breaks a run. A reading
    contributes one observed one-second slot, not proof of physical downtime.
    """
    if type(threshold_seconds) is not int or threshold_seconds < 1:
        raise ValueError("analytics.idle_window_seconds must be a positive integer")
    if readings.schema.get("ts") != pl.Datetime("us") or readings.schema.get("all_heads_no_load") != pl.Boolean:
        raise ValueError("Idle analysis requires validated raw timestamp and all-head status columns")
    previous = None
    run_start = None
    run_end = None
    run_rows = 0
    periods = []
    gaps = duplicates = 0

    def close_run():
        if run_rows >= threshold_seconds:
            periods.append({"start": run_start.isoformat(),
                            "end": (run_end + timedelta(seconds=1)).isoformat(),
                            "duration_seconds": run_rows, "n_readings": run_rows})

    for ts, all_no_load in readings.select("ts", "all_heads_no_load").iter_rows():
        step = None if previous is None else (ts - previous).total_seconds()
        if step is not None and step != 1:
            duplicates += step == 0
            gaps += step > 1
        contiguous = step == 1
        if run_rows and (not all_no_load or not contiguous):
            close_run()
            run_start = run_end = None
            run_rows = 0
        if all_no_load:
            if not run_rows:
                run_start = ts
            run_end = ts
            run_rows += 1
        previous = ts
    if run_rows:
        close_run()
    return {"idle_periods": periods, "n_periods": len(periods),
            "total_idle_seconds": sum(p["duration_seconds"] for p in periods),
            "threshold_seconds": threshold_seconds, "n_raw_readings": len(readings),
            "n_all_heads_no_load": int(readings["all_heads_no_load"].sum()),
            "timestamp_gaps": gaps, "duplicate_timestamps": duplicates}


@tool(name="machine_idle", agent="analytics", owner="integration",
      description="Find sustained all-head No Load intervals in raw one-second telemetry. Requires a machine and bounded time window; gaps break continuity.",
      params=["machine_id", "start", "end"], required=["machine_id", "start", "end"])
def machine_idle(readings, *, machine_id, start, end):
    if not isinstance(machine_id, str) or not machine_id.strip():
        raise ValueError("One explicit machine is required")
    lo, hi = _bound(start), _bound(end)
    if lo is None or hi is None or lo >= hi:
        raise ValueError("Idle analysis needs a bounded start before end")
    if not isinstance(readings, pl.DataFrame) or readings.schema.get("machine_id") != pl.String:
        raise ValueError("Idle analysis requires raw-status readings")
    if readings.height and (readings["machine_id"] != machine_id).any():
        raise ValueError("Readings differ from requested machine")
    selected = readings.filter((pl.col("ts") >= lo) & (pl.col("ts") < hi))
    result = find_idle_periods(selected, current_config().get("analytics", {}).get("idle_window_seconds", 300))
    return envelope(result, n=result["n_raw_readings"], tool="machine_idle",
                    filters_applied=[f"machine_id={machine_id}", f"start>={start}", f"end<{end}",
                                     "every head status decodes as No Load; uninterrupted 1s samples"],
                    window=data_window(selected), units={"duration_seconds": "observed s"},
                    notes=("Intervals are continuous observed one-second slots with No Load on every head. "
                           "Missing or repeated timestamps break runs. Status 2 or 3 is No Load; "
                           "unrecognized codes are not. This is a status-based candidate, "
                           "not proof of zero production, machine downtime, or a physical cause."))
