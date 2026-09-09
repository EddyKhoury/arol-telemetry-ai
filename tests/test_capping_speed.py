from src.analytics.capping_speed import (
    incremental_average,
    closures_to_pieces_per_hour,
    running_capping_speed,
)
import pytest
def test_incremental_average_matches_hand_calculation():

    values = [
        7200.0,
        10800.0,
        3600.0,
    ]

    running_mean = 0.0
    results = []

    for n, value in enumerate(values, start=1):
        running_mean = incremental_average(
            running_mean,
            value,
            n,
        )

        results.append(running_mean)

    assert results == [
        7200.0,
        9000.0,
        7200.0,
    ]

from src.analytics.capping_speed import (
    incremental_average,
    closures_to_pieces_per_hour,
)


def test_closures_are_converted_to_pieces_per_hour():
    speed = closures_to_pieces_per_hour(
        closures=2,
        interval_seconds=1,
    )

    assert speed == 7200.0

def test_zero_interval_is_rejected():
    with pytest.raises(ValueError):
        closures_to_pieces_per_hour(
            closures=2,
            interval_seconds=0,
        )

def test_running_capping_speed_updates_incrementally():

    closures_per_interval = [
        2,
        3,
        1,
    ]

    running_mean = 0.0
    running_speeds = []

    for n, closures in enumerate(closures_per_interval, start=1):

        speed = closures_to_pieces_per_hour(
            closures=closures,
            interval_seconds=1,
        )

        running_mean = incremental_average(
            running_mean,
            speed,
            n,
        )

        running_speeds.append(running_mean)

    assert running_speeds == [
        7200.0,
        9000.0,
        7200.0,
    ]

def test_running_capping_speed_function():

    closures_per_interval = [
        2,
        3,
        1,
    ]

    result = running_capping_speed(
        closures_per_interval,
        interval_seconds=1,
    )

    assert result == [
        7200.0,
        9000.0,
        7200.0,
    ]

def test_running_capping_speed_with_empty_input():
    result = running_capping_speed(
        [],
        interval_seconds=1,
    )

    assert result == []


def test_running_capping_speed_rejects_zero_interval():
    with pytest.raises(ValueError):
        running_capping_speed(
            [2, 3, 1],
            interval_seconds=0,
        )