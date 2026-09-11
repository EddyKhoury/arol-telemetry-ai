from datetime import datetime

import polars as pl
import pytest

from src.ingestion.closure_detection_polars import (
    detect_head_closures_frame,
)

from src.ingestion.event_assembly_polars import (
    STATUS_MAP,
    EVENT_COLUMNS,
    decode_status,
    assemble_event,
    assemble_events_frame,
)


# =========================================================
# LAZY PRODUCTION CONTRACT
# =========================================================

def test_polars_event_assembly_stays_lazy():

    closures = (
        pl.DataFrame({
            "row_index": [
                1,
            ],
            "head_id": [
                "H01",
            ],
            "torque": [
                2.05,
            ],
            "status": [
                65,
            ],
            "timestamp": [
                datetime(
                    2026,
                    2,
                    1,
                    10,
                    0,
                    1,
                ),
            ],
        })
        .lazy()
    )

    events = (
        assemble_events_frame(
            closures,
            machine_id="MCC777",
        )
    )

    assert isinstance(
        events,
        pl.LazyFrame,
    )


# =========================================================
# INDIVIDUAL STATUS DECODING
# =========================================================

def test_polars_status_zero_decodes_to_closure_ok():

    decoded = decode_status(
        0
    )

    assert (
        decoded[
            "error_class"
        ]
        == "Closure OK"
    )

    assert (
        decoded[
            "reject_signal"
        ]
        is False
    )

    assert (
        decoded[
            "cap_present"
        ]
        is True
    )


def test_polars_status_two_decodes_to_no_load():

    decoded = decode_status(
        2
    )

    assert (
        decoded[
            "error_class"
        ]
        == "No Load"
    )

    assert (
        decoded[
            "reject_signal"
        ]
        is False
    )

    assert (
        decoded[
            "cap_present"
        ]
        is False
    )


def test_polars_status_65_decodes_to_bad_closure():

    decoded = decode_status(
        65
    )

    assert (
        decoded[
            "error_class"
        ]
        == "Bad Closure"
    )

    assert (
        decoded[
            "reject_signal"
        ]
        is True
    )

    assert (
        decoded[
            "cap_present"
        ]
        is True
    )


def test_polars_unknown_status_is_flagged():

    decoded = decode_status(
        99
    )

    assert (
        decoded[
            "error_class"
        ]
        == "Unknown (99)"
    )

    assert (
        decoded[
            "reject_signal"
        ]
        is None
    )

    assert (
        decoded[
            "cap_present"
        ]
        is None
    )


# =========================================================
# ALL KNOWN STATUS CODES
# =========================================================

@pytest.mark.parametrize(
    (
        "status,"
        "expected_error_class,"
        "expected_reject"
    ),
    [
        (
            0,
            "Closure OK",
            False,
        ),
        (
            2,
            "No Load",
            False,
        ),
        (
            3,
            "No Load",
            True,
        ),
        (
            4,
            "No Closure",
            False,
        ),
        (
            5,
            "No Closure",
            True,
        ),
        (
            8,
            "No InTorque",
            False,
        ),
        (
            9,
            "No InTorque",
            True,
        ),
        (
            16,
            "No CapTurns",
            False,
        ),
        (
            17,
            "No CapTurns",
            True,
        ),
        (
            32,
            "Following Error",
            False,
        ),
        (
            33,
            "Following Error",
            True,
        ),
        (
            64,
            "Bad Closure",
            False,
        ),
        (
            65,
            "Bad Closure",
            True,
        ),
    ],
)
def test_polars_all_known_status_codes_decode_correctly(
    status,
    expected_error_class,
    expected_reject,
):

    decoded = decode_status(
        status
    )

    assert (
        decoded[
            "error_class"
        ]
        == expected_error_class
    )

    assert (
        decoded[
            "reject_signal"
        ]
        is expected_reject
    )


# =========================================================
# SCALAR EVENT COMPATIBILITY
# =========================================================

def test_polars_assemble_event_matches_event_schema():

    closure = {
        "row_index": 2,
        "head_id": "H01",
        "torque": 2.05,
        "status": 65,
        "timestamp":
            datetime(
                2026,
                2,
                1,
                10,
                0,
                2,
            ),
    }

    event = assemble_event(
        closure,
        machine_id="MCC777",
    )

    assert list(
        event.keys()
    ) == EVENT_COLUMNS

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
        event[
            "machine_id"
        ]
        == "MCC777"
    )

    assert (
        event[
            "head_id"
        ]
        == "H01"
    )

    assert (
        event[
            "torque"
        ]
        == 2.05
    )

    assert (
        event[
            "status"
        ]
        == 65
    )

    assert (
        event[
            "error_class"
        ]
        == "Bad Closure"
    )

    assert (
        event[
            "reject_signal"
        ]
        is True
    )

    assert (
        event[
            "cap_present"
        ]
        is True
    )


# =========================================================
# VECTORIZED EVENT SCHEMA
# =========================================================

def test_polars_event_frame_matches_agreed_schema():

    closures = (
        pl.DataFrame({
            "row_index": [
                2,
            ],

            "head_id": [
                "H01",
            ],

            "torque": [
                2.05,
            ],

            "status": [
                65,
            ],

            "timestamp": [
                datetime(
                    2026,
                    2,
                    1,
                    10,
                    0,
                    2,
                ),
            ],
        })
        .lazy()
    )

    events = (
        assemble_events_frame(
            closures,
            machine_id="MCC777",
        )
        .collect()
    )

    assert (
        events.columns
        == EVENT_COLUMNS
    )

    schema = events.schema

    assert (
        schema[
            "ts"
        ].base_type()
        == pl.Datetime
    )

    assert (
        schema[
            "machine_id"
        ]
        == pl.String
    )

    assert (
        schema[
            "head_id"
        ]
        == pl.String
    )

    assert (
        schema[
            "torque"
        ]
        == pl.Float64
    )

    assert (
        schema[
            "status"
        ]
        == pl.Int64
    )

    assert (
        schema[
            "error_class"
        ]
        == pl.String
    )

    assert (
        schema[
            "reject_signal"
        ]
        == pl.Boolean
    )

    assert (
        schema[
            "cap_present"
        ]
        == pl.Boolean
    )


# =========================================================
# CLOSURE → EVENT TIMESTAMP INTEGRATION
# =========================================================

def test_polars_event_keeps_timestamp_of_count_increment_row():

    telemetry = (
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
                datetime(
                    2026,
                    2,
                    1,
                    10,
                    0,
                    3,
                ),
            ],

            "H01 Count": [
                100,
                100,
                101,
                101,
            ],

            "H01 AppTorque": [
                0.0,
                0.0,
                2.05,
                0.0,
            ],

            "H01 Status": [
                0,
                0,
                65,
                0,
            ],
        })
        .lazy()
    )

    closures = (
        detect_head_closures_frame(
            telemetry,
            "H01",
        )
    )

    events = (
        assemble_events_frame(
            closures,
            machine_id="MCC777",
        )
        .collect()
    )

    assert events.height == 1

    event = (
        events.row(
            0,
            named=True,
        )
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
        event[
            "torque"
        ]
        == 2.05
    )

    assert (
        event[
            "status"
        ]
        == 65
    )

    assert (
        event[
            "error_class"
        ]
        == "Bad Closure"
    )


# =========================================================
# VECTORIZED STATUS DECODING
# =========================================================

def test_polars_vectorized_status_decoding_handles_known_and_unknown_codes():

    closures = (
        pl.DataFrame({
            "row_index": [
                1,
                2,
                3,
                4,
            ],

            "head_id": [
                "H01",
                "H01",
                "H01",
                "H01",
            ],

            "torque": [
                2.00,
                0.00,
                2.05,
                1.50,
            ],

            "status": [
                0,
                2,
                65,
                99,
            ],

            "timestamp": [
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
        })
        .lazy()
    )

    events = (
        assemble_events_frame(
            closures,
            machine_id="MCC777",
        )
        .collect()
    )

    rows = {
        row["status"]: row
        for row
        in events.iter_rows(
            named=True
        )
    }

    # -----------------------------------------------------
    # STATUS 0
    # -----------------------------------------------------

    assert (
        rows[0][
            "error_class"
        ]
        == "Closure OK"
    )

    assert (
        rows[0][
            "reject_signal"
        ]
        is False
    )

    assert (
        rows[0][
            "cap_present"
        ]
        is True
    )

    # -----------------------------------------------------
    # STATUS 2
    # -----------------------------------------------------

    assert (
        rows[2][
            "error_class"
        ]
        == "No Load"
    )

    assert (
        rows[2][
            "reject_signal"
        ]
        is False
    )

    assert (
        rows[2][
            "cap_present"
        ]
        is False
    )

    # -----------------------------------------------------
    # STATUS 65
    # -----------------------------------------------------

    assert (
        rows[65][
            "error_class"
        ]
        == "Bad Closure"
    )

    assert (
        rows[65][
            "reject_signal"
        ]
        is True
    )

    assert (
        rows[65][
            "cap_present"
        ]
        is True
    )

    # -----------------------------------------------------
    # UNKNOWN STATUS
    # -----------------------------------------------------

    assert (
        rows[99][
            "error_class"
        ]
        == "Unknown (99)"
    )

    assert (
        rows[99][
            "reject_signal"
        ]
        is None
    )

    assert (
        rows[99][
            "cap_present"
        ]
        is None
    )


# =========================================================
# STATUS MAP COMPLETENESS
# =========================================================

def test_polars_status_map_contains_all_expected_codes():

    assert set(
        STATUS_MAP.keys()
    ) == {
        0,
        2,
        3,
        4,
        5,
        8,
        9,
        16,
        17,
        32,
        33,
        64,
        65,
    }