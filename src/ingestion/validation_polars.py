import polars as pl


def _as_lazy(df):
    """
    Normalize supported Polars input to a LazyFrame.

    The production pipeline works primarily with LazyFrame,
    but accepting DataFrame makes the validation functions
    easier to reuse and test.
    """

    if isinstance(df, pl.LazyFrame):
        return df

    if isinstance(df, pl.DataFrame):
        return df.lazy()

    raise TypeError(
        "df must be a Polars DataFrame or LazyFrame"
    )


def _has_datetime_timestamp(lazy_df):
    """
    Return True only when the timestamp column exists
    and has Polars Datetime dtype.
    """

    schema = lazy_df.collect_schema()

    if "timestamp" not in schema:
        return False

    return (
        schema["timestamp"].base_type()
        == pl.Datetime
    )


# =========================================================
# MISSING VALUES
# =========================================================

def check_missing_values(df):
    """
    Count missing values in each column.

    Returns an empty dictionary when no missing values exist.

    Both Polars null values and floating-point NaN values
    are considered missing so that behavior matches the
    pandas reference implementation.

    Example:
    {
        "H01 AppTorque": 2,
        "H05 Status": 1
    }
    """

    lazy_df = _as_lazy(df)

    schema = lazy_df.collect_schema()

    expressions = []

    for column, dtype in schema.items():

        missing_expression = (
            pl.col(column).is_null()
        )

        # pandas.isna() also considers NaN missing.
        # Only floating-point columns can contain NaN.
        if dtype.is_float():

            missing_expression = (
                missing_expression
                | pl.col(column).is_nan()
            )

        expressions.append(
            missing_expression
            .sum()
            .alias(column)
        )

    # Collect only the aggregated counts,
    # not the full telemetry table.
    counts = (
        lazy_df
        .select(expressions)
        .collect()
        .row(
            0,
            named=True
        )
    )

    return {
        column: int(count)
        for column, count in counts.items()
        if count > 0
    }


# =========================================================
# DUPLICATE TIMESTAMPS
# =========================================================

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

    lazy_df = _as_lazy(df)

    schema = lazy_df.collect_schema()

    if "timestamp" not in schema:

        return {
            "count": 0,
            "timestamps": [],
            "error": "timestamp column is missing"
        }

    # is_first_distinct() is True only for the first
    # occurrence of each timestamp.
    #
    # Negating it gives exactly the later repetitions,
    # matching pandas duplicated(keep="first").
    duplicate_rows = (
        lazy_df
        .filter(
            ~pl.col(
                "timestamp"
            ).is_first_distinct()
        )
        .select(
            "timestamp"
        )
        .collect()
    )

    duplicate_timestamps = (
        duplicate_rows[
            "timestamp"
        ].to_list()
    )

    return {
        "count": len(
            duplicate_timestamps
        ),

        "timestamps": [
            str(timestamp)
            for timestamp
            in duplicate_timestamps
        ]
    }


# =========================================================
# OUT-OF-ORDER TIMESTAMPS
# =========================================================

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

    lazy_df = _as_lazy(df)

    schema = lazy_df.collect_schema()

    if "timestamp" not in schema:

        return {
            "count": 0,
            "rows": [],
            "error": "timestamp column is missing"
        }

    if not _has_datetime_timestamp(
        lazy_df
    ):

        return {
            "count": 0,
            "rows": [],
            "error": "timestamp column is not datetime"
        }

    # Add the original row position before filtering.
    #
    # shift(1) gives the previous timestamp.
    problem_rows = (
        lazy_df
        .with_row_index(
            "__row_index"
        )
        .with_columns(
            pl.col(
                "timestamp"
            )
            .shift(1)
            .alias(
                "__previous_timestamp"
            )
        )
        .filter(
            pl.col(
                "__previous_timestamp"
            ).is_not_null()
            &
            (
                pl.col(
                    "timestamp"
                )
                <
                pl.col(
                    "__previous_timestamp"
                )
            )
        )
        .select(
            "__row_index",
            "__previous_timestamp",
            "timestamp",
        )
        .collect()
    )

    rows = []

    for row in problem_rows.iter_rows(
        named=True
    ):

        rows.append({
            "row_index": int(
                row["__row_index"]
            ),

            "previous_timestamp": str(
                row[
                    "__previous_timestamp"
                ]
            ),

            "current_timestamp": str(
                row["timestamp"]
            )
        })

    return {
        "count": len(rows),
        "rows": rows
    }


# =========================================================
# TIMESTAMP GAPS
# =========================================================

def check_timestamp_gaps(df):
    """
    Detect gaps larger than the expected
    one-second sampling interval.

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

    lazy_df = _as_lazy(df)

    schema = lazy_df.collect_schema()

    if "timestamp" not in schema:

        return {
            "count": 0,
            "rows": [],
            "error": "timestamp column is missing"
        }

    if not _has_datetime_timestamp(
        lazy_df
    ):

        return {
            "count": 0,
            "rows": [],
            "error": "timestamp column is not datetime"
        }

    problem_rows = (
        lazy_df
        .with_row_index(
            "__row_index"
        )
        .with_columns(
            pl.col(
                "timestamp"
            )
            .shift(1)
            .alias(
                "__previous_timestamp"
            )
        )
        .with_columns(
            (
                pl.col(
                    "timestamp"
                )
                -
                pl.col(
                    "__previous_timestamp"
                )
            )
            .alias(
                "__difference"
            )
        )
        .filter(
            pl.col(
                "__difference"
            )
            >
            pl.duration(
                seconds=1
            )
        )
        .select(
            "__row_index",
            "__previous_timestamp",
            "timestamp",

            (
                pl.col(
                    "__difference"
                )
                .dt
                .total_microseconds()
                .cast(
                    pl.Float64
                )
                /
                1_000_000.0
            )
            .alias(
                "__gap_seconds"
            ),
        )
        .collect()
    )

    rows = []

    for row in problem_rows.iter_rows(
        named=True
    ):

        rows.append({
            "row_index": int(
                row["__row_index"]
            ),

            "previous_timestamp": str(
                row[
                    "__previous_timestamp"
                ]
            ),

            "current_timestamp": str(
                row["timestamp"]
            ),

            "gap_seconds": float(
                row[
                    "__gap_seconds"
                ]
            )
        })

    return {
        "count": len(rows),
        "rows": rows
    }


# =========================================================
# DTYPE / VALUE-TYPE VALIDATION
# =========================================================

def check_dtypes(df):
    """
    Check expected telemetry data types.

    Rules:

    timestamp:
        must be Polars Datetime

    * Count:
        must be numeric and contain integer-like values

    * AppTorque:
        must be numeric

    * Status:
        must be numeric and contain integer-like values

    Missing values are ignored here because missing-value
    validation is handled separately.

    Returns:
    {
        "issues": [...]
    }
    """

    lazy_df = _as_lazy(df)

    schema = lazy_df.collect_schema()

    issues = []

    # -----------------------------------------------------
    # TIMESTAMP
    # -----------------------------------------------------

    if "timestamp" not in schema:

        issues.append({
            "column": "timestamp",
            "problem": "column is missing"
        })

    elif (
        schema[
            "timestamp"
        ].base_type()
        != pl.Datetime
    ):

        issues.append({
            "column": "timestamp",
            "problem": "expected datetime"
        })

    # -----------------------------------------------------
    # INTEGER-LIKE CHECKS
    # -----------------------------------------------------

    # These expressions are accumulated and evaluated
    # together so we do not perform one full dataset scan
    # for every Count or Status column.

    integer_checks = []

    check_metadata = []

    # -----------------------------------------------------
    # COUNT COLUMNS
    # -----------------------------------------------------

    count_columns = [
        column
        for column in schema.names()
        if column.endswith(
            " Count"
        )
    ]

    for column in count_columns:

        dtype = schema[column]

        if not dtype.is_numeric():

            issues.append({
                "column": column,
                "problem":
                    "expected numeric integer-like values"
            })

            continue

        valid_value = (
            pl.col(
                column
            ).is_not_null()
        )

        # NaN is handled by missing-value validation,
        # just like pandas dropna() in the reference.
        if dtype.is_float():

            valid_value = (
                valid_value
                &
                pl.col(
                    column
                ).is_not_nan()
            )

        alias = (
            f"__count_non_integer_"
            f"{len(integer_checks)}"
        )

        integer_checks.append(
            (
                valid_value
                &
                (
                    (
                        pl.col(column)
                        % 1
                    )
                    != 0
                )
            )
            .any()
            .fill_null(False)
            .alias(alias)
        )

        check_metadata.append({
            "alias": alias,
            "column": column,
            "problem":
                "contains non-integer Count values"
        })

    # -----------------------------------------------------
    # STATUS COLUMNS
    # -----------------------------------------------------

    status_columns = [
        column
        for column in schema.names()
        if column.endswith(
            " Status"
        )
    ]

    for column in status_columns:

        dtype = schema[column]

        if not dtype.is_numeric():

            issues.append({
                "column": column,
                "problem":
                    "expected numeric integer-like values"
            })

            continue

        valid_value = (
            pl.col(
                column
            ).is_not_null()
        )

        if dtype.is_float():

            valid_value = (
                valid_value
                &
                pl.col(
                    column
                ).is_not_nan()
            )

        alias = (
            f"__status_non_integer_"
            f"{len(integer_checks)}"
        )

        integer_checks.append(
            (
                valid_value
                &
                (
                    (
                        pl.col(column)
                        % 1
                    )
                    != 0
                )
            )
            .any()
            .fill_null(False)
            .alias(alias)
        )

        check_metadata.append({
            "alias": alias,
            "column": column,
            "problem":
                "contains non-integer Status values"
        })

    # Run all integer-like checks together.
    if integer_checks:

        results = (
            lazy_df
            .select(
                integer_checks
            )
            .collect()
            .row(
                0,
                named=True
            )
        )

        for metadata in check_metadata:

            if results[
                metadata["alias"]
            ]:

                issues.append({
                    "column":
                        metadata["column"],

                    "problem":
                        metadata["problem"]
                })

    # -----------------------------------------------------
    # TORQUE COLUMNS
    # -----------------------------------------------------

    torque_columns = [
        column
        for column in schema.names()
        if column.endswith(
            " AppTorque"
        )
    ]

    for column in torque_columns:

        if not schema[
            column
        ].is_numeric():

            issues.append({
                "column": column,
                "problem":
                    "expected numeric torque values"
            })

    return {
        "issues": issues
    }


# =========================================================
# UNITS METADATA
# =========================================================

def check_units_metadata(config):
    """
    Check that expected units metadata exists in config.

    Current project convention:

        AppTorque -> Nm
    """

    try:

        units = (
            config[
                "data"
            ][
                "units"
            ]
        )

    except (
        KeyError,
        TypeError,
    ):

        return {
            "valid": False,

            "issues": [
                "data -> units section "
                "is missing from config"
            ]
        }

    issues = []

    if units.get(
        "AppTorque"
    ) != "Nm":

        issues.append(
            "AppTorque unit must be 'Nm'"
        )

    return {
        "valid":
            len(issues) == 0,

        "issues":
            issues
    }


# =========================================================
# COMPLETE VALIDATION REPORT
# =========================================================

def validate_data(df, config):
    """
    Run all Step 5 Polars validation checks.

    This function DOES NOT modify the telemetry data.

    It only reports what it finds.
    """

    lazy_df = _as_lazy(df)

    missing_values = (
        check_missing_values(
            lazy_df
        )
    )

    duplicate_timestamps = (
        check_duplicate_timestamps(
            lazy_df
        )
    )

    out_of_order_timestamps = (
        check_out_of_order_timestamps(
            lazy_df
        )
    )

    timestamp_gaps = (
        check_timestamp_gaps(
            lazy_df
        )
    )

    dtype_report = (
        check_dtypes(
            lazy_df
        )
    )

    units_report = (
        check_units_metadata(
            config
        )
    )

    has_issues = (
        len(
            missing_values
        ) > 0

        or
        duplicate_timestamps.get(
            "count",
            0
        ) > 0

        or
        "error"
        in duplicate_timestamps

        or
        out_of_order_timestamps.get(
            "count",
            0
        ) > 0

        or
        "error"
        in out_of_order_timestamps

        or
        timestamp_gaps.get(
            "count",
            0
        ) > 0

        or
        "error"
        in timestamp_gaps

        or
        len(
            dtype_report[
                "issues"
            ]
        ) > 0

        or
        not units_report[
            "valid"
        ]
    )

    return {
        "valid":
            not has_issues,

        "missing_values":
            missing_values,

        "timestamps": {
            "duplicates":
                duplicate_timestamps,

            "out_of_order":
                out_of_order_timestamps,

            "gaps":
                timestamp_gaps,
        },

        "dtypes":
            dtype_report,

        "units":
            units_report,
    }