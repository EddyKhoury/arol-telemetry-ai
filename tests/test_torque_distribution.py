import json

import polars as pl
import pytest

from src.analytics.torque_distribution import (
    torque_distribution,
)


def make_events():
    return pl.DataFrame(
        {
            "ts": [
                "2026-02-01T10:00:00",
                "2026-02-01T10:00:01",
                "2026-02-01T10:00:02",
                "2026-02-01T10:00:03",
            ],
            "machine_id": [
                "M1",
                "M1",
                "M1",
                "M1",
            ],
            "head_id": [
                "H01",
                "H01",
                "H01",
                "H01",
            ],
            "torque": [
                1.0,
                2.0,
                3.0,
                4.0,
            ],
            "status": [
                0,
                65,
                0,
                65,
            ],
            "error_class": [
                "Closure OK",
                "Bad Closure",
                "Closure OK",
                "Bad Closure",
            ],
            "reject_signal": [
                False,
                True,
                False,
                True,
            ],
            "cap_present": [
                True,
                True,
                True,
                True,
            ],
        }
    )


def test_two_bin_distribution_matches_hand_calculation():
    result = torque_distribution(
        make_events(),
        bins=2,
    )

    assert result["sample_size"] == 4

    assert result["bin_edges"] == pytest.approx(
        [
            1.0,
            2.5,
            4.0,
        ]
    )

    assert result["counts"] == [
        2,
        2,
    ]


def test_configurable_number_of_bins():
    result = torque_distribution(
        make_events(),
        bins=4,
    )

    assert len(
        result["counts"]
    ) == 4

    assert len(
        result["bin_edges"]
    ) == 5


def test_counts_sum_to_sample_size():
    result = torque_distribution(
        make_events(),
        bins=3,
    )

    assert sum(
        result["counts"]
    ) == result["sample_size"]


def test_successful_filter():
    result = torque_distribution(
        make_events(),
        bins=2,
        status_filter="successful",
    )

    # Successful torques are 1.0 and 3.0.
    assert result["sample_size"] == 2

    assert sum(
        result["counts"]
    ) == 2


def test_numeric_status_filter():
    result = torque_distribution(
        make_events(),
        bins=2,
        status_filter=65,
    )

    # Status 65 torques are 2.0 and 4.0.
    assert result["sample_size"] == 2

    assert sum(
        result["counts"]
    ) == 2


def test_lazyframe_input():
    result = torque_distribution(
        make_events().lazy(),
        bins=2,
    )

    assert result["sample_size"] == 4
    assert result["counts"] == [
        2,
        2,
    ]


def test_empty_filtered_result():
    result = torque_distribution(
        make_events(),
        bins=5,
        status_filter=999,
    )

    assert result == {
        "bin_edges": [],
        "counts": [],
        "sample_size": 0,
    }


def test_constant_torque_values():
    events = make_events().with_columns(
        pl.lit(2.0)
        .alias("torque")
    )

    result = torque_distribution(
        events,
        bins=4,
    )

    assert result["sample_size"] == 4

    assert len(
        result["bin_edges"]
    ) == 5

    assert len(
        result["counts"]
    ) == 4

    assert sum(
        result["counts"]
    ) == 4


def test_non_finite_torque_is_excluded():
    events = pl.DataFrame(
        {
            "torque": [
                1.0,
                2.0,
                None,
                float("nan"),
                float("inf"),
                3.0,
            ],
            "status": [
                0,
                0,
                0,
                0,
                0,
                0,
            ],
        }
    )

    result = torque_distribution(
        events,
        bins=2,
    )

    assert result["sample_size"] == 3

    assert sum(
        result["counts"]
    ) == 3


def test_output_is_json_serializable():
    result = torque_distribution(
        make_events(),
        bins=3,
    )

    encoded = json.dumps(
        result
    )

    assert isinstance(
        encoded,
        str,
    )

    assert type(
        result["sample_size"]
    ) is int

    assert all(
        type(value) is int
        for value in result["counts"]
    )

    assert all(
        type(value) is float
        for value in result["bin_edges"]
    )


@pytest.mark.parametrize(
    "bins",
    [
        0,
        -1,
    ],
)
def test_non_positive_bins_raise(bins):
    with pytest.raises(
        ValueError
    ):
        torque_distribution(
            make_events(),
            bins=bins,
        )


@pytest.mark.parametrize(
    "bins",
    [
        2.5,
        "10",
        None,
        True,
    ],
)
def test_invalid_bin_type_raises(bins):
    with pytest.raises(
        TypeError
    ):
        torque_distribution(
            make_events(),
            bins=bins,
        )