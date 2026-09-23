from datetime import (
    datetime,
    timedelta,
)
import json

import polars as pl
import pytest

from src.agent.tool_executor import (
    TOOL_EXECUTORS,
    execute_tool,
)

from src.agent.tool_schemas import (
    TOOL_SCHEMA_BY_NAME,
)


def make_config():
    return {
        "analytics": {
            "torque_expected_min": 1.5,
            "torque_expected_max": 2.5,
            "drift_window_seconds": 10,
            "idle_window_seconds": 300,
            "anomaly_sigma": 3.0,
        }
    }


def make_events():
    start = datetime(
        2026,
        2,
        1,
        10,
        0,
        0,
    )

    rows = []

    head_data = {
        "H01": [
            (
                2.0,
                0,
                "Closure OK",
            ),
            (
                2.1,
                0,
                "Closure OK",
            ),
            (
                2.2,
                0,
                "Closure OK",
            ),
        ],
        "H05": [
            (
                2.0,
                0,
                "Closure OK",
            ),
            (
                2.2,
                65,
                "Bad Closure",
            ),
            (
                2.4,
                0,
                "Closure OK",
            ),
        ],
    }

    for head_id, values in (
        head_data.items()
    ):
        for index, (
            torque,
            status,
            error_class,
        ) in enumerate(
            values
        ):
            rows.append(
                {
                    "ts": (
                        start
                        + timedelta(
                            seconds=index
                        )
                    ),
                    "machine_id": "M1",
                    "head_id": head_id,
                    "torque": torque,
                    "status": status,
                    "error_class": (
                        error_class
                    ),
                    "reject_signal": (
                        status != 0
                    ),
                    "cap_present": True,
                }
            )

    return pl.DataFrame(
        rows
    )


def test_executor_registry_matches_schema_registry():
    assert set(
        TOOL_EXECUTORS
    ) == set(
        TOOL_SCHEMA_BY_NAME
    )


def test_execute_torque_stats():
    result = execute_tool(
        "torque_stats",
        {},
        make_events(),
        make_config(),
    )

    assert (
        result[
            "sample_size"
        ]
        == 6
    )

    assert (
        result["mean"]
        is not None
    )


def test_execute_torque_stats_with_status_filter():
    result = execute_tool(
        "torque_stats",
        {
            "status_filter": (
                "successful"
            ),
        },
        make_events(),
        make_config(),
    )

    assert (
        result[
            "sample_size"
        ]
        == 5
    )


def test_execute_distribution_with_default_bins():
    result = execute_tool(
        "torque_distribution",
        {},
        make_events(),
        make_config(),
    )

    assert len(
        result["counts"]
    ) == 10

    assert len(
        result["bin_edges"]
    ) == 11


def test_execute_distribution_with_custom_bins():
    result = execute_tool(
        "torque_distribution",
        {
            "bins": 3,
        },
        make_events(),
        make_config(),
    )

    assert len(
        result["counts"]
    ) == 3

    assert sum(
        result["counts"]
    ) == result[
        "sample_size"
    ]


def test_execute_trend_uses_runtime_config():
    config = make_config()

    config[
        "analytics"
    ][
        "drift_window_seconds"
    ] = 7

    result = execute_tool(
        "torque_trend",
        {},
        make_events(),
        config,
    )

    assert (
        result[
            "window_seconds"
        ]
        == 7
    )


def test_execute_anomaly_detection_uses_runtime_config():
    config = make_config()

    config[
        "analytics"
    ][
        "torque_expected_max"
    ] = 2.15

    result = execute_tool(
        "detect_torque_anomalies",
        {},
        make_events(),
        config,
    )

    assert (
        result[
            "expected_max"
        ]
        == pytest.approx(
            2.15
        )
    )

    assert (
        result[
            "anomaly_count"
        ]
        > 0
    )


def test_execute_head_correlation():
    result = execute_tool(
        "head_correlation",
        {
            "head_a": "H01",
            "head_b": "H05",
        },
        make_events(),
        make_config(),
    )

    assert (
        result[
            "head_a"
        ][
            "head_id"
        ]
        == "H01"
    )

    assert (
        result[
            "head_b"
        ][
            "head_id"
        ]
        == "H05"
    )

    assert (
        result[
            "matched_torque_samples"
        ]
        == 3
    )


def test_lazyframe_is_supported():
    result = execute_tool(
        "torque_stats",
        {},
        make_events().lazy(),
        make_config(),
    )

    assert (
        result[
            "sample_size"
        ]
        == 6
    )


def test_none_arguments_are_treated_as_empty():
    result = execute_tool(
        "torque_stats",
        None,
        make_events(),
        make_config(),
    )

    assert (
        result[
            "sample_size"
        ]
        == 6
    )


def test_arguments_are_not_mutated():
    arguments = {
        "bins": 3,
    }

    original = dict(
        arguments
    )

    execute_tool(
        "torque_distribution",
        arguments,
        make_events(),
        make_config(),
    )

    assert (
        arguments
        == original
    )


def test_unknown_tool_is_rejected():
    with pytest.raises(
        KeyError,
        match="Unknown tool",
    ):
        execute_tool(
            "run_arbitrary_code",
            {},
            make_events(),
            make_config(),
        )


def test_invalid_tool_name_type_is_rejected():
    with pytest.raises(
        TypeError
    ):
        execute_tool(
            123,
            {},
            make_events(),
            make_config(),
        )


def test_non_dictionary_arguments_are_rejected():
    with pytest.raises(
        TypeError,
        match="dictionary",
    ):
        execute_tool(
            "torque_stats",
            [
                "bad",
            ],
            make_events(),
            make_config(),
        )


def test_unexpected_argument_is_rejected():
    with pytest.raises(
        ValueError,
        match="Unexpected",
    ):
        execute_tool(
            "torque_stats",
            {
                "python_code": (
                    "print('hello')"
                ),
            },
            make_events(),
            make_config(),
        )


def test_runtime_events_cannot_be_supplied_as_model_argument():
    with pytest.raises(
        ValueError,
        match="Unexpected",
    ):
        execute_tool(
            "torque_stats",
            {
                "events": "fake",
            },
            make_events(),
            make_config(),
        )


def test_runtime_config_cannot_be_supplied_as_model_argument():
    with pytest.raises(
        ValueError,
        match="Unexpected",
    ):
        execute_tool(
            "torque_trend",
            {
                "config": {
                    "analytics": {
                        "drift_window_seconds": 1,
                    }
                },
            },
            make_events(),
            make_config(),
        )


def test_missing_head_a_is_rejected():
    with pytest.raises(
        ValueError,
        match="head_a",
    ):
        execute_tool(
            "head_correlation",
            {
                "head_b": "H05",
            },
            make_events(),
            make_config(),
        )


def test_missing_head_b_is_rejected():
    with pytest.raises(
        ValueError,
        match="head_b",
    ):
        execute_tool(
            "head_correlation",
            {
                "head_a": "H01",
            },
            make_events(),
            make_config(),
        )


def test_underlying_validation_errors_propagate():
    with pytest.raises(
        ValueError
    ):
        execute_tool(
            "torque_distribution",
            {
                "bins": 0,
            },
            make_events(),
            make_config(),
        )


def test_result_is_json_serializable():
    result = execute_tool(
        "head_correlation",
        {
            "head_a": "H01",
            "head_b": "H05",
        },
        make_events(),
        make_config(),
    )

    encoded = json.dumps(
        result
    )

    assert isinstance(
        encoded,
        str,
    )


def test_execution_is_deterministic():
    events = make_events()
    config = make_config()

    result_1 = execute_tool(
        "torque_stats",
        {},
        events,
        config,
    )

    result_2 = execute_tool(
        "torque_stats",
        {},
        events,
        config,
    )

    assert (
        result_1
        == result_2
    )