"""Explicit event scope shared by registered analytics tools."""

from datetime import datetime
import polars as pl


def _bound(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Time bounds must be non-empty ISO-8601 strings")
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is not None:
        raise ValueError(
            "Timezone-aware bounds are unsupported: source timezone is unconfirmed"
        )
    return parsed


def filter_events(events, *, start=None, end=None, head_id=None, machine_id=None):
    if isinstance(events, pl.DataFrame):
        out = events.lazy()
    elif isinstance(events, pl.LazyFrame):
        out = events
    else:
        raise TypeError("events must be a Polars DataFrame or LazyFrame")

    lo, hi = _bound(start), _bound(end)
    if lo is not None and hi is not None and lo >= hi:
        raise ValueError("start must be earlier than end")

    heads = None
    if head_id is not None:
        heads = [head_id] if isinstance(head_id, str) else head_id
        if not isinstance(heads, list) or not heads or any(
            not isinstance(head, str) or not head.strip() for head in heads
        ):
            raise ValueError("head_id must be a non-empty string or list of strings")

    if machine_id is not None and (
        not isinstance(machine_id, str) or not machine_id.strip()
    ):
        raise ValueError("machine_id must be a non-empty string")

    schema = out.collect_schema()
    needs_time = lo is not None or hi is not None
    required = {
        column for column, needed in (
            ("ts", needs_time),
            ("head_id", heads is not None),
            ("machine_id", machine_id is not None),
        ) if needed
    }
    missing = required - set(schema.names())
    if missing:
        raise ValueError(f"Missing scope columns: {sorted(missing)}")

    if needs_time:
        dtype = schema["ts"]
        if dtype.base_type() != pl.Datetime or dtype.time_zone is not None:
            raise ValueError("Time filtering requires naive Datetime timestamps")

    applied = []
    if lo is not None:
        out = out.filter(pl.col("ts") >= lo)
        applied.append(f"start>={lo.isoformat()}")
    if hi is not None:
        out = out.filter(pl.col("ts") < hi)
        applied.append(f"end<{hi.isoformat()}")
    if heads is not None:
        out = out.filter(pl.col("head_id").is_in(heads))
        applied.append(f"head_id in {heads!r}")
    if machine_id is not None:
        out = out.filter(pl.col("machine_id") == machine_id)
        applied.append(f"machine_id={machine_id}")
    return out, applied
