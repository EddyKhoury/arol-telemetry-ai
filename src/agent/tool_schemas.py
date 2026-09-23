from copy import deepcopy


TOOL_INTERFACE_VERSION = "1.0"


def _status_filter_schema() -> dict:
    """
    JSON-schema fragment shared by analytics tools that
    support optional event-status filtering.

    Supported values:

        null
            Use all events.

        "successful"
            Use status == 0.

        integer
            Use the exact raw AROL status code.
    """

    return {
        "description": (
            "Optional event-status filter. "
            'Use "successful" for status 0, '
            "an integer for an exact AROL status code, "
            "or null for all events."
        ),
        "oneOf": [
            {
                "type": "null",
            },
            {
                "type": "string",
                "enum": [
                    "successful",
                ],
            },
            {
                "type": "integer",
            },
        ],
        "default": None,
    }


TORQUE_STATS_TOOL = {
    "name": "torque_stats",
    "description": (
        "Calculate summary statistics for closure torque "
        "from the current telemetry event dataset. "
        "Returns mean, minimum, maximum, sample standard "
        "deviation, and sample size."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status_filter": (
                _status_filter_schema()
            ),
        },
        "required": [],
        "additionalProperties": False,
    },
}


TORQUE_DISTRIBUTION_TOOL = {
    "name": "torque_distribution",
    "description": (
        "Calculate a histogram of closure torque from "
        "the current telemetry event dataset. "
        "Returns histogram bin edges, counts, and "
        "sample size."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "bins": {
                "type": "integer",
                "minimum": 1,
                "default": 10,
                "description": (
                    "Number of equal-width histogram bins."
                ),
            },
            "status_filter": (
                _status_filter_schema()
            ),
        },
        "required": [],
        "additionalProperties": False,
    },
}


TORQUE_TREND_TOOL = {
    "name": "torque_trend",
    "description": (
        "Analyze closure-torque behavior over event time "
        "using the configured trailing time window. "
        "Returns the moving-average series and a "
        "deterministic drift signal."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status_filter": (
                _status_filter_schema()
            ),
        },
        "required": [],
        "additionalProperties": False,
    },
}


TORQUE_ANOMALIES_TOOL = {
    "name": "detect_torque_anomalies",
    "description": (
        "Detect anomalous closure-torque events using "
        "configured engineering thresholds and "
        "statistical deviation. Each detected anomaly "
        "includes an explicit reason."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status_filter": (
                _status_filter_schema()
            ),
        },
        "required": [],
        "additionalProperties": False,
    },
}


HEAD_CORRELATION_TOOL = {
    "name": "head_correlation",
    "description": (
        "Compare two capping heads using shared-timestamp "
        "torque correlation, mean torque, event counts, "
        "and success-rate difference."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "head_a": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "First capping-head identifier, "
                    'for example "H01".'
                ),
            },
            "head_b": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Second capping-head identifier, "
                    'for example "H05".'
                ),
            },
        },
        "required": [
            "head_a",
            "head_b",
        ],
        "additionalProperties": False,
    },
}


TOOL_SCHEMAS = (
    TORQUE_STATS_TOOL,
    TORQUE_DISTRIBUTION_TOOL,
    TORQUE_TREND_TOOL,
    TORQUE_ANOMALIES_TOOL,
    HEAD_CORRELATION_TOOL,
)


TOOL_SCHEMA_BY_NAME = {
    schema["name"]: schema
    for schema in TOOL_SCHEMAS
}


def list_tool_schemas() -> list[dict]:
    """
    Return defensive copies of all registered tool
    schemas.

    Callers may safely modify the returned structures
    without changing the canonical registry.
    """

    return deepcopy(
        list(
            TOOL_SCHEMAS
        )
    )


def get_tool_schema(
    tool_name: str,
) -> dict:
    """
    Return one registered tool schema by name.

    Raises:
        TypeError:
            If tool_name is not a string.

        KeyError:
            If the requested tool is not registered.
    """

    if not isinstance(
        tool_name,
        str,
    ):
        raise TypeError(
            "tool_name must be a string"
        )

    try:
        schema = (
            TOOL_SCHEMA_BY_NAME[
                tool_name
            ]
        )

    except KeyError as exc:
        raise KeyError(
            f"Unknown tool: {tool_name}"
        ) from exc

    return deepcopy(
        schema
    )