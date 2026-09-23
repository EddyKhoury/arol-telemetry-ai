import polars as pl

from src.agent.tool_schemas import (
    get_tool_schema,
)

from src.analytics.torque_stats import (
    torque_stats,
)

from src.analytics.torque_distribution import (
    torque_distribution,
)

from src.analytics.trend_analysis import (
    torque_trend,
)

from src.analytics.anomaly_detection import (
    detect_torque_anomalies,
)

from src.analytics.head_correlation import (
    head_correlation,
)


def _normalize_arguments(
    arguments,
) -> dict:
    """
    Normalize tool-call arguments.

    None is treated as an empty argument object because
    several tools have no required model-visible
    arguments.
    """

    if arguments is None:
        return {}

    if not isinstance(
        arguments,
        dict,
    ):
        raise TypeError(
            "tool arguments must be a dictionary"
        )

    return dict(
        arguments
    )


def _validate_argument_keys(
    tool_name: str,
    arguments: dict,
) -> None:
    """
    Validate required and additional argument names
    against the canonical Step 15 schema.

    Detailed value validation remains inside the
    deterministic analytics functions so there is only
    one source of truth for analytical semantics.
    """

    schema = get_tool_schema(
        tool_name
    )

    input_schema = schema[
        "input_schema"
    ]

    properties = input_schema[
        "properties"
    ]

    required = input_schema[
        "required"
    ]

    allowed_keys = set(
        properties
    )

    supplied_keys = set(
        arguments
    )

    unexpected = (
        supplied_keys
        - allowed_keys
    )

    if unexpected:
        unexpected_text = ", ".join(
            sorted(
                unexpected
            )
        )

        raise ValueError(
            "Unexpected argument(s) for "
            f"{tool_name}: "
            f"{unexpected_text}"
        )

    missing = [
        key
        for key in required
        if key not in arguments
    ]

    if missing:
        missing_text = ", ".join(
            missing
        )

        raise ValueError(
            "Missing required argument(s) for "
            f"{tool_name}: "
            f"{missing_text}"
        )


def _execute_torque_stats(
    events,
    config,
    arguments,
):
    """
    Execute torque summary statistics.
    """

    return torque_stats(
        events,
        status_filter=arguments.get(
            "status_filter"
        ),
    )


def _execute_torque_distribution(
    events,
    config,
    arguments,
):
    """
    Execute torque histogram generation.
    """

    return torque_distribution(
        events,
        bins=arguments.get(
            "bins",
            10,
        ),
        status_filter=arguments.get(
            "status_filter"
        ),
    )


def _execute_torque_trend(
    events,
    config,
    arguments,
):
    """
    Execute timestamp-based torque trend analysis.

    Config is injected internally and is never supplied
    by the model.
    """

    return torque_trend(
        events,
        config,
        status_filter=arguments.get(
            "status_filter"
        ),
    )


def _execute_torque_anomalies(
    events,
    config,
    arguments,
):
    """
    Execute deterministic torque-anomaly detection.

    Engineering thresholds and sigma come from the
    runtime config rather than model arguments.
    """

    return detect_torque_anomalies(
        events,
        config,
        status_filter=arguments.get(
            "status_filter"
        ),
    )


def _execute_head_correlation(
    events,
    config,
    arguments,
):
    """
    Execute deterministic head-to-head comparison.
    """

    return head_correlation(
        events,
        arguments[
            "head_a"
        ],
        arguments[
            "head_b"
        ],
    )


TOOL_EXECUTORS = {
    "torque_stats": (
        _execute_torque_stats
    ),
    "torque_distribution": (
        _execute_torque_distribution
    ),
    "torque_trend": (
        _execute_torque_trend
    ),
    "detect_torque_anomalies": (
        _execute_torque_anomalies
    ),
    "head_correlation": (
        _execute_head_correlation
    ),
}


def execute_tool(
    tool_name: str,
    arguments,
    events: (
        pl.DataFrame
        | pl.LazyFrame
    ),
    config: dict,
) -> dict:
    """
    Execute one registered deterministic analytics tool.

    Parameters
    ----------
    tool_name:
        Name from the Step 15 tool registry.

    arguments:
        Model-visible arguments only.

        Runtime objects such as events and config must
        never be supplied here.

    events:
        Current clean event table or LazyFrame.

    config:
        Current trusted project configuration.

    Returns
    -------
    dict
        JSON-safe result returned by the selected
        deterministic analytics function.

    Security / architecture
    -----------------------
    This dispatcher uses a fixed Python mapping.

    It does not use:
        eval()
        exec()
        dynamic imports
        arbitrary function names
        arbitrary Python execution
    """

    if not isinstance(
        tool_name,
        str,
    ):
        raise TypeError(
            "tool_name must be a string"
        )

    # First verify that this tool exists in the
    # canonical provider-neutral schema registry.
    get_tool_schema(
        tool_name
    )

    normalized_arguments = (
        _normalize_arguments(
            arguments
        )
    )

    _validate_argument_keys(
        tool_name,
        normalized_arguments,
    )

    try:
        executor = (
            TOOL_EXECUTORS[
                tool_name
            ]
        )

    except KeyError as exc:
        # This means the schema registry and executor
        # registry have become inconsistent.
        raise RuntimeError(
            "Tool is registered in the schema "
            "registry but has no executor: "
            f"{tool_name}"
        ) from exc

    return executor(
        events,
        config,
        normalized_arguments,
    )