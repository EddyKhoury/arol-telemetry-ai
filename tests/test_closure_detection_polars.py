from datetime import datetime

import polars as pl

from src.ingestion.closure_detection_polars import (
    detect_head_closures,
    detect_head_closures_frame,
)


def make_lazy_df(
    timestamps,
    counts,
    torques,
    statuses,
):
    """
    Build one-head telemetry as a Polars LazyFrame.
    """

    return (
        pl.DataFrame({
            "timestamp":
                timestamps,

            "H01 Count":
                counts,

            "H01 AppTorque":
                torques,

            "H01 Status":
                statuses,
        })
        .lazy()
    )


# =========================================================
# LAZY PRODUCTION CONTRACT
# =========================================================

def test_polars_closure_detection_stays_lazy():

    df = make_lazy_df(
        timestamps=[
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
        counts=[
            100,
            101,
        ],
        torques=[
            0.0,
            2.05,
        ],
        statuses=[
            0,
            65,
        ],
    )

    result = (
        detect_head_closures_frame(
            df,
            "H01",
        )
    )

    assert isinstance(
        result,
        pl.LazyFrame,
    )


# =========================================================
# STEADY COUNT
# =========================================================

def test_polars_steady_count_produces_zero_closures():

    df = make_lazy_df(
        timestamps=[
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
        counts=[
            100,
            100,
            100,
            100,
        ],
        torques=[
            0.0,
            0.0,
            0.0,
            0.0,
        ],
        statuses=[
            0,
            0,
            0,
            0,
        ],
    )

    closures = (
        detect_head_closures(
            df,
            "H01",
        )
    )

    assert len(
        closures
    ) == 0


# =========================================================
# EXACT +1 INCREMENT
# =========================================================

def test_polars_increment_by_one_produces_one_closure():

    df = make_lazy_df(
        timestamps=[
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
        counts=[
            100,
            100,
            101,
            101,
        ],
        torques=[
            0.0,
            0.0,
            2.05,
            0.0,
        ],
        statuses=[
            0,
            0,
            65,
            0,
        ],
    )

    closures = (
        detect_head_closures(
            df,
            "H01",
        )
    )

    assert len(
        closures
    ) == 1

    closure = (
        closures[0]
    )

    assert (
        closure[
            "row_index"
        ]
        == 2
    )

    assert (
        closure[
            "head_id"
        ]
        == "H01"
    )

    assert (
        closure[
            "torque"
        ]
        == 2.05
    )

    assert (
        closure[
            "status"
        ]
        == 65
    )

    assert (
        closure[
            "timestamp"
        ]
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


# =========================================================
# FIRST ROW
# =========================================================

def test_polars_first_row_does_not_create_a_closure():

    df = make_lazy_df(
        timestamps=[
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
        counts=[
            500,
            500,
        ],
        torques=[
            2.0,
            0.0,
        ],
        statuses=[
            0,
            0,
        ],
    )

    closures = (
        detect_head_closures(
            df,
            "H01",
        )
    )

    assert len(
        closures
    ) == 0


# =========================================================
# STATUS CHANGE WITHOUT COUNT INCREMENT
# =========================================================

def test_polars_status_change_without_count_increment_produces_no_closure():

    df = make_lazy_df(
        timestamps=[
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
        counts=[
            100,
            100,
            100,
        ],
        torques=[
            0.0,
            2.10,
            2.20,
        ],
        statuses=[
            0,
            65,
            2,
        ],
    )

    closures = (
        detect_head_closures(
            df,
            "H01",
        )
    )

    assert len(
        closures
    ) == 0


# =========================================================
# JUMP GREATER THAN ONE
# =========================================================

def test_polars_count_jump_greater_than_one_produces_no_closure():

    df = make_lazy_df(
        timestamps=[
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
        counts=[
            100,
            103,
            103,
        ],
        torques=[
            0.0,
            2.05,
            0.0,
        ],
        statuses=[
            0,
            65,
            0,
        ],
    )

    closures = (
        detect_head_closures(
            df,
            "H01",
        )
    )

    assert len(
        closures
    ) == 0


# =========================================================
# COUNTER RESET
# =========================================================

def test_polars_counter_reset_produces_no_spurious_closure():

    df = make_lazy_df(
        timestamps=[
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
        counts=[
            1000,
            1001,
            5,
        ],
        torques=[
            0.0,
            2.00,
            0.0,
        ],
        statuses=[
            0,
            0,
            0,
        ],
    )

    closures = (
        detect_head_closures(
            df,
            "H01",
        )
    )

    # 1000 -> 1001 is one closure.
    #
    # 1001 -> 5 is a reset/decrease and
    # must not create another closure.

    assert len(
        closures
    ) == 1

    assert (
        closures[0][
            "row_index"
        ]
        == 1
    )


# =========================================================
# STITCHED FILE BOUNDARY
# =========================================================

def test_polars_closure_across_stitched_file_boundary_is_detected():

    first_file = pl.DataFrame({
        "timestamp": [
            datetime(
                2026,
                2,
                1,
                23,
                59,
                58,
            ),
            datetime(
                2026,
                2,
                1,
                23,
                59,
                59,
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

    second_file = pl.DataFrame({
        "timestamp": [
            datetime(
                2026,
                2,
                2,
                0,
                0,
                0,
            ),
            datetime(
                2026,
                2,
                2,
                0,
                0,
                1,
            ),
        ],

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

    # Simulate the continuous dataset produced by
    # scan_parquet_pool().
    df = (
        pl.concat(
            [
                first_file,
                second_file,
            ],
            how="vertical",
        )
        .lazy()
    )

    closures = (
        detect_head_closures(
            df,
            "H01",
        )
    )

    assert len(
        closures
    ) == 1

    # First row of the second stitched file.
    assert (
        closures[0][
            "row_index"
        ]
        == 2
    )

    assert (
        closures[0][
            "torque"
        ]
        == 2.10
    )

    assert (
        closures[0][
            "status"
        ]
        == 0
    )

    assert (
        closures[0][
            "timestamp"
        ]
        ==
        datetime(
            2026,
            2,
            2,
            0,
            0,
            0,
        )
    )