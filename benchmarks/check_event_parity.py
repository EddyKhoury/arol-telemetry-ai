import argparse
import time

import pandas as pd
import polars as pl

from polars.testing import assert_frame_equal

from src.ingestion.event_table import (
    build_event_table as build_event_table_pandas,
)

from src.ingestion.event_table_polars import (
    build_event_table as build_event_table_polars,
)

from src.ingestion.conversion import (
    scan_csv_telemetry,
)


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


def load_pandas_csv(path):
    return pd.read_csv(
        path,
        parse_dates=["timestamp"],
    )


def normalize_pandas_events(events):
    """
    Convert the pandas reference event table to the same
    canonical Polars schema used by the production pipeline.
    """

    result = pl.from_pandas(
        events
    )

    return result.select(
        pl.col("ts")
        .cast(
            pl.Datetime("us")
        ),

        pl.col("machine_id")
        .cast(
            pl.String
        ),

        pl.col("head_id")
        .cast(
            pl.String
        ),

        pl.col("torque")
        .cast(
            pl.Float64
        ),

        pl.col("status")
        .cast(
            pl.Int64
        ),

        pl.col("error_class")
        .cast(
            pl.String
        ),

        pl.col("reject_signal")
        .cast(
            pl.Boolean
        ),

        pl.col("cap_present")
        .cast(
            pl.Boolean
        ),
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "csv_path",
    )

    parser.add_argument(
        "--machine-id",
        default="MCC777",
    )

    args = parser.parse_args()

    print(
        "Building pandas reference events..."
    )

    start = time.perf_counter()

    pandas_telemetry = load_pandas_csv(
        args.csv_path
    )

    pandas_events = (
        build_event_table_pandas(
            pandas_telemetry,
            args.machine_id,
        )
    )

    pandas_seconds = (
        time.perf_counter()
        - start
    )

    print(
        f"Pandas events: "
        f"{len(pandas_events):,}"
    )

    print(
        f"Pandas time: "
        f"{pandas_seconds:.3f} s"
    )

    print(
        "Building Polars production events..."
    )

    start = time.perf_counter()

    polars_telemetry = (
        scan_csv_telemetry(
            args.csv_path
        )
    )

    polars_events = (
        build_event_table_polars(
            polars_telemetry,
            args.machine_id,
        )
    )

    polars_seconds = (
        time.perf_counter()
        - start
    )

    print(
        f"Polars events: "
        f"{polars_events.height:,}"
    )

    print(
        f"Polars time: "
        f"{polars_seconds:.3f} s"
    )

    pandas_events_normalized = (
        normalize_pandas_events(
            pandas_events
        )
    )

    print(
        "Comparing complete event tables..."
    )

    assert_frame_equal(
        pandas_events_normalized,
        polars_events,
        check_dtypes=True,
        check_row_order=True,
        check_column_order=True,
    )

    print()
    print(
        "PARITY PASSED"
    )

    print(
        f"All {polars_events.height:,} event rows "
        f"match exactly."
    )


if __name__ == "__main__":
    main()