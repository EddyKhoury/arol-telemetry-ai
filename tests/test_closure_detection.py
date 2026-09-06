import pandas as pd

from src.ingestion.closure_detection import detect_head_closures


def test_steady_count_produces_zero_closures():
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
            100,
            100,
        ],
        "H01 AppTorque": [
            0.0,
            0.0,
            0.0,
            0.0,
        ],
        "H01 Status": [
            0,
            0,
            0,
            0,
        ],
    })

    closures = detect_head_closures(
        df,
        "H01"
    )

    assert len(closures) == 0

def test_increment_by_one_produces_one_closure():
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
        "H01"
    )

    assert len(closures) == 1

    closure = closures[0]

    assert closure["row_index"] == 2
    assert closure["head_id"] == "H01"
    assert closure["torque"] == 2.05
    assert closure["status"] == 65

    assert closure["timestamp"] == pd.Timestamp(
        "2026-02-01 10:00:02"
    )

def test_first_row_does_not_create_a_closure():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-01 10:00:00",
            "2026-02-01 10:00:01",
        ]),
        "H01 Count": [
            500,
            500,
        ],
        "H01 AppTorque": [
            2.0,
            0.0,
        ],
        "H01 Status": [
            0,
            0,
        ],
    })

    closures = detect_head_closures(
        df,
        "H01"
    )

    assert len(closures) == 0

def test_status_change_without_count_increment_produces_no_closure():
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
            2.10,
            2.20,
        ],

        "H01 Status": [
            0,
            65,
            2,
        ],
    })

    closures = detect_head_closures(
        df,
        "H01"
    )

    assert len(closures) == 0

def test_count_jump_greater_than_one_produces_no_closure():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-01 10:00:00",
            "2026-02-01 10:00:01",
            "2026-02-01 10:00:02",
        ]),

        "H01 Count": [
            100,
            103,
            103,
        ],

        "H01 AppTorque": [
            0.0,
            2.05,
            0.0,
        ],

        "H01 Status": [
            0,
            65,
            0,
        ],
    })

    closures = detect_head_closures(
        df,
        "H01"
    )

    assert len(closures) == 0

def test_counter_reset_produces_no_spurious_closure():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-01 10:00:00",
            "2026-02-01 10:00:01",
            "2026-02-01 10:00:02",
        ]),

        "H01 Count": [
            1000,
            1001,
            5,
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
    })

    closures = detect_head_closures(
        df,
        "H01"
    )

    # 1000 -> 1001 is one real closure
    # 1001 -> 5 is a reset/decrease, so it must not create another one
    assert len(closures) == 1

    assert closures[0]["row_index"] == 1

def test_closure_across_stitched_file_boundary_is_detected():
    # Simulate the end of one file
    first_file = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-01 23:59:58",
            "2026-02-01 23:59:59",
        ]),
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

    # Simulate the beginning of the next file
    second_file = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-02-02 00:00:00",
            "2026-02-02 00:00:01",
        ]),
        "H01 Count": [
            101,
            101,
        ],
        "H01 AppTorque": [
            2.10,
            0.0,
        ],
        "H01 Status": [
            0,
            0,
        ],
    })

    # Simulate what load_pool() does:
    # combine both files into one continuous DataFrame
    df = pd.concat(
        [first_file, second_file],
        ignore_index=True
    )

    closures = detect_head_closures(
        df,
        "H01"
    )

    assert len(closures) == 1

    # The closure should be detected on the first row
    # of the second stitched file
    assert closures[0]["row_index"] == 2

    assert closures[0]["torque"] == 2.10
    assert closures[0]["status"] == 0

    assert closures[0]["timestamp"] == pd.Timestamp(
        "2026-02-02 00:00:00"
    )