from pathlib import Path

import polars as pl

from src.ingestion.closure_detection_polars import (
    detect_head_closures_frame,
)

from src.ingestion.event_assembly_polars import (
    assemble_events_frame,
)


# =========================================================
# FINAL EVENT CONTRACT
# =========================================================

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


EVENT_SCHEMA = {
    "ts": pl.Datetime("us"),
    "machine_id": pl.String,
    "head_id": pl.String,
    "torque": pl.Float64,
    "status": pl.Int64,
    "error_class": pl.String,
    "reject_signal": pl.Boolean,
    "cap_present": pl.Boolean,
}


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


def _empty_event_frame():
    """
    Return an empty LazyFrame with the exact final
    event-table schema.
    """

    return (
        pl.DataFrame(
            schema=EVENT_SCHEMA
        )
        .lazy()
    )


def _enforce_event_schema(df):
    """
    Select the final event columns in the agreed order
    and normalize their dtypes.
    """

    lazy_df = _as_lazy(df)

    return lazy_df.select(
        pl.col("ts")
        .cast(
            pl.Datetime("us")
        )
        .alias("ts"),

        pl.col("machine_id")
        .cast(
            pl.String
        )
        .alias("machine_id"),

        pl.col("head_id")
        .cast(
            pl.String
        )
        .alias("head_id"),

        pl.col("torque")
        .cast(
            pl.Float64
        )
        .alias("torque"),

        pl.col("status")
        .cast(
            pl.Int64
        )
        .alias("status"),

        pl.col("error_class")
        .cast(
            pl.String
        )
        .alias("error_class"),

        pl.col("reject_signal")
        .cast(
            pl.Boolean
        )
        .alias("reject_signal"),

        pl.col("cap_present")
        .cast(
            pl.Boolean
        )
        .alias("cap_present"),
    )


# =========================================================
# HEAD DETECTION
# =========================================================

def detect_head_ids(df):
    """
    Automatically detect capping-head IDs from columns
    ending in " Count".

    No fixed number of heads is assumed.

    Example:

        H01 Count
        H02 Count
        H03 Count

    becomes:

        ["H01", "H02", "H03"]
    """

    lazy_df = _as_lazy(df)

    schema = (
        lazy_df
        .collect_schema()
    )

    head_ids = []

    for column in schema.names():

        if column.endswith(
            " Count"
        ):

            head_id = (
                column.removesuffix(
                    " Count"
                )
            )

            head_ids.append(
                head_id
            )

    return sorted(
        head_ids
    )


# =========================================================
# FINAL EVENT TABLE
# =========================================================

def build_event_table_frame(
    df,
    machine_id,
):
    """
    Build the final event table as a Polars LazyFrame.

    Pipeline:

        raw telemetry
            ↓
        detect heads
            ↓
        detect closures for each head
            ↓
        concatenate closure rows
            ↓
        vectorized status/event assembly
            ↓
        exact event schema
            ↓
        deterministic sort by ts + head_id

    A small Python loop over heads is acceptable.
    There is NO Python loop over raw telemetry rows.
    """

    lazy_df = _as_lazy(df)

    head_ids = detect_head_ids(
        lazy_df
    )

    # No heads means no possible events.
    if not head_ids:
        return _empty_event_frame()

    closure_frames = []

    for head_id in head_ids:

        closures = (
            detect_head_closures_frame(
                lazy_df,
                head_id,
            )
        )

        closure_frames.append(
            closures
        )

    # Every closure frame has the same schema.
    all_closures = pl.concat(
        closure_frames,
        how="vertical",
    )

    events = assemble_events_frame(
        all_closures,
        machine_id=machine_id,
    )

    events = _enforce_event_schema(
        events
    )

    # Reference behavior:
    #
    #   sort by timestamp, then head ID.
    #
    # maintain_order keeps ordering deterministic if
    # rows are otherwise tied.
    events = events.sort(
        [
            "ts",
            "head_id",
        ],
        maintain_order=True,
    )

    return events


def build_event_table(
    df,
    machine_id,
):
    """
    Materialized compatibility wrapper.

    The production calculation remains lazy until the
    final clean event table is requested.
    """

    return (
        build_event_table_frame(
            df,
            machine_id,
        )
        .collect()
    )


# =========================================================
# EVENT PARQUET PERSISTENCE
# =========================================================

def write_event_table_parquet(
    events,
    parquet_path,
):
    """
    Persist the final event table to Parquet.

    Accepts either a Polars DataFrame or LazyFrame.

    The exact event schema is enforced before writing.

    Returns the output Path.
    """

    parquet_path = Path(
        parquet_path
    )

    parquet_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    lazy_events = (
        _enforce_event_schema(
            events
        )
    )

    lazy_events.sink_parquet(
        str(
            parquet_path
        )
    )

    return parquet_path