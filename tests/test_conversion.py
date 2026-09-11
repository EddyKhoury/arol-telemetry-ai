from pathlib import Path

import polars as pl

from src.ingestion.conversion import (
    convert_csv_to_parquet,
    convert_csv_pool_to_parquet,
)


def test_csv_is_converted_to_parquet(tmp_path):
    csv_path = tmp_path / "telemetry.csv"
    parquet_path = tmp_path / "telemetry.parquet"

    csv_path.write_text(
        "timestamp,H01 Count,H01 AppTorque,H01 Status\n"
        "2026-02-01 10:00:00,100,0.0,0\n"
        "2026-02-01 10:00:01,101,2.05,65\n"
    )

    convert_csv_to_parquet(
        csv_path,
        parquet_path,
    )

    assert parquet_path.exists()

    df = pl.read_parquet(parquet_path)

    assert df.height == 2

    assert df.columns == [
        "timestamp",
        "H01 Count",
        "H01 AppTorque",
        "H01 Status",
    ]

def test_parquet_timestamp_is_datetime(tmp_path):
    csv_path = tmp_path / "telemetry.csv"
    parquet_path = tmp_path / "telemetry.parquet"

    csv_path.write_text(
        "timestamp,H01 Count,H01 AppTorque,H01 Status\n"
        "2026-02-01 10:00:00,100,0.0,0\n"
        "2026-02-01 10:00:01,101,2.05,65\n"
    )

    convert_csv_to_parquet(
        csv_path,
        parquet_path,
    )

    df = pl.read_parquet(parquet_path)

    assert df.schema["timestamp"] == pl.Datetime("us")



def test_parquet_preserves_numeric_column_types(tmp_path):
    csv_path = tmp_path / "telemetry.csv"
    parquet_path = tmp_path / "telemetry.parquet"

    csv_path.write_text(
        "timestamp,H01 Count,H01 AppTorque,H01 Status\n"
        "2026-02-01 10:00:00,100,0.0,0\n"
        "2026-02-01 10:00:01,101,2.05,65\n"
    )

    convert_csv_to_parquet(
        csv_path,
        parquet_path,
    )

    df = pl.read_parquet(parquet_path)

    assert df.schema["H01 Count"].is_integer()
    assert df.schema["H01 AppTorque"].is_float()
    assert df.schema["H01 Status"].is_integer()   

def test_multiple_csv_files_are_converted_to_parquet(tmp_path):
    first_csv = tmp_path / "day_1.csv"
    second_csv = tmp_path / "day_2.csv"

    output_dir = tmp_path / "parquet"

    first_csv.write_text(
        "timestamp,H01 Count,H01 AppTorque,H01 Status\n"
        "2026-02-01 10:00:00,100,0.0,0\n"
    )

    second_csv.write_text(
        "timestamp,H01 Count,H01 AppTorque,H01 Status\n"
        "2026-02-02 10:00:00,101,2.05,65\n"
    )

    parquet_paths = convert_csv_pool_to_parquet(
        [
            first_csv,
            second_csv,
        ],
        output_dir,
    )

    assert len(parquet_paths) == 2

    assert parquet_paths[0].name == "day_1.parquet"
    assert parquet_paths[1].name == "day_2.parquet"

    assert parquet_paths[0].exists()
    assert parquet_paths[1].exists()