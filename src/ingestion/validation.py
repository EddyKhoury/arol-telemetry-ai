import pandas as pd


def check_missing_values(df):
    """
    Count missing values in each column.

    Returns an empty dictionary when no missing values exist.

    Example:
    {
        "H01 AppTorque": 2,
        "H05 Status": 1
    }
    """

    # Count missing cells for every column
    missing_counts = df.isna().sum()

    missing_values = {}

    # Keep only columns that actually contain missing values
    for column, count in missing_counts.items():
        if count > 0:
            missing_values[column] = int(count)

    return missing_values


def check_duplicate_timestamps(df):
    """
    Find timestamps that occur more than once.

    The first occurrence is considered valid.
    Later repetitions are considered duplicates.

    Returns:
    {
        "count": ...,
        "timestamps": [...]
    }
    """

    # If timestamp itself is missing from the table,
    # report that instead of crashing.
    if "timestamp" not in df.columns:
        return {
            "count": 0,
            "timestamps": [],
            "error": "timestamp column is missing"
        }

    # True for duplicate occurrences after the first one
    duplicate_mask = df["timestamp"].duplicated(
        keep="first"
    )

    duplicate_timestamps = df.loc[
        duplicate_mask,
        "timestamp"
    ]

    return {
        "count": int(duplicate_mask.sum()),
        "timestamps": [
            str(timestamp)
            for timestamp in duplicate_timestamps
        ]
    }


def check_out_of_order_timestamps(df):
    """
    Detect rows where time moves backwards.

    Returns:
    {
        "count": ...,
        "rows": [
            {
                "row_index": ...,
                "previous_timestamp": ...,
                "current_timestamp": ...
            }
        ]
    }
    """

    if "timestamp" not in df.columns:
        return {
            "count": 0,
            "rows": [],
            "error": "timestamp column is missing"
        }

    # This function requires actual datetime values.
    if not pd.api.types.is_datetime64_any_dtype(
        df["timestamp"]
    ):
        return {
            "count": 0,
            "rows": [],
            "error": "timestamp column is not datetime"
        }

    # Difference between each timestamp and previous timestamp
    differences = df["timestamp"].diff()

    # Previous timestamp for each row
    previous_timestamps = df["timestamp"].shift(1)

    # Negative time difference = time moved backwards
    out_of_order_mask = differences < pd.Timedelta(0)

    rows = []

    for index in df.index[out_of_order_mask]:

        rows.append({
            "row_index": int(index),
            "previous_timestamp": str(
                previous_timestamps.loc[index]
            ),
            "current_timestamp": str(
                df.loc[index, "timestamp"]
            )
        })

    return {
        "count": int(out_of_order_mask.sum()),
        "rows": rows
    }


def check_timestamp_gaps(df):
    """
    Detect gaps larger than the expected 1-second sampling interval.

    Returns:
    {
        "count": ...,
        "rows": [
            {
                "row_index": ...,
                "previous_timestamp": ...,
                "current_timestamp": ...,
                "gap_seconds": ...
            }
        ]
    }
    """

    if "timestamp" not in df.columns:
        return {
            "count": 0,
            "rows": [],
            "error": "timestamp column is missing"
        }

    if not pd.api.types.is_datetime64_any_dtype(
        df["timestamp"]
    ):
        return {
            "count": 0,
            "rows": [],
            "error": "timestamp column is not datetime"
        }

    # Difference between consecutive timestamps
    differences = df["timestamp"].diff()

    previous_timestamps = df["timestamp"].shift(1)

    # Real telemetry is sampled once per second.
    # Anything larger than 1 second represents a gap.
    gap_mask = differences > pd.Timedelta(seconds=1)

    gap_rows = []

    for index in df.index[gap_mask]:

        gap_rows.append({
            "row_index": int(index),

            "previous_timestamp": str(
                previous_timestamps.loc[index]
            ),

            "current_timestamp": str(
                df.loc[index, "timestamp"]
            ),

            "gap_seconds": float(
                differences.loc[index].total_seconds()
            )
        })

    return {
        "count": int(gap_mask.sum()),
        "rows": gap_rows
    }


def check_dtypes(df):
    """
    Check the expected data types of telemetry columns.

    Rules:

    timestamp:
        must be pandas datetime

    * Count:
        must be numeric and contain integer-like values

    * AppTorque:
        must be numeric

    * Status:
        must be numeric and contain integer-like values

    Returns:
    {
        "issues": [...]
    }
    """

    issues = []

    # -----------------------------------------------------
    # TIMESTAMP
    # -----------------------------------------------------

    if "timestamp" not in df.columns:

        issues.append({
            "column": "timestamp",
            "problem": "column is missing"
        })

    elif not pd.api.types.is_datetime64_any_dtype(
        df["timestamp"]
    ):

        issues.append({
            "column": "timestamp",
            "problem": "expected datetime"
        })

    # -----------------------------------------------------
    # COUNT COLUMNS
    # -----------------------------------------------------

    count_columns = [
        column
        for column in df.columns
        if column.endswith(" Count")
    ]

    for column in count_columns:

        # Count must contain numeric data
        if not pd.api.types.is_numeric_dtype(df[column]):

            issues.append({
                "column": column,
                "problem": "expected numeric integer-like values"
            })

            continue

        # Ignore missing values here because missing-value validation
        # already has its own dedicated check.
        values = df[column].dropna()

        # Example:
        # 104085.0 -> valid integer-like value
        # 104085.5 -> invalid
        non_integer_values = (
            values % 1 != 0
        )

        if non_integer_values.any():

            issues.append({
                "column": column,
                "problem": "contains non-integer Count values"
            })

    # -----------------------------------------------------
    # STATUS COLUMNS
    # -----------------------------------------------------

    status_columns = [
        column
        for column in df.columns
        if column.endswith(" Status")
    ]

    for column in status_columns:

        if not pd.api.types.is_numeric_dtype(df[column]):

            issues.append({
                "column": column,
                "problem": "expected numeric integer-like values"
            })

            continue

        values = df[column].dropna()

        non_integer_values = (
            values % 1 != 0
        )

        if non_integer_values.any():

            issues.append({
                "column": column,
                "problem": "contains non-integer Status values"
            })

    # -----------------------------------------------------
    # TORQUE COLUMNS
    # -----------------------------------------------------

    torque_columns = [
        column
        for column in df.columns
        if column.endswith(" AppTorque")
    ]

    for column in torque_columns:

        if not pd.api.types.is_numeric_dtype(df[column]):

            issues.append({
                "column": column,
                "problem": "expected numeric torque values"
            })

    return {
        "issues": issues
    }


def check_units_metadata(config):
    """
    Check that expected units metadata exists in config.

    Current project convention:
        AppTorque -> Nm

    NOTE:
    The project spec requires units metadata validation,
    but does not define where the metadata lives.

    We therefore store it in config.yaml.
    """

    try:
        units = config["data"]["units"]

    except (KeyError, TypeError):

        return {
            "valid": False,
            "issues": [
                "data -> units section is missing from config"
            ]
        }

    issues = []

    # AppTorque is expected to be measured in Nm
    if units.get("AppTorque") != "Nm":

        issues.append(
            "AppTorque unit must be 'Nm'"
        )

    return {
        "valid": len(issues) == 0,
        "issues": issues
    }


def validate_data(df, config):
    """
    Run all Step 5 validation checks.

    This function DOES NOT modify the DataFrame.

    It only reports what it finds.
    """

    missing_values = check_missing_values(df)

    duplicate_timestamps = (
        check_duplicate_timestamps(df)
    )

    out_of_order_timestamps = (
        check_out_of_order_timestamps(df)
    )

    timestamp_gaps = (
        check_timestamp_gaps(df)
    )

    dtype_report = check_dtypes(df)

    units_report = check_units_metadata(config)

    # Determine whether any issue exists
    has_issues = (
        len(missing_values) > 0
        or duplicate_timestamps.get("count", 0) > 0
        or "error" in duplicate_timestamps
        or out_of_order_timestamps.get("count", 0) > 0
        or "error" in out_of_order_timestamps
        or timestamp_gaps.get("count", 0) > 0
        or "error" in timestamp_gaps
        or len(dtype_report["issues"]) > 0
        or not units_report["valid"]
    )

    return {
        "valid": not has_issues,

        "missing_values": missing_values,

        "timestamps": {
            "duplicates": duplicate_timestamps,
            "out_of_order": out_of_order_timestamps,
            "gaps": timestamp_gaps
        },

        "dtypes": dtype_report,

        "units": units_report
    }


if __name__ == "__main__":

    # Only used as a quick manual check.
    # Automated tests belong in tests/test_validation.py.

    from src.ingestion.loader import (
        load_config,
        load_pool
    )

    config = load_config("config.yaml")

    df = load_pool("sample")

    report = validate_data(
        df,
        config
    )

    print(report)