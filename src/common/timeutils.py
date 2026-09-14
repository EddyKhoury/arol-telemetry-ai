"""Shared time bucketing.

Audit finding F5: if each side writes its own flooring, "per day" means one
thing in Person A's drift tool and another in Person B's KPI tool, and the
numbers stop agreeing for reasons nobody can find. All bucketing goes through
here.

Timestamps are plant-local and naive (schema.TIMEZONE_POLICY). We never
localise or convert them here - a UTC shift would move closures across
midnight and every per-day KPI would stop matching what the operator saw on
the line. Conversion, if the plant turns out not to be UTC, belongs in the
loader, once.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl

# The `bucket` parameter vocabulary, shared by every tool that buckets time.
BUCKETS = ("hour", "shift", "day", "week")

# Plant shifts, as (name, start_hour). Provisional - confirm with AROL.
# A shift boundary that does not match the plant's makes per-shift KPIs
# meaningless, so this is a question for Person A to put to the company.
SHIFTS = (("A", 6), ("B", 14), ("C", 22))

# Polars truncate intervals for the simple buckets.
_TRUNCATE = {"hour": "1h", "day": "1d", "week": "1w"}


def floor_to(ts: pl.Series | pl.Expr, bucket: str):
    """Floor a timestamp series or expression to the start of its bucket.

    Works on both a Series and an Expr, so callers can use it inside a
    `select`/`with_columns` or directly on a column.
    """
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {bucket!r}; expected one of {BUCKETS}")

    if bucket in _TRUNCATE:
        return ts.dt.truncate(_TRUNCATE[bucket])

    # shift: floor to the most recent shift start, rolling back over midnight
    # for timestamps before the first start of the day.
    starts = sorted(h for _, h in SHIFTS)
    day = ts.dt.truncate("1d")
    hour = ts.dt.hour()

    # Walk the starts in order; each one overrides for hours at or past it.
    shift_hour = pl.lit(starts[-1], dtype=pl.Int32)
    for h in starts:
        shift_hour = pl.when(hour >= h).then(pl.lit(h, dtype=pl.Int32)).otherwise(shift_hour)

    floored = day + pl.duration(hours=shift_hour)
    return (
        pl.when(hour < starts[0])
        .then(floored - pl.duration(days=1))
        .otherwise(floored)
    )


def shift_name(ts: pl.Series | pl.Expr):
    """Name of the shift each timestamp falls in ("A"/"B"/"C")."""
    starts = sorted(SHIFTS, key=lambda s: s[1])
    hour = ts.dt.hour()
    name = pl.lit(starts[-1][0], dtype=pl.String)
    for label, h in starts:
        name = pl.when(hour >= h).then(pl.lit(label, dtype=pl.String)).otherwise(name)
    return name


def parse_bound(value) -> datetime | None:
    """Parse a `start`/`end` parameter. Returns None for None/empty.

    Accepts an ISO-8601 string, a date, or a datetime. A timezone-aware value
    has its offset dropped rather than converted, because the event table is
    plant-local naive and silently shifting a user's window would be worse
    than ignoring an offset they probably did not mean to supply.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)

    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = (
                pl.Series([text])
                .str.to_datetime(strict=True, time_unit="us")
                .item()
            )
        except Exception as exc:
            raise ValueError(
                f"could not parse timestamp {value!r}; expected ISO-8601"
            ) from exc
    return parsed.replace(tzinfo=None)
