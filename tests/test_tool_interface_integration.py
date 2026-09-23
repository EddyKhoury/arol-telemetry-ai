from datetime import (
    datetime,
    timedelta,
)
import json

import polars as pl
import pytest

from src.agent.tool_executor import (
    execute_tool,
)

from src.agent.tool_schemas import (
    get_tool_schema,
    list_tool_schemas,
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
    """
    Synthetic clean event table representing the
    boundary Person B receives from Person A.

    H01 and H05 share timestamps so head correlation
    can also be exercised end-to-end.
    """

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
            (1.0, 65, "Bad Closure"),
            (1.9, 0, "Closure OK"),
            (2.0, 0, "Closure OK"),
            (2.1, 0, "Closure OK"),
            (3.0, 65, "Bad Closure"),
        ],
        "H05": [
            (1.8, 0, "Closure OK"),
            (1.9, 0, "Closure OK"),
            (2.0, 0, "Closure OK"),
            (2.2, 65, "Bad Closure"),
            (2.4, 0, "Closure OK"),
        ],
    }

    for head_id, values in head_data.items():

        for index, (
            torque,
            status,
            error_class,
        ) in enumerate(values):

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


def execute_model_style_call(
    tool_call,
    events=None,
    config=None,
):
    """
    Simulate Person B receiving a provider-neutral
    model tool call.

    Example:

        {
            "name": "torque_stats",
            "arguments": {
                "status_filter": "successful"
            }
        }

    Runtime events and config are supplied by the
    application, not by the model.
    """

    if events is None:
        events = make_events()

    if config is None:
        config = make_config()

    return execute_tool(
        tool_call["name"],
        tool_call.get(
            "arguments",
            {},
        ),
        events,
        config,
    )


def test_all_published_tools_are_executable_end_to_end():
    """
    Every tool advertised by Step 15 must have a
    functioning Step 16 execution path.
    """

    calls = {
        "torque_stats": {
            "name": "torque_stats",
            "arguments": {},
        },
        "torque_distribution": {
            "name": (
                "torque_distribution"
            ),
            "arguments": {
                "bins": 4,
            },
        },
        "torque_trend": {
            "name": "torque_trend",
            "arguments": {},
        },
        "detect_torque_anomalies": {
            "name": (
                "detect_torque_anomalies"
            ),
            "arguments": {},
        },
        "head_correlation": {
            "name": "head_correlation",
            "arguments": {
                "head_a": "H01",
                "head_b": "H05",
            },
        },
    }

    published_names = {
        schema["name"]
        for schema
        in list_tool_schemas()
    }

    assert (
        set(calls)
        == published_names
    )

    for tool_name in sorted(
        published_names
    ):
        result = (
            execute_model_style_call(
                calls[
                    tool_name
                ]
            )
        )

        assert isinstance(
            result,
            dict,
        )


def test_torque_stats_full_boundary():
    tool_call = {
        "name": "torque_stats",
        "arguments": {
            "status_filter": (
                "successful"
            ),
        },
    }

    schema = get_tool_schema(
        tool_call["name"]
    )

    assert (
        "status_filter"
        in schema[
            "input_schema"
        ][
            "properties"
        ]
    )

    result = (
        execute_model_style_call(
            tool_call
        )
    )

    # Successful events:
    #
    # H01 -> 3
    # H05 -> 4
    assert (
        result[
            "sample_size"
        ]
        == 7
    )

    assert (
        result["mean"]
        is not None
    )


def test_distribution_full_boundary():
    tool_call = {
        "name": (
            "torque_distribution"
        ),
        "arguments": {
            "bins": 5,
        },
    }

    result = (
        execute_model_style_call(
            tool_call
        )
    )

    assert len(
        result["counts"]
    ) == 5

    assert len(
        result["bin_edges"]
    ) == 6

    assert sum(
        result["counts"]
    ) == result[
        "sample_size"
    ]


def test_trend_full_boundary_uses_trusted_config():
    tool_call = {
        "name": "torque_trend",
        "arguments": {},
    }

    config = make_config()

    config[
        "analytics"
    ][
        "drift_window_seconds"
    ] = 7

    result = (
        execute_model_style_call(
            tool_call,
            config=config,
        )
    )

    assert (
        result[
            "window_seconds"
        ]
        == 7
    )


def test_anomaly_detection_full_boundary():
    tool_call = {
        "name": (
            "detect_torque_anomalies"
        ),
        "arguments": {},
    }

    result = (
        execute_model_style_call(
            tool_call
        )
    )

    # The synthetic table contains torque 1.0
    # below the configured minimum and torque 3.0
    # above the configured maximum.
    assert (
        result[
            "anomaly_count"
        ]
        >= 2
    )

    reasons = [
        anomaly["reason"]
        for anomaly
        in result[
            "anomalies"
        ]
    ]

    assert any(
        "below_expected_min"
        in reason
        for reason in reasons
    )

    assert any(
        "above_expected_max"
        in reason
        for reason in reasons
    )


def test_head_correlation_full_boundary():
    tool_call = {
        "name": "head_correlation",
        "arguments": {
            "head_a": "H01",
            "head_b": "H05",
        },
    }

    result = (
        execute_model_style_call(
            tool_call
        )
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
        == 5
    )


def test_complete_tool_results_survive_json_round_trip():
    """
    Person B must be able to pass tool results through
    a JSON-based agent/orchestration layer.
    """

    calls = [
        {
            "name": "torque_stats",
            "arguments": {},
        },
        {
            "name": (
                "torque_distribution"
            ),
            "arguments": {
                "bins": 3,
            },
        },
        {
            "name": "torque_trend",
            "arguments": {},
        },
        {
            "name": (
                "detect_torque_anomalies"
            ),
            "arguments": {},
        },
        {
            "name": "head_correlation",
            "arguments": {
                "head_a": "H01",
                "head_b": "H05",
            },
        },
    ]

    for tool_call in calls:

        result = (
            execute_model_style_call(
                tool_call
            )
        )

        encoded = json.dumps(
            result
        )

        decoded = json.loads(
            encoded
        )

        assert isinstance(
            decoded,
            dict,
        )


def test_lazy_event_boundary_works_end_to_end():
    tool_call = {
        "name": "torque_stats",
        "arguments": {},
    }

    result = (
        execute_model_style_call(
            tool_call,
            events=(
                make_events()
                .lazy()
            ),
        )
    )

    assert (
        result[
            "sample_size"
        ]
        == 10
    )


def test_model_cannot_override_runtime_config():
    tool_call = {
        "name": "torque_trend",
        "arguments": {
            "config": {
                "analytics": {
                    "drift_window_seconds": 1,
                }
            }
        },
    }

    with pytest.raises(
        ValueError,
        match="Unexpected",
    ):
        execute_model_style_call(
            tool_call
        )


def test_model_cannot_override_runtime_events():
    tool_call = {
        "name": "torque_stats",
        "arguments": {
            "events": "fake-data",
        },
    }

    with pytest.raises(
        ValueError,
        match="Unexpected",
    ):
        execute_model_style_call(
            tool_call
        )


def test_unknown_model_requested_tool_is_rejected():
    tool_call = {
        "name": (
            "execute_python_code"
        ),
        "arguments": {
            "code": (
                "print('unsafe')"
            ),
        },
    }

    with pytest.raises(
        KeyError,
        match="Unknown tool",
    ):
        execute_model_style_call(
            tool_call
        )


def test_required_model_arguments_are_enforced():
    tool_call = {
        "name": "head_correlation",
        "arguments": {
            "head_a": "H01",
        },
    }

    with pytest.raises(
        ValueError,
        match="head_b",
    ):
        execute_model_style_call(
            tool_call
        )


def test_schema_and_executor_use_same_argument_contract():
    """
    A model-visible argument accepted by the schema
    must successfully reach the deterministic function.
    """

    schema = get_tool_schema(
        "torque_distribution"
    )

    assert (
        "bins"
        in schema[
            "input_schema"
        ][
            "properties"
        ]
    )

    result = (
        execute_model_style_call(
            {
                "name": (
                    "torque_distribution"
                ),
                "arguments": {
                    "bins": 7,
                },
            }
        )
    )

    assert len(
        result["counts"]
    ) == 7


def test_same_tool_call_is_deterministic_end_to_end():
    tool_call = {
        "name": "head_correlation",
        "arguments": {
            "head_a": "H01",
            "head_b": "H05",
        },
    }

    events = make_events()
    config = make_config()

    result_1 = (
        execute_model_style_call(
            tool_call,
            events=events,
            config=config,
        )
    )

    result_2 = (
        execute_model_style_call(
            tool_call,
            events=events,
            config=config,
        )
    )

    assert (
        result_1
        == result_2
    )