import polars as pl
import pytest

from src.analytics.capping_speed_polars import (
    incremental_average,
    closures_to_pieces_per_hour,
    running_capping_speed,
    running_capping_speed_frame,
)


# =========================================================
# INCREMENTAL AVERAGE
# =========================================================

def test_polars_incremental_average_matches_hand_calculation():

    values = [
        7200.0,
        10800.0,
        3600.0,
    ]

    running_mean = 0.0

    results = []

    for n, value in enumerate(
        values,
        start=1,
    ):

        running_mean = (
            incremental_average(
                running_mean,
                value,
                n,
            )
        )

        results.append(
            running_mean
        )

    assert results == [
        7200.0,
        9000.0,
        7200.0,
    ]


# =========================================================
# PIECES PER HOUR
# =========================================================

def test_polars_closures_are_converted_to_pieces_per_hour():

    speed = (
        closures_to_pieces_per_hour(
            closures=2,
            interval_seconds=1,
        )
    )

    assert speed == 7200.0


def test_polars_zero_interval_is_rejected():

    with pytest.raises(
        ValueError
    ):

        closures_to_pieces_per_hour(
            closures=2,
            interval_seconds=0,
        )


def test_polars_negative_interval_is_rejected():

    with pytest.raises(
        ValueError
    ):

        closures_to_pieces_per_hour(
            closures=2,
            interval_seconds=-1,
        )


# =========================================================
# LAZY PRODUCTION CONTRACT
# =========================================================

def test_polars_running_capping_speed_frame_stays_lazy():

    df = (
        pl.DataFrame({
            "closures": [
                2,
                3,
                1,
            ]
        })
        .lazy()
    )

    result = (
        running_capping_speed_frame(
            df,
            interval_seconds=1,
        )
    )

    assert isinstance(
        result,
        pl.LazyFrame,
    )


# =========================================================
# VECTORIZED SPEED CALCULATION
# =========================================================

def test_polars_running_capping_speed_frame_calculates_speeds():

    df = (
        pl.DataFrame({
            "closures": [
                2,
                3,
                1,
            ]
        })
        .lazy()
    )

    result = (
        running_capping_speed_frame(
            df,
            interval_seconds=1,
        )
        .collect()
    )

    assert (
        result[
            "pieces_per_hour"
        ].to_list()
        ==
        [
            7200.0,
            10800.0,
            3600.0,
        ]
    )

    assert (
        result[
            "running_mean"
        ].to_list()
        ==
        [
            7200.0,
            9000.0,
            7200.0,
        ]
    )


# =========================================================
# WRAPPER PARITY
# =========================================================

def test_polars_running_capping_speed_function():

    closures_per_interval = [
        2,
        3,
        1,
    ]

    result = (
        running_capping_speed(
            closures_per_interval,
            interval_seconds=1,
        )
    )

    assert result == [
        7200.0,
        9000.0,
        7200.0,
    ]


def test_polars_running_capping_speed_with_empty_input():

    result = (
        running_capping_speed(
            [],
            interval_seconds=1,
        )
    )

    assert result == []


def test_polars_running_capping_speed_rejects_zero_interval():

    with pytest.raises(
        ValueError
    ):

        running_capping_speed(
            [
                2,
                3,
                1,
            ],
            interval_seconds=0,
        )