import argparse
import json
import time
from pathlib import Path

import pandas as pd
import polars as pl

from src.ingestion.loader import load_config
from src.ingestion.validation import validate_data as validate_pandas
from src.ingestion.validation_polars import validate_data as validate_polars

from src.ingestion.event_table import (
    build_event_table as build_event_table_pandas,
)

from src.ingestion.event_table_polars import (
    build_event_table as build_event_table_polars,
)

from src.ingestion.conversion import (
    convert_csv_pool_to_parquet,
    scan_csv_telemetry,
)

from src.ingestion.loader import (
    scan_parquet_pool,
)





def total_file_size(paths):
    return sum(
        Path(path).stat().st_size
        for path in paths
    )


def load_pandas_csv(paths):
    frames = []

    for path in paths:
        frame = pd.read_csv(
            path,
            parse_dates=["timestamp"],
        )

        frames.append(frame)

    return pd.concat(
        frames,
        ignore_index=True,
    )


def scan_polars_csv(paths):
    frames = [
        scan_csv_telemetry(path)
        for path in paths
    ]

    return pl.concat(
        frames,
        how="vertical",
    )


def benchmark_pandas_csv(
    paths,
    machine_id,
    config,
):
    start_total = time.perf_counter()

    start = time.perf_counter()

    df = load_pandas_csv(paths)

    load_seconds = (
        time.perf_counter()
        - start
    )

    input_rows = len(df)

    start = time.perf_counter()

    validation = validate_pandas(
        df,
        config,
    )

    validation_seconds = (
        time.perf_counter()
        - start
    )

    start = time.perf_counter()

    events = build_event_table_pandas(
        df,
        machine_id,
    )

    event_seconds = (
        time.perf_counter()
        - start
    )

    total_seconds = (
        time.perf_counter()
        - start_total
    )

    return {
        "mode": "pandas_csv",
        "files": len(paths),
        "input_rows": input_rows,
        "input_bytes": total_file_size(paths),
        "validation_valid": validation["valid"],
        "event_count": len(events),
        "load_seconds": load_seconds,
        "validation_seconds": validation_seconds,
        "event_build_seconds": event_seconds,
        "total_seconds": total_seconds,
    }


def benchmark_polars_csv(
    paths,
    machine_id,
    config,
):
    start_total = time.perf_counter()

    start = time.perf_counter()

    df = scan_polars_csv(paths)

    scan_setup_seconds = (
        time.perf_counter()
        - start
    )

    start = time.perf_counter()

    validation = validate_polars(
        df,
        config,
    )

    validation_seconds = (
        time.perf_counter()
        - start
    )

    start = time.perf_counter()

    events = build_event_table_polars(
        df,
        machine_id,
    )

    event_seconds = (
        time.perf_counter()
        - start
    )

    total_seconds = (
        time.perf_counter()
        - start_total
    )

    # Record row count after the measured run so the
    # extra count scan does not inflate benchmark timing.
    input_rows = (
        df.select(
            pl.len()
        )
        .collect()
        .item()
    )

    return {
        "mode": "polars_csv",
        "files": len(paths),
        "input_rows": input_rows,
        "input_bytes": total_file_size(paths),
        "validation_valid": validation["valid"],
        "event_count": events.height,
        "scan_setup_seconds": scan_setup_seconds,
        "validation_seconds": validation_seconds,
        "event_build_seconds": event_seconds,
        "total_seconds": total_seconds,
    }


def benchmark_polars_parquet(
    paths,
    machine_id,
    config,
):
    start_total = time.perf_counter()

    start = time.perf_counter()

    df = scan_parquet_pool(paths)

    scan_setup_seconds = (
        time.perf_counter()
        - start
    )

    start = time.perf_counter()

    validation = validate_polars(
        df,
        config,
    )

    validation_seconds = (
        time.perf_counter()
        - start
    )

    start = time.perf_counter()

    events = build_event_table_polars(
        df,
        machine_id,
    )

    event_seconds = (
        time.perf_counter()
        - start
    )

    total_seconds = (
        time.perf_counter()
        - start_total
    )

    input_rows = (
        df.select(
            pl.len()
        )
        .collect()
        .item()
    )

    return {
        "mode": "polars_parquet",
        "files": len(paths),
        "input_rows": input_rows,
        "input_bytes": total_file_size(paths),
        "validation_valid": validation["valid"],
        "event_count": events.height,
        "scan_setup_seconds": scan_setup_seconds,
        "validation_seconds": validation_seconds,
        "event_build_seconds": event_seconds,
        "total_seconds": total_seconds,
    }


def prepare_parquet(
    csv_paths,
    output_dir,
):
    start = time.perf_counter()

    parquet_paths = (
        convert_csv_pool_to_parquet(
            csv_paths,
            output_dir,
        )
    )

    elapsed = (
        time.perf_counter()
        - start
    )

    result = {
        "mode": "csv_to_parquet_conversion",
        "files": len(csv_paths),
        "input_bytes": total_file_size(
            csv_paths
        ),
        "output_bytes": total_file_size(
            parquet_paths
        ),
        "conversion_seconds": elapsed,
        "parquet_paths": [
            str(path)
            for path in parquet_paths
        ],
    }

    return result


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        required=True,
        choices=[
            "pandas-csv",
            "polars-csv",
            "prepare-parquet",
            "polars-parquet",
        ],
    )

    parser.add_argument(
        "--machine-id",
        default="MCC777",
    )

    parser.add_argument(
        "--config",
        default="config.yaml",
    )

    parser.add_argument(
        "--output-dir",
        default="data/parquet/benchmark",
    )

    parser.add_argument(
        "--result",
        default=None,
    )

    parser.add_argument(
        "paths",
        nargs="+",
    )

    args = parser.parse_args()

    config = load_config(
        args.config
    )

    paths = [
        Path(path)
        for path in args.paths
    ]

    if args.mode == "pandas-csv":

        result = benchmark_pandas_csv(
            paths,
            args.machine_id,
            config,
        )

    elif args.mode == "polars-csv":

        result = benchmark_polars_csv(
            paths,
            args.machine_id,
            config,
        )

    elif args.mode == "prepare-parquet":

        result = prepare_parquet(
            paths,
            args.output_dir,
        )

    else:

        result = benchmark_polars_parquet(
            paths,
            args.machine_id,
            config,
        )

    print(
        json.dumps(
            result,
            indent=2,
        )
    )

    if args.result is not None:

        result_path = Path(
            args.result
        )

        result_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        result_path.write_text(
            json.dumps(
                result,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()