"""Event-table schema and status decoding.

Single source of truth for the A/B integration contract. Both the real loader
(Person A, src/ingestion) and the synthetic generator (Person B, src/testing)
must produce frames that pass `validate_events`.

Derived from Person A's contract.pdf, with the amendments agreed in the audit:
  - pool_id, count_delta, head_index added   (contract OPEN item 2)
  - timestamps are plant-local and naive     (audit F5)
  - status decoded as a bitfield, not an enum (audit F11)
  - count_delta > 1 is representable         (audit F6)
"""

from __future__ import annotations

# Bump on any breaking change to EVENT_COLUMNS. Loader and generator both
# stamp it; the conformance test asserts they agree.
SCHEMA_VERSION = "1.0"

# Column -> pandas dtype. Order is the canonical column order.
EVENT_COLUMNS: dict[str, str] = {
    "ts":            "datetime64[ns]",  # plant-local, naive. See TIMEZONE_POLICY.
    "pool_id":       "string",          # which pool this event came from
    "machine_id":    "string",          # parsed from the filename (MCC777...)
    "head_id":       "string",          # "H01".."H36"
    "head_index":    "int16",           # 1..36, for correct numeric sort order
    "torque":        "float64",         # H## AppTorque on the increment row, Nm
    "status":        "int16",           # H## Status on the increment row, raw code
    "error_class":   "string",          # decoded from status
    "reject_signal": "bool",            # status bit 0
    "cap_present":   "bool",            # a cap was actually applied
    "count_delta":   "int32",           # counter increment that produced this event
    "inferred":      "bool",            # True when count_delta > 1 (dropped sample)
}

TORQUE_UNIT = "Nm"

# Timestamps are kept in plant-local wall-clock time with no tzinfo, so that
# "per day" and "per shift" match what an operator on the line would say.
# The originating timezone is reported in pool_meta()["timezone"], not baked
# into the values. Never call tz_localize/tz_convert on `ts`.
TIMEZONE_POLICY = "plant-local naive"


# --- status decoding -------------------------------------------------------
#
# Observed in the real pools: only 0, 2 and 65 occur. The brief lists further
# codes (3, 4/5, 8/9, 16/17, 32/33, 64) that pair as n / n+1, which is what a
# bitfield looks like: bit 0 is the reject flag, the high bits are the error
# category. That reading reproduces all three observed codes exactly:
#     0  -> category 0  (Closure OK), not rejected
#     2  -> category 2  (No Load),    not rejected
#     65 -> category 64 (Bad Closure), rejected      (65 == 64 | 1)
#
# PROVISIONAL: confirmed for categories 0, 2 and 64 only. Categories 4, 8, 16
# and 32 appear in the brief but their names are not known to us; they decode
# to "Unknown (<code>)" and are counted as unconfirmed rather than crashing.
# Replace CATEGORY_NAMES from AROL's own code table when we get it.

REJECT_BIT = 0b1

CATEGORY_NAMES: dict[int, str] = {
    0:  "Closure OK",
    2:  "No Load",
    64: "Bad Closure",
}

# Categories where no cap was physically present in the head.
NO_CAP_CATEGORIES: frozenset[int] = frozenset({2})

# Codes we have actually seen in the data and can vouch for.
CONFIRMED_STATUS_CODES: frozenset[int] = frozenset({0, 2, 65})


def decode_status(status: int) -> dict:
    """Decode one raw status code into its contract fields.

    Never raises on an unseen code: an unknown category yields
    error_class "Unknown (<code>)" and confirmed=False, so a grading dataset
    with new codes degrades instead of crashing.
    """
    status = int(status)
    category = status & ~REJECT_BIT
    reject = bool(status & REJECT_BIT)
    name = CATEGORY_NAMES.get(category)
    return {
        "error_class": name if name is not None else f"Unknown ({status})",
        "reject_signal": reject,
        # Assumption: a cap was present unless the category says otherwise.
        "cap_present": category not in NO_CAP_CATEGORIES,
        "confirmed": status in CONFIRMED_STATUS_CODES,
    }


def decode_status_series(status):
    """Vectorised decode_status. Returns a DataFrame indexed like `status`."""
    import pandas as pd

    codes = pd.Series(status).astype("int16")
    category = codes & ~REJECT_BIT
    names = category.map(CATEGORY_NAMES)
    return pd.DataFrame(
        {
            "error_class": names.where(
                names.notna(), "Unknown (" + codes.astype(str) + ")"
            ).astype("string"),
            "reject_signal": (codes & REJECT_BIT).astype(bool),
            "cap_present": (~category.isin(NO_CAP_CATEGORIES)).astype(bool),
            "confirmed": codes.isin(CONFIRMED_STATUS_CODES).astype(bool),
        },
        index=codes.index,
    )


# --- validation ------------------------------------------------------------

class SchemaError(ValueError):
    """Raised when a frame does not conform to EVENT_COLUMNS."""


def empty_events():
    """An empty event table with exactly the right columns and dtypes.

    Tools return this rather than None when a filter matches nothing, so
    downstream code never has to branch on the empty case.
    """
    import pandas as pd

    return pd.DataFrame(
        {name: pd.Series(dtype=dtype) for name, dtype in EVENT_COLUMNS.items()}
    )


def validate_events(events, *, strict: bool = True) -> list[str]:
    """Check a frame against the contract. Returns a list of problems.

    strict=True (default) raises SchemaError instead of returning. This is the
    one assertion that makes swapping the synthetic generator for the real
    loader a one-line change.
    """
    problems: list[str] = []

    missing = [c for c in EVENT_COLUMNS if c not in events.columns]
    if missing:
        problems.append(f"missing columns: {missing}")

    extra = [c for c in events.columns if c not in EVENT_COLUMNS]
    if extra:
        problems.append(f"unexpected columns: {extra} (extend EVENT_COLUMNS first)")

    for name, expected in EVENT_COLUMNS.items():
        if name not in events.columns:
            continue
        actual = str(events[name].dtype)
        if actual != expected:
            problems.append(f"{name}: dtype {actual!r}, contract says {expected!r}")

    if "ts" in events.columns and len(events):
        if getattr(events["ts"].dtype, "tz", None) is not None:
            problems.append("ts is timezone-aware; contract says plant-local naive")
        if not events["ts"].is_monotonic_increasing:
            problems.append("ts is not sorted ascending")

    if strict and problems:
        raise SchemaError("event table does not match the contract:\n  - " +
                          "\n  - ".join(problems))
    return problems


def conform(events):
    """Coerce a frame to the contract: column order and dtypes. Then validate."""
    out = events.loc[:, [c for c in EVENT_COLUMNS if c in events.columns]].copy()
    for name, dtype in EVENT_COLUMNS.items():
        if name in out.columns and str(out[name].dtype) != dtype:
            out[name] = out[name].astype(dtype)
    validate_events(out)
    return out
