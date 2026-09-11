import pandas as pd
import pytest
import yaml
import polars as pl

from src.ingestion.loader import scan_parquet_file
from src.ingestion.loader import (
    LoaderError,
    load_config,
    get_pool_files,
    load_file,
    load_pool,
)


# ---------------------------------------------------------
# TEST 1
# Check that config.yaml can be loaded correctly.
# ---------------------------------------------------------
def test_config_loads():
    config = load_config("config.yaml")

    # Our config must contain:
    # data -> pools -> sample
    assert "data" in config
    assert "pools" in config["data"]
    assert "sample" in config["data"]["pools"]


# ---------------------------------------------------------
# TEST 2
# Check that the sample file path comes from config.yaml.
# ---------------------------------------------------------
def test_sample_pool_path():
    config = load_config("config.yaml")

    files = get_pool_files(
        config,
        "sample"
    )

    assert files == ["data/sample.csv"]


# ---------------------------------------------------------
# TEST 3
# Check that CSV loading actually returns a DataFrame.
# ---------------------------------------------------------
def test_csv_loads():
    df = load_file("data/sample.csv")

    assert isinstance(df, pd.DataFrame)

    # Our sample should contain some rows.
    assert len(df) > 0


# ---------------------------------------------------------
# TEST 4
# Check that loading does NOT change the source column names.
# ---------------------------------------------------------
def test_column_names_are_preserved():

    # Read the original CSV directly.
    original_df = pd.read_csv("data/sample.csv")

    # Read it through our loader.
    loaded_df = load_file("data/sample.csv")

    # Both must have exactly the same column names
    # in exactly the same order.
    assert list(original_df.columns) == list(loaded_df.columns)


# ---------------------------------------------------------
# TEST 5
# Check that timestamp is a real datetime, not a string.
# ---------------------------------------------------------
def test_timestamp_is_datetime():
    df = load_file("data/sample.csv")

    assert pd.api.types.is_datetime64_any_dtype(
        df["timestamp"]
    )


# ---------------------------------------------------------
# TEST 6
# Check that the entire sample pool can be loaded.
# ---------------------------------------------------------
def test_pool_loads():
    df = load_pool(
        "sample",
        "config.yaml"
    )

    assert isinstance(df, pd.DataFrame)

    # Your current sample has 17 rows.
    assert len(df) == 17

    # 36 heads × 3 columns + timestamp = 109.
    assert len(df.columns) == 109


# ---------------------------------------------------------
# TEST 7
# Asking for a file that does not exist should produce
# our clear LoaderError instead of an unclear raw error.
# ---------------------------------------------------------
def test_missing_file_has_clear_error():

    with pytest.raises(
        LoaderError,
        match="Data file not found"
    ):
        load_file("data/does_not_exist.csv")


# ---------------------------------------------------------
# TEST 8
# Asking for a pool that doesn't exist should also
# produce a clear LoaderError.
# ---------------------------------------------------------
def test_missing_pool_has_clear_error():
    config = load_config("config.yaml")

    with pytest.raises(
        LoaderError,
        match="was not found"
    ):
        get_pool_files(
            config,
            "does_not_exist"
        )


# ---------------------------------------------------------
# TEST 9
# A corrupt CSV should fail cleanly.
#
# tmp_path is a temporary folder automatically provided
# by pytest. It disappears after the test.
# ---------------------------------------------------------
def test_corrupt_file_has_clear_error(tmp_path):

    corrupt_file = tmp_path / "corrupt.csv"

    # Write invalid binary data into something pretending
    # to be a CSV file.
    corrupt_file.write_bytes(
        b"\xff\xfe\x00\x00"
    )

    with pytest.raises(
        LoaderError,
        match="Could not read data file"
    ):
        load_file(corrupt_file)


# ---------------------------------------------------------
# TEST 10
# Check JSON support.
#
# Most importantly, we call load_pool() exactly the same
# way as with CSV. Only config changes.
# ---------------------------------------------------------
def test_json_pool_works(tmp_path):

    # Read our known-good sample.
    original_df = pd.read_csv("data/sample.csv")

    # Create a temporary JSON version.
    json_file = tmp_path / "sample.json"

    original_df.to_json(
        json_file,
        orient="records"
    )

    # Create a temporary config pointing at the JSON file.
    config_file = tmp_path / "config.json_test.yaml"

    config = {
        "data": {
            "pools": {
                "json_test": [
                    str(json_file)
                ]
            },
            "n_heads": None
        }
    }

    with open(config_file, "w") as f:
        yaml.safe_dump(config, f)

    # SAME loader interface as CSV.
    df = load_pool(
        "json_test",
        config_file
    )

    assert isinstance(df, pd.DataFrame)
    assert len(df) == len(original_df)

    # Timestamp must still end up as datetime.
    assert pd.api.types.is_datetime64_any_dtype(
        df["timestamp"]
    )


# ---------------------------------------------------------
# TEST 11
# Check Parquet support.
#
# Again, load_pool() itself does not change.
# ---------------------------------------------------------
def test_parquet_pool_works(tmp_path):

    original_df = pd.read_csv("data/sample.csv")

    # Create temporary Parquet file.
    parquet_file = tmp_path / "sample.parquet"

    original_df.to_parquet(
        parquet_file,
        index=False
    )

    # Temporary config pointing at Parquet.
    config_file = tmp_path / "config.parquet_test.yaml"

    config = {
        "data": {
            "pools": {
                "parquet_test": [
                    str(parquet_file)
                ]
            },
            "n_heads": None
        }
    }

    with open(config_file, "w") as f:
        yaml.safe_dump(config, f)

    # SAME loader interface again.
    df = load_pool(
        "parquet_test",
        config_file
    )

    assert isinstance(df, pd.DataFrame)
    assert len(df) == len(original_df)

    assert pd.api.types.is_datetime64_any_dtype(
        df["timestamp"]
    )


# ---------------------------------------------------------
# TEST 12
# Check that multiple files in a pool are stitched together
# in the order listed in config.
#
# This matters because the contract says day-files form one
# continuous telemetry stream.
# ---------------------------------------------------------
def test_multiple_files_are_stitched_in_order(tmp_path):

    original_df = pd.read_csv("data/sample.csv")

    # Make two small fake "day files".
    first_file_df = original_df.iloc[:3]
    second_file_df = original_df.iloc[3:6]

    first_file = tmp_path / "part1.csv"
    second_file = tmp_path / "part2.csv"

    first_file_df.to_csv(
        first_file,
        index=False
    )

    second_file_df.to_csv(
        second_file,
        index=False
    )

    # Pool order is explicitly part1 then part2.
    config_file = tmp_path / "config.multi.yaml"

    config = {
        "data": {
            "pools": {
                "multi": [
                    str(first_file),
                    str(second_file)
                ]
            },
            "n_heads": None
        }
    }

    with open(config_file, "w") as f:
        yaml.safe_dump(config, f)

    df = load_pool(
        "multi",
        config_file
    )

    # 3 rows + 3 rows = 6 rows.
    assert len(df) == 6

    # Verify the first timestamp still comes from part1.
    expected_first_timestamp = pd.to_datetime(
        first_file_df.iloc[0]["timestamp"]
    )

    assert df.iloc[0]["timestamp"] == expected_first_timestamp

def test_parquet_is_loaded_lazily(tmp_path):
    parquet_path = tmp_path / "telemetry.parquet"

    df = pl.DataFrame({
        "timestamp": [
            "2026-02-01 10:00:00",
            "2026-02-01 10:00:01",
        ],
        "H01 Count": [
            100,
            101,
        ],
        "H01 AppTorque": [
            0.0,
            2.05,
        ],
        "H01 Status": [
            0,
            65,
        ],
    }).with_columns(
        pl.col("timestamp").str.strptime(
            pl.Datetime,
            format="%Y-%m-%d %H:%M:%S",
        )
    )

    df.write_parquet(parquet_path)

    lazy_df = scan_parquet_file(parquet_path)

    assert isinstance(lazy_df, pl.LazyFrame)