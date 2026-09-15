"""Event-table schema and status decoding.

Single source of truth for the A/B integration contract. Both the real loader
(Person A, src/ingestion) and the synthetic generator (Person B, src/testing)
must produce frames that pass `validate_events`.

Derived from Person A's contract.pdf, with the amendments agreed in the audit:
  - pool_id, count_delta, head_index added   (contract OPEN item 2)
  - timestamps are plant-local and naive     (audit F5)
  - status decoded as a bitfield, not an enum (audit F11)
  - count_delta > 1 is representable         (audit F6)

ENGINE: Polars. Person A's pipeline is Polars end to end, and a pandas event
table costs ~178 MB per machine-day (~5 GB for a 28-day pool), so the two
halves share one engine rather than converting at the boundary.
"""

from __future__ import annotations

import polars as pl

# Bump on any breaking change to EVENT_COLUMNS. Loader and generator both
# stamp it; the conformance test asserts they agree.
SCHEMA_VERSION = "1.0"

# Column -> Polars dtype. Order is the canonical column order.
# Datetime("us") matches Person A's EVENT_SCHEMA; every timestamp in the real
# telemetry is a whole second, so the unit costs no precision either way.
EVENT_COLUMNS: dict[str, pl.DataType] = {
    "ts":            pl.Datetime("us"),  # plant-local, naive. See TIMEZONE_POLICY.
    "pool_id":       pl.String,          # which pool this event came from
    "machine_id":    pl.String,          # parsed from the filename (MCC777...)
    "head_id":       pl.String,          # "H01".."H36"
    "head_index":    pl.Int16,           # 1..36, for correct numeric sort order
    "torque":        pl.Float64,         # H## AppTorque on the increment row, Nm
    "status":        pl.Int16,           # H## Status on the increment row, raw code
    "error_class":   pl.String,          # decoded from status
    "reject_signal": pl.Boolean,         # status bit 0
    "cap_present":   pl.Boolean,         # True / False / null - null = not knowable
    "count_delta":   pl.Int32,           # counter increment that produced this event
    "inferred":      pl.Boolean,         # True when count_delta > 1 (dropped sample)
}

TORQUE_UNIT = "Nm"

# Timestamps are kept in plant-local wall-clock time with no tzinfo, so that
# "per day" and "per shift" match what an operator on the line would say.
# The originating timezone is reported in pool_meta()["timezone"], not baked
# into the values. Never attach a time zone to `ts`.
#
# OPEN: the real files are stamped on a 16:00 boundary and the activity
# pattern fits UTC+8, so the loader will have to CONVERT rather than pass
# through. Confirm the plant's timezone with Person A before relying on any
# per-day or per-shift figure.
TIMEZONE_POLICY = "plant-local naive"


# --- status decoding -------------------------------------------------------
#
# Bit 0 is the reject flag; the high bits are the error category. Confirmed
# against AROL's own code table (via Person A): every category appears as a
# pair n / n+1 with identical error_class and reject_signal false / true --
# 2/3 No Load, 4/5 No Closure, 8/9 No InTorque, 16/17 No CapTurns,
# 32/33 Following Error, 64/65 Bad Closure. So 65 == 64 | 1.
#
# Only 0, 2 and 65 occur in the real pools, but all seven categories are named
# in AROL's own table (via Person A), so a grading dataset containing any of
# them decodes to its real meaning rather than "Unknown".

REJECT_BIT = 0b1

CATEGORY_NAMES: dict[int, str] = {
    0:  "Closure OK",
    2:  "No Load",
    4:  "No Closure",
    8:  "No InTorque",
    16: "No CapTurns",
    32: "Following Error",
    64: "Bad Closure",
}

# Whether a cap was physically in the head is a SEPARATE question from what
# went wrong, and we only know the answer for three categories:
#
#   Closure OK   a cap was applied successfully        -> present
#   Bad Closure  a cap was applied badly               -> present
#   No Load      the head cycled with nothing in it    -> absent
#
# For No Closure / No InTorque / No CapTurns / Following Error the source does
# not say. Person A's contract sets cap_present to null there rather than
# guessing, and he is right: guessing True would silently put those events into
# the success-rate DENOMINATOR, quietly changing every rate on a dataset that
# contains them. Null forces an honest decision downstream instead.
CAP_PRESENT_CATEGORIES: frozenset[int] = frozenset({0, 64})
NO_CAP_CATEGORIES: frozenset[int] = frozenset({2})

# Codes we have actually seen in the data and can vouch for.
CONFIRMED_STATUS_CODES: frozenset[int] = frozenset({0, 2, 65})


def _category(expr: pl.Expr) -> pl.Expr:
    """Clear bit 0 to get the error category. Avoids bitwise-and on a signed
    dtype, which is easy to get subtly wrong."""
    return expr - (expr % 2)


def decode_status(status: int) -> dict:
    """Decode one raw status code into its contract fields.

    Never raises on an unseen code: an unknown category yields
    error_class "Unknown (<code>)" and confirmed=False, so a grading dataset
    with new codes degrades instead of crashing.
    """
    status = int(status)
    category = status - (status % 2)
    reject = bool(status % 2)
    name = CATEGORY_NAMES.get(category)
    if category in CAP_PRESENT_CATEGORIES:
        cap = True
    elif category in NO_CAP_CATEGORIES:
        cap = False
    else:
        cap = None          # not guessed - see CAP_PRESENT_CATEGORIES above
    return {
        "error_class": name if name is not None else f"Unknown ({status})",
        "reject_signal": reject,
        "cap_present": cap,
        "confirmed": status in CONFIRMED_STATUS_CODES,
    }


def decode_status_series(status) -> pl.DataFrame:
    """Vectorised decode_status.

    Accepts a Polars Series or any sequence of ints; returns a DataFrame with
    columns error_class / reject_signal / cap_present / confirmed, in the same
    row order as the input.
    """
    series = status if isinstance(status, pl.Series) else pl.Series("status", list(status))
    frame = pl.DataFrame({"status": series.cast(pl.Int16)})
    category = _category(pl.col("status"))
    return frame.select(
        pl.coalesce(
            category.cast(pl.Int64).replace_strict(
                CATEGORY_NAMES, default=None, return_dtype=pl.String
            ),
            pl.format("Unknown ({})", pl.col("status")),
        ).alias("error_class"),
        ((pl.col("status") % 2) != 0).alias("reject_signal"),
        pl.when(category.is_in(list(CAP_PRESENT_CATEGORIES))).then(True)
          .when(category.is_in(list(NO_CAP_CATEGORIES))).then(False)
          .otherwise(None).alias("cap_present"),
        pl.col("status").is_in(list(CONFIRMED_STATUS_CODES)).alias("confirmed"),
    )


# --- validation ------------------------------------------------------------

class SchemaError(ValueError):
    """Raised when a frame does not conform to EVENT_COLUMNS."""


def empty_events() -> pl.DataFrame:
    """An empty event table with exactly the right columns and dtypes.

    Tools return this rather than None when a filter matches nothing, so
    downstream code never has to branch on the empty case.
    """
    return pl.DataFrame(schema=dict(EVENT_COLUMNS))


def validate_events(events: pl.DataFrame, *, strict: bool = True) -> list[str]:
    """Check a frame against the contract. Returns a list of problems.

    strict=True (default) raises SchemaError instead of returning. This is the
    one assertion that makes swapping the synthetic generator for the real
    loader a one-line change.
    """
    problems: list[str] = []
    schema = events.schema

    missing = [c for c in EVENT_COLUMNS if c not in schema]
    if missing:
        problems.append(f"missing columns: {missing}")

    extra = [c for c in schema if c not in EVENT_COLUMNS]
    if extra:
        problems.append(f"unexpected columns: {extra} (extend EVENT_COLUMNS first)")

    for name, expected in EVENT_COLUMNS.items():
        if name not in schema:
            continue
        actual = schema[name]
        if actual != expected:
            problems.append(f"{name}: dtype {actual!r}, contract says {expected!r}")

    if "ts" in schema and events.height:
        dtype = schema["ts"]
        if isinstance(dtype, pl.Datetime) and dtype.time_zone is not None:
            problems.append("ts is timezone-aware; contract says plant-local naive")
        if not events["ts"].is_sorted():
            problems.append("ts is not sorted ascending")

    if strict and problems:
        raise SchemaError("event table does not match the contract:\n  - " +
                          "\n  - ".join(problems))
    return problems


def conform(events: pl.DataFrame) -> pl.DataFrame:
    """Coerce a frame to the contract: column order and dtypes. Then validate."""
    present = [c for c in EVENT_COLUMNS if c in events.columns]
    out = events.select([pl.col(c).cast(EVENT_COLUMNS[c]) for c in present])
    validate_events(out)
    return out
