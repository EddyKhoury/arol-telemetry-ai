"""Shared time bucketing.

Audit finding F5: if each side writes its own `.dt.floor()`, "per day" means
one thing in Person A's drift tool and another in Person B's KPI tool, and the
numbers stop agreeing for reasons nobody can find. All bucketing goes through
here.

Timestamps are plant-local and naive (schema.TIMEZONE_POLICY). We never
localise or convert them - a UTC shift would move closures across midnight and
every per-day KPI would stop matching what the operator saw on the line.
"""

from __future__ import annotations

import pandas as pd

# The `bucket` parameter vocabulary, shared by every tool that buckets time.
BUCKETS = ("hour", "shift", "day", "week")

# Plant shifts, as (name, start_hour). Provisional - confirm with AROL.
# A shift boundary that does not match the plant's makes per-shift KPIs
# meaningless, so this is a question for Person A to put to the company.
SHIFTS = (("A", 6), ("B", 14), ("C", 22))


def floor_to(ts: pd.Series, bucket: str) -> pd.Series:
    """Floor a timestamp series to the start of its bucket."""
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {bucket!r}; expected one of {BUCKETS}")
    if bucket == "hour":
        return ts.dt.floor("h")
    if bucket == "day":
        return ts.dt.floor("D")
    if bucket == "week":
        return ts.dt.to_period("W").dt.start_time
    # shift: floor to the most recent shift start
    starts = sorted(h for _, h in SHIFTS)
    hour = ts.dt.hour
    shift_hour = pd.Series(starts[-1], index=ts.index)   # before the first start -> previous day's last shift
    day = ts.dt.floor("D")
    rolls_back = hour < starts[0]
    for h in starts:
        shift_hour = shift_hour.where(hour < h, h)
    out = day + pd.to_timedelta(shift_hour, unit="h")
    return out.where(~rolls_back, out - pd.Timedelta(days=1))


def shift_name(ts: pd.Series) -> pd.Series:
    """Name of the shift each timestamp falls in ("A"/"B"/"C")."""
    starts = sorted(SHIFTS, key=lambda s: s[1])
    hour = ts.dt.hour
    name = pd.Series(starts[-1][0], index=ts.index, dtype="object")
    for label, h in starts:
        name = name.where(hour < h, label)
    return name.astype("string")


def parse_bound(value) -> pd.Timestamp | None:
    """Parse a `start`/`end` parameter. Returns None for None/empty."""
    if value is None or value == "":
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        raise ValueError(f"could not parse timestamp {value!r}; expected ISO-8601")
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_localize(None)
    return ts
