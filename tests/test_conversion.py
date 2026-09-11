from pathlib import Path

import polars as pl

from src.ingestion.conversion import convert_csv_to_parquet


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