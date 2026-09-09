import pandas as pd
import pytest

from src.ingestion.event_assembly import decode_status, assemble_event
from src.ingestion.closure_detection import detect_head_closures


def test_status_zero_decodes_to_closure_ok():
    decoded = decode_status(0)

    assert decoded["error_class"] == "Closure OK"
    assert decoded["reject_signal"] is False
    assert decoded["cap_present"] is True


def test_status_two_decodes_to_no_load():
    decoded = decode_status(2)

    assert decoded["error_class"] == "No Load"
    assert decoded["reject_signal"] is False
    assert decoded["cap_present"] is False


def test_status_65_decodes_to_bad_closure():
    decoded = decode_status(65)

    assert decoded["error_class"] == "Bad Closure"
    assert decoded["reject_signal"] is True
    assert decoded["cap_present"] is True


def test_unknown_status_is_flagged():
    decoded = decode_status(99)

    assert decoded["error_class"] == "Unknown (99)"
    assert decoded["reject_signal"] is None
    assert decoded["cap_present"] is None


@pytest.mark.parametrize(
    "status, expected_error_class, expected_reject",
    [
        (0, "Closure OK", False),
        (2, "No Load", False),
        (3, "No Load", True),
        (4, "No Closure", False),
        (5, "No Closure", True),
        (8, "No InTorque", False),
        (9, "No InTorque", True),
        (16, "No CapTurns", False),
        (17, "No CapTurns", True),
        (32, "Following Error", False),
        (33, "Following Error", True),
        (64, "Bad Closure", False),
        (65, "Bad Closure", True),
    ],
)
def test_all_known_status_codes_decode_correctly(
    status,
    expected_error_class,
    expected_reject,
):
    decoded = decode_status(status)

    assert decoded["error_class"] == expected_error_class
    assert decoded["reject_signal"] is expected_reject


def test_assemble_event_matches_event_schema():
    closure = {
        "row_index": 2,
        "head_id": "H01",
        "torque": 2.05,
        "status": 65,
        "timestamp": pd.Timestamp("2026-02-01 10:00:02"),
    }

    event = assemble_event(
        closure,
        machine_id="MCC777",
    )

    # Check that the event contains exactly the agreed schema fields.
    assert set(event.keys()) == {
        "ts",
        "machine_id",
        "head_id",
        "torque",
        "status",
        "error_class",
        "reject_signal",
        "cap_present",
    }

    # Check the values.
    assert event["ts"] == pd.Timestamp("2026-02-01 10:00:02")
    assert event["machine_id"] == "MCC777"
    assert event["head_id"] == "H01"
    assert event["torque"] == 2.05
    assert event["status"] == 65
    assert event["error_class"] == "Bad Closure"
    assert event["reject_signal"] is True
    assert event["cap_present"] is True

    # Check the expected value types.
    assert isinstance(event["ts"], pd.Timestamp)
    assert isinstance(event["machine_id"], str)
    assert isinstance(event["head_id"], str)
    assert isinstance(event["torque"], float)
    assert isinstance(event["status"], int)
    assert isinstance(event["error_class"], str)
    assert isinstance(event["reject_signal"], bool)
    assert isinstance(event["cap_present"], bool)


def test_event_keeps_timestamp_of_count_increment_row():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-01 10:00:00",
            "2026-02-01 10:00:01",
            "2026-02-01 10:00:02",
            "2026-02-01 10:00:03",
        ]),
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

    closures = detect_head_closures(
        df,
        "H01",
    )

    event = assemble_event(
        closures[0],
        machine_id="MCC777",
    )

    assert event["ts"] == pd.Timestamp(
        "2026-02-01 10:00:02"
    )