from datetime import (
    datetime,
    timedelta,
)
import json

import polars as pl
import pytest

from src.analytics.trend_analysis import (
    torque_trend,
)


def make_config(
    window_seconds=3,
):
    return {
        "analytics": {
            "drift_window_seconds": (
                window_seconds
            ),
        }
    }


def make_events(
    torques,
    spacing_seconds=1,
):
    start = datetime(
        2026,
        2,
        1,
        10,
        0,
        0,
    )

    timestamps = [
        start
        + timedelta(
            seconds=(
                index
                * spacing_seconds
            )
        )
        for index
        in range(
            len(torques)
        )
    ]

    return pl.DataFrame(
        {
            "ts": timestamps,
            "machine_id": [
                "M1"
                for _ in torques
            ],
            "head_id": [
                "H01"
                for _ in torques
            ],
            "torque": torques,
            "status": [
                0
                for _ in torques
            ],
            "error_class": [
                "Closure OK"
                for _ in torques
            ],
            "reject_signal": [
                False
                for _ in torques
            ],
            "cap_present": [
                True
                for _ in torques
            ],
        }
    )


def test_window_is_read_from_config():
    result = torque_trend(
        make_events(
            [
                1.0,
                2.0,
                3.0,
                4.0,
            ]
        ),
        make_config(
            window_seconds=3,
        ),
    )

    assert (
        result[
            "window_seconds"
        ]
        == 3
    )


def test_time_based_moving_average():
    result = torque_trend(
        make_events(
            [
                1.0,
                2.0,
                3.0,
                4.0,
            ]
        ),
        make_config(
            window_seconds=3,
        ),
    )

    assert result[
        "moving_average"
    ] == pytest.approx(
        [
            1.0,
            1.5,
            2.0,
            3.0,
        ]
    )


def test_moving_average_uses_timestamps_not_row_count():
    events = pl.DataFrame(
        {
            "ts": [
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
                    10,
                ),
            ],
            "torque": [
                1.0,
                3.0,
                10.0,
            ],
            "status": [
                0,
                0,
                0,
            ],
        }
    )

    result = torque_trend(
        events,
        make_config(
            window_seconds=3,
        ),
    )

    # At t=10 seconds, the observations at
    # t=0 and t=1 are outside the 3-second
    # trailing window.
    assert result[
        "moving_average"
    ][-1] == pytest.approx(
        10.0
    )


def test_upward_drift_fires():
    result = torque_trend(
        make_events(
            [
                1.0,
                2.0,
                3.0,
                4.0,
                5.0,
                6.0,
            ]
        ),
        make_config(
            window_seconds=4,
        ),
    )

    assert (
        result[
            "drift_detected"
        ]
        is True
    )

    assert (
        result[
            "drift_direction"
        ]
        == "upward"
    )

    assert (
        result[
            "drift_slope_per_second"
        ]
        > 0
    )


def test_flat_data_does_not_fire():
    result = torque_trend(
        make_events(
            [
                2.0,
                2.0,
                2.0,
                2.0,
                2.0,
                2.0,
            ]
        ),
        make_config(
            window_seconds=4,
        ),
    )

    assert (
        result[
            "drift_detected"
        ]
        is False
    )

    assert (
        result[
            "drift_direction"
        ]
        == "stable"
    )

    assert result[
        "drift_slope_per_second"
    ] == pytest.approx(
        0.0
    )


def test_downward_drift_is_identified():
    result = torque_trend(
        make_events(
            [
                6.0,
                5.0,
                4.0,
                3.0,
                2.0,
                1.0,
            ]
        ),
        make_config(
            window_seconds=4,
        ),
    )

    assert (
        result[
            "drift_detected"
        ]
        is True
    )

    assert (
        result[
            "drift_direction"
        ]
        == "downward"
    )

    assert (
        result[
            "drift_slope_per_second"
        ]
        < 0
    )


def test_lazyframe_input():
    result = torque_trend(
        make_events(
            [
                1.0,
                2.0,
                3.0,
            ]
        ).lazy(),
        make_config(),
    )

    assert (
        result[
            "sample_size"
        ]
        == 3
    )


def test_status_filter_is_supported():
    events = make_events(
        [
            1.0,
            100.0,
            2.0,
        ]
    ).with_columns(
        pl.Series(
            "status",
            [
                0,
                65,
                0,
            ],
        )
    )

    result = torque_trend(
        events,
        make_config(
            window_seconds=10,
        ),
        status_filter="successful",
    )

    assert (
        result[
            "sample_size"
        ]
        == 2
    )

    assert result[
        "moving_average"
    ][-1] == pytest.approx(
        1.5
    )


def test_empty_events_return_safe_result():
    events = pl.DataFrame(
        {
            "ts": [],
            "torque": [],
            "status": [],
        },
        schema={
            "ts": pl.Datetime(
                "us"
            ),
            "torque": pl.Float64,
            "status": pl.Int64,
        },
    )

    result = torque_trend(
        events,
        make_config(),
    )

    assert result == {
        "window_seconds": 3,
        "sample_size": 0,
        "timestamps": [],
        "moving_average": [],
        "drift_detected": False,
        "drift_direction": (
            "insufficient_data"
        ),
        "drift_slope_per_second": None,
    }


def test_single_event_has_insufficient_drift_data():
    result = torque_trend(
        make_events(
            [
                2.0,
            ]
        ),
        make_config(),
    )

    assert (
        result[
            "drift_detected"
        ]
        is False
    )

    assert (
        result[
            "drift_direction"
        ]
        == "insufficient_data"
    )

    assert (
        result[
            "drift_slope_per_second"
        ]
        is None
    )


def test_non_finite_torque_is_excluded():
    events = make_events(
        [
            1.0,
            float("nan"),
            float("inf"),
            2.0,
        ]
    )

    result = torque_trend(
        events,
        make_config(
            window_seconds=10,
        ),
    )

    assert (
        result[
            "sample_size"
        ]
        == 2
    )


def test_output_is_json_serializable():
    result = torque_trend(
        make_events(
            [
                1.0,
                2.0,
                3.0,
            ]
        ),
        make_config(),
    )

    encoded = json.dumps(
        result
    )

    assert isinstance(
        encoded,
        str,
    )

    assert all(
        isinstance(
            timestamp,
            str,
        )
        for timestamp
        in result[
            "timestamps"
        ]
    )

    assert all(
        type(value)
        is float
        for value
        in result[
            "moving_average"
        ]
    )


def test_missing_config_value_raises():
    with pytest.raises(
        ValueError,
        match=(
            "drift_window_seconds"
        ),
    ):
        torque_trend(
            make_events(
                [
                    1.0,
                    2.0,
                ]
            ),
            {},
        )


@pytest.mark.parametrize(
    "window",
    [
        0,
        -1,
    ],
)
def test_non_positive_window_raises(
    window,
):
    with pytest.raises(
        ValueError
    ):
        torque_trend(
            make_events(
                [
                    1.0,
                    2.0,
                ]
            ),
            make_config(
                window
            ),
        )


@pytest.mark.parametrize(
    "window",
    [
        3.5,
        "3600",
        True,
    ],
)
def test_invalid_window_type_raises(
    window,
):
    with pytest.raises(
        TypeError
    ):
        torque_trend(
            make_events(
                [
                    1.0,
                    2.0,
                ]
            ),
            make_config(
                window
            ),
        )