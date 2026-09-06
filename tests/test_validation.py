import pandas as pd

from src.ingestion.loader import (
    load_config,
    load_pool,
)

from src.ingestion.validation import (
    check_missing_values,
    check_duplicate_timestamps,
    check_out_of_order_timestamps,
    check_timestamp_gaps,
    check_dtypes,
    check_units_metadata,
    validate_data,
)


# =========================================================
# MISSING VALUES
# =========================================================

def test_clean_data_has_no_missing_values():
    """
    Clean sample data should contain no missing values.
    """
    df = load_pool("sample")

    result = check_missing_values(df)

    assert result == {}


def test_missing_value_is_detected():
    """
    Inject one missing value and verify that validation
    reports exactly that column and count.
    """
    df = load_pool("sample")

    # Work on a copy so the original sample is untouched
    bad_df = df.copy()

    # Inject one missing value
    bad_df.loc[0, "H01 AppTorque"] = None

    result = check_missing_values(bad_df)

    assert result == {
        "H01 AppTorque": 1
    }


# =========================================================
# DUPLICATE TIMESTAMPS
# =========================================================

def test_clean_data_has_no_duplicate_timestamps():
    """
    Clean sample data should contain no duplicate timestamps.
    """
    df = load_pool("sample")

    result = check_duplicate_timestamps(df)

    assert result["count"] == 0
    assert result["timestamps"] == []


def test_duplicate_timestamp_is_detected():
    """
    Inject one duplicate timestamp and verify that
    the validator finds exactly one duplicate row.
    """
    df = load_pool("sample")

    bad_df = df.copy()

    # Make row 1 use the same timestamp as row 0
    bad_df.loc[1, "timestamp"] = bad_df.loc[0, "timestamp"]

    result = check_duplicate_timestamps(bad_df)

    assert result["count"] == 1
    assert len(result["timestamps"]) == 1


# =========================================================
# OUT-OF-ORDER TIMESTAMPS
# =========================================================

def test_clean_data_is_in_timestamp_order():
    """
    Clean sample timestamps should never move backwards.
    """
    df = load_pool("sample")

    result = check_out_of_order_timestamps(df)

    assert result["count"] == 0
    assert result["rows"] == []


def test_out_of_order_timestamp_is_detected():
    """
    Inject one timestamp that moves backwards in time.
    """
    df = load_pool("sample")

    bad_df = df.copy()

    # Make row 2 occur one second BEFORE row 1
    bad_df.loc[2, "timestamp"] = (
        bad_df.loc[1, "timestamp"]
        - pd.Timedelta(seconds=1)
    )

    result = check_out_of_order_timestamps(bad_df)

    assert result["count"] == 1
    assert len(result["rows"]) == 1
    assert result["rows"][0]["row_index"] == 2


# =========================================================
# TIMESTAMP GAPS
# =========================================================

def test_clean_data_has_no_timestamp_gaps():
    """
    Clean sample data should have no gaps larger than
    the expected one-second sampling interval.
    """
    df = load_pool("sample")

    result = check_timestamp_gaps(df)

    assert result["count"] == 0
    assert result["rows"] == []


def test_timestamp_gap_is_detected():
    """
    Inject a five-second interval between two rows and
    verify that the gap is reported.
    """
    df = load_pool("sample")

    bad_df = df.copy()

    # Make row 2 occur 5 seconds after row 1
    bad_df.loc[2, "timestamp"] = (
        bad_df.loc[1, "timestamp"]
        + pd.Timedelta(seconds=5)
    )

    result = check_timestamp_gaps(bad_df)

    assert result["count"] == 1
    assert len(result["rows"]) == 1
    assert result["rows"][0]["row_index"] == 2
    assert result["rows"][0]["gap_seconds"] == 5.0


# =========================================================
# DTYPE / VALUE-TYPE VALIDATION
# =========================================================

def test_clean_data_has_valid_dtypes():
    """
    The clean sample should satisfy all expected
    timestamp/count/status/torque type rules.
    """
    df = load_pool("sample")

    result = check_dtypes(df)

    assert result["issues"] == []


def test_bad_count_value_is_detected():
    """
    Count values must be integer-like.

    104085.0 is acceptable.
    104085.5 is not.
    """
    df = load_pool("sample")

    bad_df = df.copy()

    bad_df.loc[0, "H01 Count"] = 104085.5

    result = check_dtypes(bad_df)

    assert any(
        issue["column"] == "H01 Count"
        for issue in result["issues"]
    )


def test_bad_status_value_is_detected():
    """
    Status codes must also be integer-like.
    """
    df = load_pool("sample")

    bad_df = df.copy()

    # Deliberately inject an invalid decimal status
    bad_df.loc[0, "H01 Status"] = 2.5

    result = check_dtypes(bad_df)

    assert any(
        issue["column"] == "H01 Status"
        for issue in result["issues"]
    )


def test_bad_torque_dtype_is_detected():
    """
    AppTorque columns must contain numeric values.
    """
    df = load_pool("sample")

    bad_df = df.copy()

    # Convert the entire torque column to strings
    bad_df["H01 AppTorque"] = (
        bad_df["H01 AppTorque"].astype(str)
    )

    result = check_dtypes(bad_df)

    assert any(
        issue["column"] == "H01 AppTorque"
        for issue in result["issues"]
    )


# =========================================================
# UNITS METADATA
# =========================================================

def test_units_metadata_is_valid():
    """
    Config should contain the expected AppTorque unit.
    """
    config = load_config("config.yaml")

    result = check_units_metadata(config)

    assert result["valid"] is True
    assert result["issues"] == []


def test_missing_units_metadata_is_detected():
    """
    Remove the units section from a copy of the config
    and verify that validation reports the problem.
    """
    config = load_config("config.yaml")

    # Copy the outer dictionary
    bad_config = config.copy()

    # Copy the nested data dictionary so the original
    # config is not modified
    bad_config["data"] = config["data"].copy()

    # Remove the units metadata
    bad_config["data"].pop(
        "units",
        None
    )

    result = check_units_metadata(
        bad_config
    )

    assert result["valid"] is False


# =========================================================
# COMPLETE VALIDATION REPORT
# =========================================================

def test_clean_data_validation_report():
    """
    Running every validation check on clean sample data
    should result in an overall valid report.
    """
    df = load_pool("sample")
    config = load_config("config.yaml")

    report = validate_data(
        df,
        config
    )

    assert report["valid"] is True

    assert report["missing_values"] == {}

    assert (
        report["timestamps"]["duplicates"]["count"]
        == 0
    )

    assert (
        report["timestamps"]["out_of_order"]["count"]
        == 0
    )

    assert (
        report["timestamps"]["gaps"]["count"]
        == 0
    )

    assert report["dtypes"]["issues"] == []

    assert report["units"]["valid"] is True


def test_validation_reports_multiple_problems():
    """
    Inject several different problems at once.

    Validation should report them rather than crash
    or silently modify the DataFrame.
    """
    df = load_pool("sample")
    config = load_config("config.yaml")

    bad_df = df.copy()

    # Problem 1: missing torque value
    bad_df.loc[0, "H01 AppTorque"] = None

    # Problem 2: duplicate timestamp
    bad_df.loc[2, "timestamp"] = (
        bad_df.loc[1, "timestamp"]
    )

    # Problem 3: non-integer Count value
    bad_df.loc[3, "H01 Count"] = 100.5

    report = validate_data(
        bad_df,
        config
    )

    # Overall validation must fail
    assert report["valid"] is False

    # Missing value should be reported
    assert (
        report["missing_values"]["H01 AppTorque"]
        == 1
    )

    # Duplicate timestamp should be reported
    assert (
        report["timestamps"]["duplicates"]["count"]
        >= 1
    )

    # Invalid Count should be reported
    assert len(
        report["dtypes"]["issues"]
    ) >= 1