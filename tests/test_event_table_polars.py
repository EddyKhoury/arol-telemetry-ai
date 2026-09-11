from datetime import datetime

import polars as pl

from polars.testing import (
    assert_frame_equal,
)

from src.ingestion.event_table_polars import (
    EVENT_COLUMNS,
    EVENT_SCHEMA,
    detect_head_ids,
    build_event_table,
    build_event_table_frame,
    write_event_table_parquet,
)


# =========================================================
# HEAD DETECTION
# =========================================================

def test_polars_head_ids_are_auto_detected():

    df = (
        pl.DataFrame({
            "timestamp": [
                datetime(
                    2026,
                    2,
                    1,
                    10,
                    0,
                    0,
                ),
            ],

            "H01 Count": [
                100,
            ],

            "H01 AppTorque": [
                0.0,
            ],

            "H01 Status": [
                0,
            ],

            "H02 Count": [
                200,
            ],

            "H02 AppTorque": [
                0.0,
            ],

            "H02 Status": [
                0,
            ],
        })
        .lazy()
    )

    head_ids = detect_head_ids(
        df
    )

    assert head_ids == [
        "H01",
        "H02",
    ]


def test_polars_head_detection_does_not_assume_36_heads():

    df = (
        pl.DataFrame({
            "timestamp": [
                datetime(
                    2026,
                    2,
                    1,
                    10,
                    0,
                    0,
                ),
            ],

            "H01 Count": [
                100,
            ],
            "H01 AppTorque": [
                0.0,
            ],
            "H01 Status": [
                0,
            ],

            "H02 Count": [
                200,
            ],
            "H02 AppTorque": [
                0.0,
            ],
            "H02 Status": [
                0,
            ],

            "H03 Count": [
                300,
            ],
            "H03 AppTorque": [
                0.0,
            ],
            "H03 Status": [
                0,
            ],
        })
        .lazy()
    )

    head_ids = detect_head_ids(
        df
    )

    assert head_ids == [
        "H01",
        "H02",
        "H03",
    ]


# =========================================================
# LAZY PRODUCTION CONTRACT
# =========================================================

def test_polars_event_table_stays_lazy():

    df = (
        pl.DataFrame({
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
        })
        .lazy()
    )

    events = build_event_table_frame(
        df,
        machine_id="MCC777",
    )

    assert isinstance(
        events,
        pl.LazyFrame,
    )


# =========================================================
# EMPTY EVENT TABLE
# =========================================================

def test_polars_no_closures_returns_empty_event_table_with_schema():

    df = (
        pl.DataFrame({
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
            ],

            "H01 Count": [
                100,
                100,
                100,
            ],

            "H01 AppTorque": [
                0.0,
                0.0,
                0.0,
            ],

            "H01 Status": [
                0,
                0,
                0,
            ],
        })
        .lazy()
    )

    events = build_event_table(
        df,
        machine_id="MCC777",
    )

    assert events.height == 0

    assert (
        events.columns
        == EVENT_COLUMNS
    )

    assert (
        events.schema
        == EVENT_SCHEMA
    )


# =========================================================
# ONE CLOSURE
# =========================================================

def test_polars_one_closure_produces_one_event_row():

    df = (
        pl.DataFrame({
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
            ],

            "H01 Count": [
                100,
                100,
                101,
            ],

            "H01 AppTorque": [
                0.0,
                0.0,
                2.05,
            ],

            "H01 Status": [
                0,
                0,
                65,
            ],
        })
        .lazy()
    )

    events = build_event_table(
        df,
        machine_id="MCC777",
    )

    assert events.height == 1

    event = events.row(
        0,
        named=True,
    )

    assert (
        event["ts"]
        ==
        datetime(
            2026,
            2,
            1,
            10,
            0,
            2,
        )
    )

    assert (
        event["machine_id"]
        == "MCC777"
    )

    assert (
        event["head_id"]
        == "H01"
    )

    assert (
        event["torque"]
        == 2.05
    )

    assert (
        event["status"]
        == 65
    )

    assert (
        event["error_class"]
        == "Bad Closure"
    )

    assert (
        event["reject_signal"]
        is True
    )

    assert (
        event["cap_present"]
        is True
    )


# =========================================================
# MULTIPLE HEADS
# =========================================================

def test_polars_multiple_heads_produce_multiple_event_rows():

    df = (
        pl.DataFrame({
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
            ],

            "H01 Count": [
                100,
                101,
                101,
            ],

            "H01 AppTorque": [
                0.0,
                2.00,
                0.0,
            ],

            "H01 Status": [
                0,
                0,
                0,
            ],

            "H02 Count": [
                200,
                200,
                201,
            ],

            "H02 AppTorque": [
                0.0,
                0.0,
                2.20,
            ],

            "H02 Status": [
                0,
                0,
                65,
            ],
        })
        .lazy()
    )

    events = build_event_table(
        df,
        machine_id="MCC777",
    )

    assert events.height == 2

    assert set(
        events[
            "head_id"
        ].to_list()
    ) == {
        "H01",
        "H02",
    }


# =========================================================
# CHRONOLOGICAL SORTING
# =========================================================

def test_polars_event_table_is_sorted_chronologically():

    df = (
        pl.DataFrame({
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
            ],

            # H01 closes later.
            "H01 Count": [
                100,
                100,
                101,
            ],

            "H01 AppTorque": [
                0.0,
                0.0,
                2.10,
            ],

            "H01 Status": [
                0,
                0,
                0,
            ],

            # H02 closes earlier.
            "H02 Count": [
                200,
                201,
                201,
            ],

            "H02 AppTorque": [
                0.0,
                2.20,
                0.0,
            ],

            "H02 Status": [
                0,
                65,
                0,
            ],
        })
        .lazy()
    )

    events = build_event_table(
        df,
        machine_id="MCC777",
    )

    assert (
        events[
            "ts"
        ].to_list()
        ==
        [
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
        ]
    )

    assert (
        events[
            "head_id"
        ].to_list()
        ==
        [
            "H02",
            "H01",
        ]
    )


# =========================================================
# SAME TIMESTAMP / DIFFERENT HEADS
# =========================================================

def test_polars_same_timestamp_different_heads_are_both_kept():

    df = (
        pl.DataFrame({
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
            ],

            "H01 Count": [
                100,
                101,
            ],

            "H01 AppTorque": [
                0.0,
                2.10,
            ],

            "H01 Status": [
                0,
                0,
            ],

            "H02 Count": [
                200,
                201,
            ],

            "H02 AppTorque": [
                0.0,
                2.20,
            ],

            "H02 Status": [
                0,
                65,
            ],
        })
        .lazy()
    )

    events = build_event_table(
        df,
        machine_id="MCC777",
    )

    assert events.height == 2

    assert (
        events[
            "head_id"
        ].to_list()
        ==
        [
            "H01",
            "H02",
        ]
    )

    assert (
        events[
            "ts"
        ].to_list()
        ==
        [
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
                1,
            ),
        ]
    )


# =========================================================
# DETERMINISM
# =========================================================

def test_polars_event_table_is_deterministic():

    df = (
        pl.DataFrame({
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
            ],

            "H01 Count": [
                100,
                101,
                101,
            ],

            "H01 AppTorque": [
                0.0,
                2.10,
                0.0,
            ],

            "H01 Status": [
                0,
                0,
                0,
            ],

            "H02 Count": [
                200,
                200,
                201,
            ],

            "H02 AppTorque": [
                0.0,
                0.0,
                2.20,
            ],

            "H02 Status": [
                0,
                0,
                65,
            ],
        })
        .lazy()
    )

    first = build_event_table(
        df,
        machine_id="MCC777",
    )

    second = build_event_table(
        df,
        machine_id="MCC777",
    )

    assert_frame_equal(
        first,
        second,
    )


# =========================================================
# FINAL DTYPES
# =========================================================

def test_polars_event_table_has_expected_types():

    df = (
        pl.DataFrame({
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
        })
        .lazy()
    )

    events = build_event_table(
        df,
        machine_id="MCC777",
    )

    assert (
        events.schema
        == EVENT_SCHEMA
    )


# =========================================================
# EVENT PARQUET ROUND TRIP
# =========================================================

def test_polars_event_table_parquet_round_trip(
    tmp_path
):

    df = (
        pl.DataFrame({
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
        })
        .lazy()
    )

    events = build_event_table_frame(
        df,
        machine_id="MCC777",
    )

    parquet_path = (
        tmp_path
        /
        "events.parquet"
    )

    returned_path = (
        write_event_table_parquet(
            events,
            parquet_path,
        )
    )

    assert returned_path == parquet_path
    assert parquet_path.exists()

    actual = pl.read_parquet(
        parquet_path
    )

    expected = (
        events
        .collect()
    )

    assert_frame_equal(
        actual,
        expected,
    )


# =========================================================
# EMPTY EVENT PARQUET
# =========================================================

def test_polars_empty_event_table_parquet_preserves_schema(
    tmp_path
):

    df = (
        pl.DataFrame({
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
            ],

            "H01 Count": [
                100,
                100,
            ],

            "H01 AppTorque": [
                0.0,
                0.0,
            ],

            "H01 Status": [
                0,
                0,
            ],
        })
        .lazy()
    )

    events = build_event_table_frame(
        df,
        machine_id="MCC777",
    )

    parquet_path = (
        tmp_path
        /
        "empty_events.parquet"
    )

    write_event_table_parquet(
        events,
        parquet_path,
    )

    restored = pl.read_parquet(
        parquet_path
    )

    assert restored.height == 0

    assert (
        restored.columns
        == EVENT_COLUMNS
    )

    assert (
        restored.schema
        == EVENT_SCHEMA
    )