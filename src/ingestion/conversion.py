from pathlib import Path

import polars as pl


def scan_csv_telemetry(csv_path):
    """
    Lazily scan an AROL telemetry CSV and make sure
    the timestamp column is parsed as Datetime.

    Supports the timestamp formats we have observed:

        2026-02-01 10:00:00
        2026-02-01T10:54:43.000

    Returns:
        pl.LazyFrame
    """

    csv_path = Path(csv_path)

    if not csv_path.exists():
        raise FileNotFoundError(
            f"CSV file not found: {csv_path}"
        )

    # Let Polars infer date/datetime columns where possible.
    lazy_df = pl.scan_csv(
        csv_path,
        try_parse_dates=True,
    )

    schema = lazy_df.collect_schema()

    if "timestamp" not in schema:
        raise ValueError(
            "timestamp column is missing"
        )

    # If Polars did not automatically infer timestamp
    # as Datetime, parse it explicitly.
    if (
        schema["timestamp"].base_type()
        != pl.Datetime
    ):
        lazy_df = lazy_df.with_columns(
            pl.col("timestamp")
            .str.to_datetime(
                strict=True
            )
        )

    return lazy_df


def convert_csv_to_parquet(
    csv_path,
    parquet_path,
):
    """
    Convert one AROL telemetry CSV file to Parquet.

    Timestamp parsing happens during this conversion so
    later Parquet processing already has a Datetime column.
    """

    csv_path = Path(csv_path)
    parquet_path = Path(parquet_path)

    parquet_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        scan_csv_telemetry(
            csv_path
        )
        .sink_parquet(
            parquet_path
        )
    )


def convert_csv_pool_to_parquet(
    csv_paths,
    output_dir,
):
    """
    Convert multiple AROL CSV files to Parquet.

    One Parquet file is produced for each input CSV.
    Input file order is preserved in the returned list.
    """

    output_dir = Path(
        output_dir
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    parquet_paths = []

    for csv_path in csv_paths:

        csv_path = Path(
            csv_path
        )

        parquet_path = (
            output_dir
            /
            f"{csv_path.stem}.parquet"
        )

        convert_csv_to_parquet(
            csv_path,
            parquet_path,
        )

        parquet_paths.append(
            parquet_path
        )

    return parquet_paths