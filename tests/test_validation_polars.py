from datetime import (
    datetime,
    timedelta,
)

import polars as pl

from src.ingestion.loader import (
    load_config,
)

from src.ingestion.validation_polars import (
    check_missing_values,
    check_duplicate_timestamps,
    check_out_of_order_timestamps,
    check_timestamp_gaps,
    check_dtypes,
    check_units_metadata,
    validate_data,
)


# =========================================================
# TEST DATA
# =========================================================

def make_clean_data():
    """
    Return fresh clean telemetry data for every test.

    Using fresh lists prevents one test from modifying
    another test's input.
    """

    return {
        "timestamp": [
            datetime(
                2026,
                2,
                1,
                10,
                0,
                0,
            ),
            datetime(
                2026,
                2,
                1,
                10,
                0,
                1,
            ),
            datetime(
                2026,
                2,
                1,
                10,
                0,
                2,
            ),
            datetime(
                2026,
                2,
                1,
                10,
                0,
                3,
            ),
            datetime(
                2026,
                2,
                1,
                10,
                0,
                4,
            ),
        ],

        "H01 Count": [
            100,
            101,
            102,
            103,
            104,
        ],

        "H01 AppTorque": [
            0.0,
            2.05,
            2.10,
            1.95,
            2.00,
        ],

        "H01 Status": [
            0,
            65,
            0,
            2,
            0,
        ],
    }


def make_clean_lazy_df():

    return (
        pl.DataFrame(
            make_clean_data()
        )
        .lazy()
    )


# =========================================================
# MISSING VALUES
# =========================================================

def test_polars_clean_data_has_no_missing_values():

    df = make_clean_lazy_df()

    result = check_missing_values(
        df
    )

    assert result == {}


def test_polars_missing_value_is_detected():

    data = make_clean_data()

    data[
        "H01 AppTorque"
    ][0] = None

    df = (
        pl.DataFrame(
            data
        )
        .lazy()
    )

    result = check_missing_values(
        df
    )

    assert result == {
        "H01 AppTorque": 1
    }


# =========================================================
# DUPLICATE TIMESTAMPS
# =========================================================

def test_polars_clean_data_has_no_duplicate_timestamps():

    df = make_clean_lazy_df()

    result = (
        check_duplicate_timestamps(
            df
        )
    )

    assert result["count"] == 0

    assert (
        result["timestamps"]
        == []
    )


def test_polars_duplicate_timestamp_is_detected():

    data = make_clean_data()

    # Row 1 repeats row 0.
    data[
        "timestamp"
    ][1] = data[
        "timestamp"
    ][0]

    df = (
        pl.DataFrame(
            data
        )
        .lazy()
    )

    result = (
        check_duplicate_timestamps(
            df
        )
    )

    assert result["count"] == 1

    assert len(
        result["timestamps"]
    ) == 1


# =========================================================
# OUT-OF-ORDER TIMESTAMPS
# =========================================================

def test_polars_clean_data_is_in_timestamp_order():

    df = make_clean_lazy_df()

    result = (
        check_out_of_order_timestamps(
            df
        )
    )

    assert result["count"] == 0

    assert result["rows"] == []


def test_polars_out_of_order_timestamp_is_detected():

    data = make_clean_data()

    # Row 2 occurs one second before row 1.
    data[
        "timestamp"
    ][2] = (
        data[
            "timestamp"
        ][1]
        -
        timedelta(
            seconds=1
        )
    )

    df = (
        pl.DataFrame(
            data
        )
        .lazy()
    )

    result = (
        check_out_of_order_timestamps(
            df
        )
    )

    assert result["count"] == 1

    assert len(
        result["rows"]
    ) == 1

    assert (
        result[
            "rows"
        ][0][
            "row_index"
        ]
        == 2
    )


# =========================================================
# TIMESTAMP GAPS
# =========================================================

def test_polars_clean_data_has_no_timestamp_gaps():

    df = make_clean_lazy_df()

    result = (
        check_timestamp_gaps(
            df
        )
    )

    assert result["count"] == 0

    assert result["rows"] == []


def test_polars_timestamp_gap_is_detected():

    data = make_clean_data()

    # Row 2 occurs five seconds after row 1.
    data[
        "timestamp"
    ][2] = (
        data[
            "timestamp"
        ][1]
        +
        timedelta(
            seconds=5
        )
    )

    df = (
        pl.DataFrame(
            data
        )
        .lazy()
    )

    result = (
        check_timestamp_gaps(
            df
        )
    )

    assert result["count"] == 1

    assert len(
        result["rows"]
    ) == 1

    assert (
        result[
            "rows"
        ][0][
            "row_index"
        ]
        == 2
    )

    assert (
        result[
            "rows"
        ][0][
            "gap_seconds"
        ]
        == 5.0
    )


# =========================================================
# DTYPE / VALUE-TYPE VALIDATION
# =========================================================

def test_polars_clean_data_has_valid_dtypes():

    df = make_clean_lazy_df()

    result = check_dtypes(
        df
    )

    assert result[
        "issues"
    ] == []


def test_polars_bad_count_value_is_detected():

    data = make_clean_data()

    # A decimal Count is invalid.
    data[
        "H01 Count"
    ][0] = 104085.5

    df = (
        pl.DataFrame(
            data
        )
        .lazy()
    )

    result = check_dtypes(
        df
    )

    assert any(
        issue[
            "column"
        ] == "H01 Count"

        for issue
        in result[
            "issues"
        ]
    )


def test_polars_bad_status_value_is_detected():

    data = make_clean_data()

    data[
        "H01 Status"
    ][0] = 2.5

    df = (
        pl.DataFrame(
            data
        )
        .lazy()
    )

    result = check_dtypes(
        df
    )

    assert any(
        issue[
            "column"
        ] == "H01 Status"

        for issue
        in result[
            "issues"
        ]
    )


def test_polars_bad_torque_dtype_is_detected():

    data = make_clean_data()

    # Convert the entire torque column to strings.
    data[
        "H01 AppTorque"
    ] = [
        str(value)
        for value
        in data[
            "H01 AppTorque"
        ]
    ]

    df = (
        pl.DataFrame(
            data
        )
        .lazy()
    )

    result = check_dtypes(
        df
    )

    assert any(
        issue[
            "column"
        ] == "H01 AppTorque"

        for issue
        in result[
            "issues"
        ]
    )


# =========================================================
# UNITS METADATA
# =========================================================

def test_polars_units_metadata_is_valid():

    config = load_config(
        "config.yaml"
    )

    result = (
        check_units_metadata(
            config
        )
    )

    assert (
        result["valid"]
        is True
    )

    assert (
        result["issues"]
        == []
    )


def test_polars_missing_units_metadata_is_detected():

    config = load_config(
        "config.yaml"
    )

    bad_config = (
        config.copy()
    )

    bad_config[
        "data"
    ] = (
        config[
            "data"
        ].copy()
    )

    bad_config[
        "data"
    ].pop(
        "units",
        None,
    )

    result = (
        check_units_metadata(
            bad_config
        )
    )

    assert (
        result["valid"]
        is False
    )


# =========================================================
# COMPLETE VALIDATION REPORT
# =========================================================

def test_polars_clean_data_validation_report():

    df = make_clean_lazy_df()

    config = load_config(
        "config.yaml"
    )

    report = validate_data(
        df,
        config,
    )

    assert (
        report["valid"]
        is True
    )

    assert (
        report[
            "missing_values"
        ]
        == {}
    )

    assert (
        report[
            "timestamps"
        ][
            "duplicates"
        ][
            "count"
        ]
        == 0
    )

    assert (
        report[
            "timestamps"
        ][
            "out_of_order"
        ][
            "count"
        ]
        == 0
    )

    assert (
        report[
            "timestamps"
        ][
            "gaps"
        ][
            "count"
        ]
        == 0
    )

    assert (
        report[
            "dtypes"
        ][
            "issues"
        ]
        == []
    )

    assert (
        report[
            "units"
        ][
            "valid"
        ]
        is True
    )


def test_polars_validation_reports_multiple_problems():

    data = make_clean_data()

    # Problem 1:
    # missing torque value
    data[
        "H01 AppTorque"
    ][0] = None

    # Problem 2:
    # duplicate timestamp
    data[
        "timestamp"
    ][2] = data[
        "timestamp"
    ][1]

    # Make Count a numeric floating-point column first.
    # Integer-like floats such as 100.0 are valid.
    data["H01 Count"] = [
        float(value)
        for value in data["H01 Count"]
    ]

    # Problem 3:
    # one Count is numeric but not integer-like
    data["H01 Count"][3] = 100.5

    df = (
        pl.DataFrame(
            data
        )
        .lazy()
    )

    config = load_config(
        "config.yaml"
    )

    report = validate_data(
        df,
        config,
    )

    assert (
        report["valid"]
        is False
    )

    assert (
        report[
            "missing_values"
        ][
            "H01 AppTorque"
        ]
        == 1
    )

    assert (
        report[
            "timestamps"
        ][
            "duplicates"
        ][
            "count"
        ]
        >= 1
    )

    assert len(
        report[
            "dtypes"
        ][
            "issues"
        ]
    ) >= 1