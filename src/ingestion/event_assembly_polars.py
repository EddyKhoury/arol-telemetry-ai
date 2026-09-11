import polars as pl


# =========================================================
# STATUS DEFINITIONS
# =========================================================

STATUS_MAP = {
    0: ("Closure OK", False),
    2: ("No Load", False),
    3: ("No Load", True),
    4: ("No Closure", False),
    5: ("No Closure", True),
    8: ("No InTorque", False),
    9: ("No InTorque", True),
    16: ("No CapTurns", False),
    17: ("No CapTurns", True),
    32: ("Following Error", False),
    33: ("Following Error", True),
    64: ("Bad Closure", False),
    65: ("Bad Closure", True),
}


CAP_PRESENT_MAP = {
    0: True,
    2: False,
    65: True,
}


EVENT_COLUMNS = [
    "ts",
    "machine_id",
    "head_id",
    "torque",
    "status",
    "error_class",
    "reject_signal",
    "cap_present",
]


# =========================================================
# INPUT NORMALIZATION
# =========================================================

def _as_lazy(df):
    """
    Normalize supported Polars input to LazyFrame.
    """

    if isinstance(df, pl.LazyFrame):
        return df

    if isinstance(df, pl.DataFrame):
        return df.lazy()

    raise TypeError(
        "df must be a Polars DataFrame or LazyFrame"
    )


# =========================================================
# STATUS LOOKUP TABLE
# =========================================================

def _build_status_lookup():
    """
    Build the small status-code lookup as a Polars LazyFrame.

    The lookup has only 13 rows, so joining against it is
    inexpensive while allowing status decoding to remain
    vectorized.
    """

    rows = []

    for status, (
        error_class,
        reject_signal,
    ) in STATUS_MAP.items():

        rows.append({
            "status": status,
            "error_class": error_class,
            "reject_signal": reject_signal,
            "cap_present":
                CAP_PRESENT_MAP.get(
                    status
                ),
        })

    return (
        pl.DataFrame(
            rows,
            schema={
                "status": pl.Int64,
                "error_class": pl.String,
                "reject_signal": pl.Boolean,
                "cap_present": pl.Boolean,
            },
        )
        .lazy()
    )


# =========================================================
# SCALAR COMPATIBILITY FUNCTIONS
# =========================================================

def decode_status(status):
    """
    Decode one status code.

    This preserves the same logical behavior as the
    original pandas/reference implementation.
    """

    if status in STATUS_MAP:

        error_class, reject_signal = (
            STATUS_MAP[status]
        )

        return {
            "error_class":
                error_class,

            "reject_signal":
                reject_signal,

            "cap_present":
                CAP_PRESENT_MAP.get(
                    status
                ),
        }

    return {
        "error_class":
            f"Unknown ({status})",

        "reject_signal":
            None,

        "cap_present":
            None,
    }


def assemble_event(
    closure,
    machine_id,
):
    """
    Assemble one event dictionary.

    This compatibility helper preserves the original
    scalar event semantics.
    """

    decoded = decode_status(
        closure["status"]
    )

    return {
        "ts":
            closure["timestamp"],

        "machine_id":
            machine_id,

        "head_id":
            closure["head_id"],

        "torque":
            closure["torque"],

        "status":
            closure["status"],

        "error_class":
            decoded[
                "error_class"
            ],

        "reject_signal":
            decoded[
                "reject_signal"
            ],

        "cap_present":
            decoded[
                "cap_present"
            ],
    }


# =========================================================
# VECTORIZED PRODUCTION EVENT ASSEMBLY
# =========================================================

def assemble_events_frame(
    closures,
    machine_id,
):
    """
    Assemble closure rows into the agreed event schema
    using Polars expressions.

    Expected input closure columns:

        row_index
        head_id
        torque
        status
        timestamp

    Returns a LazyFrame with:

        ts
        machine_id
        head_id
        torque
        status
        error_class
        reject_signal
        cap_present

    Status decoding is performed using a vectorized
    join against the small status lookup table.
    """

    lazy_closures = _as_lazy(
        closures
    )

    lookup = (
        _build_status_lookup()
    )

    # Normalize important event dtypes before the join.
    normalized = (
        lazy_closures
        .with_columns(
            pl.col(
                "status"
            )
            .cast(
                pl.Int64
            ),

            pl.col(
                "torque"
            )
            .cast(
                pl.Float64
            ),

            pl.col(
                "head_id"
            )
            .cast(
                pl.String
            ),
        )
    )

    events = (
        normalized

        # Small vectorized lookup instead of decoding
        # every event through a Python loop.
        .join(
            lookup,
            on="status",
            how="left",
        )

        # Unknown codes do not exist in the lookup.
        # Their error_class must therefore be generated
        # dynamically as "Unknown (<code>)".
        .with_columns(
            pl.coalesce([
                pl.col(
                    "error_class"
                ),

                pl.concat_str([
                    pl.lit(
                        "Unknown ("
                    ),

                    pl.col(
                        "status"
                    ).cast(
                        pl.String
                    ),

                    pl.lit(
                        ")"
                    ),
                ]),
            ])
            .alias(
                "error_class"
            )
        )

        # Return exactly the agreed event schema.
        .select(
            pl.col(
                "timestamp"
            ).alias(
                "ts"
            ),

            pl.lit(
                machine_id
            )
            .cast(
                pl.String
            )
            .alias(
                "machine_id"
            ),

            pl.col(
                "head_id"
            ),

            pl.col(
                "torque"
            ),

            pl.col(
                "status"
            ),

            pl.col(
                "error_class"
            ),

            pl.col(
                "reject_signal"
            ),

            pl.col(
                "cap_present"
            ),
        )
    )

    return events


def assemble_events(
    closures,
    machine_id,
):
    """
    Compatibility wrapper.

    The large event assembly operation stays inside Polars.
    Only the final event rows are converted to Python
    dictionaries when this wrapper is explicitly used.
    """

    event_df = (
        assemble_events_frame(
            closures,
            machine_id,
        )
        .collect()
    )

    return list(
        event_df.iter_rows(
            named=True
        )
    )