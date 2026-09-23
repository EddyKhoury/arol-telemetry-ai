from datetime import (
    datetime,
    timedelta,
)
import json

import polars as pl
import pytest

from src.analytics.head_correlation import (
    head_correlation,
)


START = datetime(
    2026,
    2,
    1,
    10,
    0,
    0,
)


def make_head(
    head_id,
    torques,
    statuses=None,
    start_offset=0,
):
    if statuses is None:
        statuses = [
            0
            for _ in torques
        ]

    timestamps = [
        START
        + timedelta(
            seconds=(
                start_offset
                + index
            )
        )
        for index
        in range(
            len(torques)
        )
    ]

    error_classes = []

    for status in statuses:

        if status == 0:
            error_classes.append(
                "Closure OK"
            )

        elif status in (
            2,
            3,
        ):
            error_classes.append(
                "No Load"
            )

        elif status in (
            64,
            65,
        ):
            error_classes.append(
                "Bad Closure"
            )

        else:
            error_classes.append(
                "Other Error"
            )

    return pl.DataFrame(
        {
            "ts": timestamps,
            "head_id": [
                head_id
                for _ in torques
            ],
            "torque": torques,
            "status": statuses,
            "error_class": (
                error_classes
            ),
        }
    )


def combine(
    head_a,
    head_b,
):
    return pl.concat(
        [
            head_a,
            head_b,
        ],
        how="vertical",
    )


def test_similar_heads_have_strong_positive_correlation():
    events = combine(
        make_head(
            "H01",
            [
                1.0,
                2.0,
                3.0,
                4.0,
            ],
        ),
        make_head(
            "H05",
            [
                1.1,
                2.1,
                3.1,
                4.1,
            ],
        ),
    )

    result = head_correlation(
        events,
        "H01",
        "H05",
    )

    assert result[
        "matched_torque_samples"
    ] == 4

    assert result[
        "torque_correlation"
    ] == pytest.approx(
        1.0
    )

    assert result[
        "torque_correlation_interpretation"
    ] == "strong_positive"


def test_dissimilar_heads_have_strong_negative_correlation():
    events = combine(
        make_head(
            "H01",
            [
                1.0,
                2.0,
                3.0,
                4.0,
            ],
        ),
        make_head(
            "H05",
            [
                4.0,
                3.0,
                2.0,
                1.0,
            ],
        ),
    )

    result = head_correlation(
        events,
        "H01",
        "H05",
    )

    assert result[
        "torque_correlation"
    ] == pytest.approx(
        -1.0
    )

    assert result[
        "torque_correlation_interpretation"
    ] == "strong_negative"


def test_different_event_counts_are_handled_gracefully():
    events = combine(
        make_head(
            "H01",
            [
                1.0,
                2.0,
                3.0,
                4.0,
                5.0,
            ],
        ),
        make_head(
            "H05",
            [
                1.1,
                2.1,
                3.1,
            ],
        ),
    )

    result = head_correlation(
        events,
        "H01",
        "H05",
    )

    assert result[
        "head_a"
    ][
        "event_count"
    ] == 5

    assert result[
        "head_b"
    ][
        "event_count"
    ] == 3

    assert result[
        "matched_torque_samples"
    ] == 3

    assert result[
        "torque_correlation"
    ] == pytest.approx(
        1.0
    )


def test_success_rate_difference():
    events = combine(
        make_head(
            "H01",
            [
                2.0,
                2.0,
                2.0,
                0.0,
            ],
            statuses=[
                0,
                0,
                65,
                2,
            ],
        ),
        make_head(
            "H05",
            [
                2.0,
                2.0,
                2.0,
                0.0,
            ],
            statuses=[
                0,
                65,
                65,
                2,
            ],
        ),
    )

    result = head_correlation(
        events,
        "H01",
        "H05",
    )

    # H01:
    # successful = 2
    # evaluable = 3
    #
    # H05:
    # successful = 1
    # evaluable = 3
    #
    # No Load is excluded.

    assert result[
        "head_a"
    ][
        "success_rate"
    ] == pytest.approx(
        2 / 3
    )

    assert result[
        "head_b"
    ][
        "success_rate"
    ] == pytest.approx(
        1 / 3
    )

    assert result[
        "success_rate_difference"
    ] == pytest.approx(
        1 / 3
    )

    assert result[
        "success_rate_difference_percentage_points"
    ] == pytest.approx(
        100 / 3
    )

    assert result[
        "success_rate_direction"
    ] == "head_a_higher"


def test_no_load_is_not_counted_as_failure():
    events = combine(
        make_head(
            "H01",
            [
                2.0,
                0.0,
                0.0,
            ],
            statuses=[
                0,
                2,
                2,
            ],
        ),
        make_head(
            "H05",
            [
                2.0,
                0.0,
                0.0,
            ],
            statuses=[
                0,
                2,
                2,
            ],
        ),
    )

    result = head_correlation(
        events,
        "H01",
        "H05",
    )

    assert result[
        "head_a"
    ][
        "success_evaluable_count"
    ] == 1

    assert result[
        "head_a"
    ][
        "success_rate"
    ] == pytest.approx(
        1.0
    )

    assert result[
        "head_b"
    ][
        "success_rate"
    ] == pytest.approx(
        1.0
    )


def test_no_shared_timestamps_returns_insufficient_overlap():
    events = combine(
        make_head(
            "H01",
            [
                1.0,
                2.0,
                3.0,
            ],
            start_offset=0,
        ),
        make_head(
            "H05",
            [
                1.0,
                2.0,
                3.0,
            ],
            start_offset=10,
        ),
    )

    result = head_correlation(
        events,
        "H01",
        "H05",
    )

    assert result[
        "matched_torque_samples"
    ] == 0

    assert result[
        "torque_correlation"
    ] is None

    assert result[
        "torque_correlation_interpretation"
    ] == "insufficient_overlap"


def test_constant_torque_returns_interpretable_undefined_result():
    events = combine(
        make_head(
            "H01",
            [
                2.0,
                2.0,
                2.0,
            ],
        ),
        make_head(
            "H05",
            [
                2.1,
                2.1,
                2.1,
            ],
        ),
    )

    result = head_correlation(
        events,
        "H01",
        "H05",
    )

    assert result[
        "matched_torque_samples"
    ] == 3

    assert result[
        "torque_correlation"
    ] is None

    assert result[
        "torque_correlation_interpretation"
    ] == "undefined_constant_torque"


def test_missing_head_is_handled_gracefully():
    events = make_head(
        "H01",
        [
            1.0,
            2.0,
            3.0,
        ],
    )

    result = head_correlation(
        events,
        "H01",
        "H99",
    )

    assert result[
        "head_a"
    ][
        "found"
    ] is True

    assert result[
        "head_b"
    ][
        "found"
    ] is False

    assert result[
        "head_b"
    ][
        "event_count"
    ] == 0

    assert result[
        "matched_torque_samples"
    ] == 0

    assert result[
        "torque_correlation"
    ] is None


def test_lazyframe_input():
    events = combine(
        make_head(
            "H01",
            [
                1.0,
                2.0,
                3.0,
            ],
        ),
        make_head(
            "H05",
            [
                1.1,
                2.1,
                3.1,
            ],
        ),
    )

    result = head_correlation(
        events.lazy(),
        "H01",
        "H05",
    )

    assert result[
        "matched_torque_samples"
    ] == 3


def test_output_is_json_serializable():
    events = combine(
        make_head(
            "H01",
            [
                1.0,
                2.0,
                3.0,
            ],
        ),
        make_head(
            "H05",
            [
                1.1,
                2.1,
                3.1,
            ],
        ),
    )

    result = head_correlation(
        events,
        "H01",
        "H05",
    )

    encoded = json.dumps(
        result
    )

    assert isinstance(
        encoded,
        str,
    )


def test_same_head_cannot_be_compared_with_itself():
    events = make_head(
        "H01",
        [
            1.0,
            2.0,
        ],
    )

    with pytest.raises(
        ValueError,
        match="different",
    ):
        head_correlation(
            events,
            "H01",
            "H01",
        )


@pytest.mark.parametrize(
    "head_a, head_b",
    [
        (
            1,
            "H05",
        ),
        (
            "H01",
            5,
        ),
    ],
)
def test_invalid_head_types_raise(
    head_a,
    head_b,
):
    events = make_head(
        "H01",
        [
            1.0,
            2.0,
        ],
    )

    with pytest.raises(
        TypeError
    ):
        head_correlation(
            events,
            head_a,
            head_b,
        )


def test_missing_required_column_raises():
    events = pl.DataFrame(
        {
            "ts": [
                START,
            ],
            "head_id": [
                "H01",
            ],
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
        match="error_class",
    ):
        head_correlation(
            events,
            "H01",
            "H05",
        )