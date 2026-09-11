import pandas as pd

from pandas.api.types import (
    is_datetime64_any_dtype,
    is_float_dtype,
    is_integer_dtype,
    is_bool_dtype,
)

from src.ingestion.event_table import detect_head_ids, build_event_table


def test_head_ids_are_auto_detected():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-01 10:00:00",
        ]),
        "H01 Count": [100],
        "H01 AppTorque": [0.0],
        "H01 Status": [0],
        "H02 Count": [200],
        "H02 AppTorque": [0.0],
        "H02 Status": [0],
    })

    head_ids = detect_head_ids(df)

    assert head_ids == [
        "H01",
        "H02",
    ]


def test_head_detection_does_not_assume_36_heads():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-01 10:00:00",
        ]),
        "H01 Count": [100],
        "H01 AppTorque": [0.0],
        "H01 Status": [0],
        "H02 Count": [200],
        "H02 AppTorque": [0.0],
        "H02 Status": [0],
        "H03 Count": [300],
        "H03 AppTorque": [0.0],
        "H03 Status": [0],
    })

    head_ids = detect_head_ids(df)

    assert head_ids == [
        "H01",
        "H02",
        "H03",
    ]


def test_no_closures_returns_empty_event_table_with_schema():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-01 10:00:00",
            "2026-02-01 10:00:01",
            "2026-02-01 10:00:02",
        ]),
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

    event_table = build_event_table(
        df,
        machine_id="MCC777",
    )

    assert len(event_table) == 0

    assert list(event_table.columns) == [
        "ts",
        "machine_id",
        "head_id",
        "torque",
        "status",
        "error_class",
        "reject_signal",
        "cap_present",
    ]


def test_one_closure_produces_one_event_row():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-01 10:00:00",
            "2026-02-01 10:00:01",
            "2026-02-01 10:00:02",
        ]),
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

    event_table = build_event_table(
        df,
        machine_id="MCC777",
    )

    assert len(event_table) == 1

    event = event_table.iloc[0]

    assert event["ts"] == pd.Timestamp("2026-02-01 10:00:02")
    assert event["machine_id"] == "MCC777"
    assert event["head_id"] == "H01"
    assert event["torque"] == 2.05
    assert event["status"] == 65
    assert event["error_class"] == "Bad Closure"
    assert event["reject_signal"] == True
    assert event["cap_present"] == True


def test_multiple_heads_produce_multiple_event_rows():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-01 10:00:00",
            "2026-02-01 10:00:01",
            "2026-02-01 10:00:02",
        ]),

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

    event_table = build_event_table(
        df,
        machine_id="MCC777",
    )

    assert len(event_table) == 2

    assert set(event_table["head_id"]) == {
        "H01",
        "H02",
    }


def test_event_table_is_sorted_chronologically():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-01 10:00:00",
            "2026-02-01 10:00:01",
            "2026-02-01 10:00:02",
        ]),

        # H01 closes later
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

        # H02 closes earlier
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

    event_table = build_event_table(
        df,
        machine_id="MCC777",
    )

    assert list(event_table["ts"]) == [
        pd.Timestamp("2026-02-01 10:00:01"),
        pd.Timestamp("2026-02-01 10:00:02"),
    ]

    assert list(event_table["head_id"]) == [
        "H02",
        "H01",
    ]


def test_same_timestamp_different_heads_are_both_kept():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-01 10:00:00",
            "2026-02-01 10:00:01",
        ]),

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

    event_table = build_event_table(
        df,
        machine_id="MCC777",
    )

    assert len(event_table) == 2

    assert list(event_table["head_id"]) == [
        "H01",
        "H02",
    ]

    assert list(event_table["ts"]) == [
        pd.Timestamp("2026-02-01 10:00:01"),
        pd.Timestamp("2026-02-01 10:00:01"),
    ]


def test_event_table_is_deterministic():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-01 10:00:00",
            "2026-02-01 10:00:01",
            "2026-02-01 10:00:02",
        ]),

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

    first = build_event_table(
        df,
        machine_id="MCC777",
    )

    second = build_event_table(
        df,
        machine_id="MCC777",
    )

    pd.testing.assert_frame_equal(
        first,
        second,
    )


def test_event_table_has_expected_types():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-01 10:00:00",
            "2026-02-01 10:00:01",
        ]),
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

    event_table = build_event_table(
        df,
        machine_id="MCC777",
    )

    # Check pandas column data types.
    assert is_datetime64_any_dtype(event_table["ts"])
    assert is_float_dtype(event_table["torque"])
    assert is_integer_dtype(event_table["status"])
    assert is_bool_dtype(event_table["reject_signal"])
    assert is_bool_dtype(event_table["cap_present"])

    # Check text columns contain strings.
    assert event_table["machine_id"].map(
        lambda value: isinstance(value, str)
    ).all()

    assert event_table["head_id"].map(
        lambda value: isinstance(value, str)
    ).all()

    assert event_table["error_class"].map(
        lambda value: isinstance(value, str)
    ).all()