from datetime import (
    datetime,
    timedelta,
)
import json

import polars as pl
import pytest

from src.analytics.anomaly_detection import (
    detect_torque_anomalies,
)


def make_config(
    expected_min=1.5,
    expected_max=2.5,
    sigma=3.0,
):
    return {
        "analytics": {
            "torque_expected_min": (
                expected_min
            ),
            "torque_expected_max": (
                expected_max
            ),
            "anomaly_sigma": sigma,
        }
    }


def make_events(
    torques,
    statuses=None,
):
    start = datetime(
        2026,
        2,
        1,
        10,
        0,
        0,
    )

    if statuses is None:
        statuses = [
            0
            for _ in torques
        ]

    return pl.DataFrame(
        {
            "ts": [
                start
                + timedelta(
                    seconds=index
                )
                for index
                in range(
                    len(torques)
                )
            ],
            "machine_id": [
                "M1"
                for _ in torques
            ],
            "head_id": [
                "H01"
                for _ in torques
            ],
            "torque": torques,
            "status": statuses,
        }
    )


def test_below_expected_min_is_detected():
    result = detect_torque_anomalies(
        make_events(
            [
                1.4,
                2.0,
            ]
        ),
        make_config(),
    )

    assert (
        result[
            "anomaly_count"
        ]
        == 1
    )

    assert (
        result[
            "anomalies"
        ][0]["torque"]
        == pytest.approx(
            1.4
        )
    )

    assert (
        "below_expected_min"
        in result[
            "anomalies"
        ][0]["reason"]
    )


def test_above_expected_max_is_detected():
    result = detect_torque_anomalies(
        make_events(
            [
                2.0,
                2.6,
            ]
        ),
        make_config(),
    )

    assert (
        result[
            "anomaly_count"
        ]
        == 1
    )

    assert (
        "above_expected_max"
        in result[
            "anomalies"
        ][0]["reason"]
    )


def test_exact_threshold_boundaries_are_not_anomalies():
    result = detect_torque_anomalies(
        make_events(
            [
                1.5,
                2.5,
            ]
        ),
        make_config(),
    )

    assert (
        result[
            "anomaly_count"
        ]
        == 0
    )


def test_thresholds_come_from_config():
    events = make_events(
        [
            1.4,
        ]
    )

    strict_result = (
        detect_torque_anomalies(
            events,
            make_config(
                expected_min=1.5,
            ),
        )
    )

    relaxed_result = (
        detect_torque_anomalies(
            events,
            make_config(
                expected_min=1.0,
            ),
        )
    )

    assert (
        strict_result[
            "anomaly_count"
        ]
        == 1
    )

    assert (
        relaxed_result[
            "anomaly_count"
        ]
        == 0
    )


def test_statistical_deviation_is_detected():
    torques = (
        [
            2.0
            for _ in range(
                20
            )
        ]
        + [
            5.0
        ]
    )

    result = detect_torque_anomalies(
        make_events(
            torques
        ),
        make_config(
            expected_min=-100.0,
            expected_max=100.0,
            sigma=3.0,
        ),
    )

    assert (
        result[
            "anomaly_count"
        ]
        == 1
    )

    anomaly = result[
        "anomalies"
    ][0]

    assert (
        anomaly["torque"]
        == pytest.approx(
            5.0
        )
    )

    assert (
        "statistical_deviation"
        in anomaly["reason"]
    )

    assert (
        anomaly["z_score"]
        > 3.0
    )


def test_reason_is_attached_to_every_anomaly():
    result = detect_torque_anomalies(
        make_events(
            [
                1.0,
                2.0,
                3.0,
            ]
        ),
        make_config(),
    )

    assert (
        result[
            "anomaly_count"
        ]
        == 2
    )

    assert all(
        isinstance(
            anomaly["reason"],
            str,
        )
        and anomaly["reason"]
        for anomaly
        in result[
            "anomalies"
        ]
    )


def test_multiple_reasons_can_be_attached():
    torques = (
        [
            2.0
            for _ in range(
                20
            )
        ]
        + [
            5.0
        ]
    )

    result = detect_torque_anomalies(
        make_events(
            torques
        ),
        make_config(
            expected_min=1.5,
            expected_max=2.5,
            sigma=3.0,
        ),
    )

    anomaly = result[
        "anomalies"
    ][0]

    assert (
        "above_expected_max"
        in anomaly["reason"]
    )

    assert (
        "statistical_deviation"
        in anomaly["reason"]
    )


def test_planted_anomalies_detected_and_false_positive_rate_measured():
    clean_torques = [
        1.9,
        2.0,
        2.1,
        2.0,
        1.95,
        2.05,
        2.0,
        2.1,
        1.9,
        2.0,
    ]

    planted_torques = [
        1.0,
        3.0,
    ]

    torques = (
        clean_torques
        + planted_torques
    )

    result = detect_torque_anomalies(
        make_events(
            torques
        ),
        make_config(),
    )

    detected_torques = [
        anomaly["torque"]
        for anomaly
        in result[
            "anomalies"
        ]
    ]

    true_positives = sum(
        torque
        in planted_torques
        for torque
        in detected_torques
    )

    false_positives = sum(
        torque
        not in planted_torques
        for torque
        in detected_torques
    )

    false_positive_rate = (
        false_positives
        / len(
            clean_torques
        )
    )

    assert true_positives == 2

    assert false_positives == 0

    assert (
        false_positive_rate
        == pytest.approx(
            0.0
        )
    )


def test_no_anomalies_returns_empty_list():
    result = detect_torque_anomalies(
        make_events(
            [
                1.9,
                2.0,
                2.1,
            ]
        ),
        make_config(),
    )

    assert (
        result[
            "anomaly_count"
        ]
        == 0
    )

    assert (
        result[
            "anomalies"
        ]
        == []
    )


def test_zero_standard_deviation_does_not_create_false_anomalies():
    result = detect_torque_anomalies(
        make_events(
            [
                2.0,
                2.0,
                2.0,
                2.0,
            ]
        ),
        make_config(),
    )

    assert (
        result[
            "std"
        ]
        == pytest.approx(
            0.0
        )
    )

    assert (
        result[
            "anomaly_count"
        ]
        == 0
    )


def test_status_filter_is_supported():
    events = make_events(
        [
            2.0,
            10.0,
            2.1,
        ],
        statuses=[
            0,
            65,
            0,
        ],
    )

    result = detect_torque_anomalies(
        events,
        make_config(),
        status_filter="successful",
    )

    assert (
        result[
            "sample_size"
        ]
        == 2
    )

    assert (
        result[
            "anomaly_count"
        ]
        == 0
    )


def test_lazyframe_input():
    result = detect_torque_anomalies(
        make_events(
            [
                1.0,
                2.0,
            ]
        ).lazy(),
        make_config(),
    )

    assert (
        result[
            "sample_size"
        ]
        == 2
    )

    assert (
        result[
            "anomaly_count"
        ]
        == 1
    )


def test_non_finite_torques_are_excluded():
    result = detect_torque_anomalies(
        make_events(
            [
                2.0,
                None,
                float("nan"),
                float("inf"),
                2.1,
            ]
        ),
        make_config(),
    )

    assert (
        result[
            "sample_size"
        ]
        == 2
    )


def test_empty_input_returns_safe_result():
    events = pl.DataFrame(
        {
            "ts": [],
            "machine_id": [],
            "head_id": [],
            "torque": [],
            "status": [],
        },
        schema={
            "ts": pl.Datetime(
                "us"
            ),
            "machine_id": (
                pl.String
            ),
            "head_id": pl.String,
            "torque": pl.Float64,
            "status": pl.Int64,
        },
    )

    result = detect_torque_anomalies(
        events,
        make_config(),
    )

    assert (
        result[
            "sample_size"
        ]
        == 0
    )

    assert (
        result[
            "anomaly_count"
        ]
        == 0
    )

    assert (
        result[
            "anomaly_rate"
        ]
        == 0.0
    )

    assert (
        result[
            "anomalies"
        ]
        == []
    )


def test_output_is_json_serializable():
    result = detect_torque_anomalies(
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


def test_missing_config_raises():
    with pytest.raises(
        ValueError,
        match="anomaly",
    ):
        detect_torque_anomalies(
            make_events(
                [
                    2.0,
                ]
            ),
            {},
        )


def test_expected_min_greater_than_max_raises():
    with pytest.raises(
        ValueError
    ):
        detect_torque_anomalies(
            make_events(
                [
                    2.0,
                ]
            ),
            make_config(
                expected_min=3.0,
                expected_max=1.0,
            ),
        )


@pytest.mark.parametrize(
    "sigma",
    [
        0,
        -1,
    ],
)
def test_non_positive_sigma_raises(
    sigma,
):
    with pytest.raises(
        ValueError
    ):
        detect_torque_anomalies(
            make_events(
                [
                    2.0,
                ]
            ),
            make_config(
                sigma=sigma,
            ),
        )


@pytest.mark.parametrize(
    "sigma",
    [
        "3",
        True,
    ],
)
def test_invalid_sigma_type_raises(
    sigma,
):
    with pytest.raises(
        TypeError
    ):
        detect_torque_anomalies(
            make_events(
                [
                    2.0,
                ]
            ),
            make_config(
                sigma=sigma,
            ),
        )


def test_missing_required_event_column_raises():
    events = pl.DataFrame(
        {
            "torque": [
                2.0,
            ],
            "status": [
                0,
            ],
        }
    )

    with pytest.raises(
        ValueError,
        match="Missing required",
    ):
        detect_torque_anomalies(
            events,
            make_config(),
        )