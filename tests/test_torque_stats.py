import json

import polars as pl
import pytest

from src.analytics.torque_stats import (
    torque_stats,
)


def make_events():
    return pl.DataFrame(
        {
            "ts": [
                "2026-02-01T10:00:00",
                "2026-02-01T10:00:01",
                "2026-02-01T10:00:02",
            ],
            "machine_id": [
                "M1",
                "M1",
                "M1",
            ],
            "head_id": [
                "H01",
                "H01",
                "H01",
            ],
            "torque": [
                1.0,
                2.0,
                3.0,
            ],
            "status": [
                0,
                65,
                0,
            ],
            "error_class": [
                "Closure OK",
                "Bad Closure",
                "Closure OK",
            ],
            "reject_signal": [
                False,
                True,
                False,
            ],
            "cap_present": [
                True,
                True,
                True,
            ],
        }
    )


def test_torque_stats_hand_computed_example():
    result = torque_stats(
        make_events()
    )

    assert result["sample_size"] == 3
    assert result["mean"] == pytest.approx(
        2.0
    )
    assert result["min"] == pytest.approx(
        1.0
    )
    assert result["max"] == pytest.approx(
        3.0
    )

    # Sample standard deviation of [1, 2, 3].
    assert result["std"] == pytest.approx(
        1.0
    )


def test_successful_filter_changes_result():
    result = torque_stats(
        make_events(),
        status_filter="successful",
    )

    # Successful events have torque [1, 3].
    assert result["sample_size"] == 2
    assert result["mean"] == pytest.approx(
        2.0
    )
    assert result["min"] == pytest.approx(
        1.0
    )
    assert result["max"] == pytest.approx(
        3.0
    )
    assert result["std"] == pytest.approx(
        2 ** 0.5
    )


def test_numeric_status_filter():
    result = torque_stats(
        make_events(),
        status_filter=65,
    )

    assert result["sample_size"] == 1
    assert result["mean"] == pytest.approx(
        2.0
    )
    assert result["min"] == pytest.approx(
        2.0
    )
    assert result["max"] == pytest.approx(
        2.0
    )

    # Sample standard deviation is undefined for n=1.
    assert result["std"] is None


def test_lazyframe_input():
    result = torque_stats(
        make_events().lazy()
    )

    assert result["sample_size"] == 3
    assert result["mean"] == pytest.approx(
        2.0
    )


def test_empty_filtered_result():
    result = torque_stats(
        make_events(),
        status_filter=999,
    )

    assert result == {
        "mean": None,
        "min": None,
        "max": None,
        "std": None,
        "sample_size": 0,
    }


def test_output_is_json_serializable():
    result = torque_stats(
        make_events()
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

    for key in (
        "mean",
        "min",
        "max",
        "std",
    ):
        assert (
            result[key] is None
            or type(result[key]) is float
        )


def test_missing_required_column_raises():
    events = pl.DataFrame(
        {
            "status": [0],
        }
    )

    with pytest.raises(
        ValueError,
        match="torque",
    ):
        torque_stats(
            events
        )


def test_invalid_string_filter_raises():
    with pytest.raises(
        ValueError
    ):
        torque_stats(
            make_events(),
            status_filter="bad",
        )


def test_invalid_filter_type_raises():
    with pytest.raises(
        TypeError
    ):
        torque_stats(
            make_events(),
            status_filter=[
                0,
                65,
            ],
        )