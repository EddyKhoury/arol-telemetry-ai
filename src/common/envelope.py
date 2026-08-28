"""The tool return envelope.

Every analysis tool - Person A's statistical ones and Person B's KPI ones -
returns this shape and nothing else. The orchestrator can then consume any
tool identically, and the trace log comes for free.

Amended from contract.pdf section 2 per audit findings F14 and F15:
  F14 - all four top-level keys are ALWAYS present, so the dispatcher never
        has to branch on `"error" in result`.
  F15 - meta carries enough to reconstruct the call: tool name, echoed params,
        elapsed_ms, the data window actually covered, and units.
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
import pandas as pd


def jsonable(value: Any) -> Any:
    """Cast numpy/pandas scalars to plain Python so json.dumps cannot fail.

    The contract calls this out explicitly: numpy types serialise silently
    wrong or not at all, and the agent chokes on them at report time.
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(value, int):
        return int(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.total_seconds()
    if value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, np.ndarray, pd.Index)):
        return [jsonable(v) for v in value]
    if isinstance(value, pd.Series):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, pd.DataFrame):
        return [jsonable(row) for row in value.to_dict(orient="records")]
    return value


def data_window(events) -> dict:
    """ts_min / ts_max of the rows a result was computed from."""
    if events is None or len(events) == 0 or "ts" not in events.columns:
        return {"ts_min": None, "ts_max": None}
    return {
        "ts_min": jsonable(events["ts"].min()),
        "ts_max": jsonable(events["ts"].max()),
    }


def envelope(
    result: Any,
    *,
    n: int,
    tool: str = "",
    params: dict | None = None,
    filters_applied: list[str] | None = None,
    notes: str = "",
    units: dict | None = None,
    window: dict | None = None,
    elapsed_ms: float | None = None,
    error: str | None = None,
) -> dict:
    """Build the canonical envelope. Always four keys, always JSON-safe.

    `n` is mandatory and is what the report's confidence/limits section is
    computed from - never write prose about confidence that `n` does not support.
    """
    return {
        "ok": error is None,
        "result": jsonable(result),
        "error": error,
        "meta": {
            "tool": tool,
            "n": int(n),
            "params": jsonable(params or {}),
            "filters_applied": list(filters_applied or []),
            "data_window": window if window is not None else {"ts_min": None, "ts_max": None},
            "units": units or {},
            "elapsed_ms": round(float(elapsed_ms), 2) if elapsed_ms is not None else None,
            "notes": notes,
        },
    }


def failure(error: str, *, tool: str = "", params: dict | None = None,
            n: int = 0, notes: str = "") -> dict:
    """A tool that cannot produce a result RETURNS this - it does not raise.

    An exception halfway through a plan kills the whole report; a failure
    envelope lets the orchestrator degrade and still deliver something.
    """
    return envelope(None, n=n, tool=tool, params=params, notes=notes, error=error)


class Timer:
    """with Timer() as t: ...   ->   t.ms"""

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = (time.perf_counter() - self._t0) * 1000.0
        return False
