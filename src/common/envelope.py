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
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import polars as pl


def jsonable(value: Any) -> Any:
    """Cast Polars / numeric scalars to plain Python so json.dumps cannot fail.

    The contract calls this out explicitly: engine-native types serialise
    silently wrong or not at all, and the agent chokes on them at report time.
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, (float, Decimal)):
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, pl.Series):
        return [jsonable(v) for v in value.to_list()]
    if isinstance(value, pl.DataFrame):
        return [jsonable(row) for row in value.to_dicts()]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in value]
    # numpy scalars and anything else exposing .item()
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return jsonable(item())
        except Exception:
            pass
    return value


def data_window(events: pl.DataFrame | None) -> dict:
    """ts_min / ts_max of the rows a result was computed from."""
    if events is None or events.height == 0 or "ts" not in events.columns:
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
