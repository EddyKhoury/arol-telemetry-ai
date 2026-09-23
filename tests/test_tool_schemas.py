import json

import pytest

from src.agent.tool_schemas import (
    TOOL_INTERFACE_VERSION,
    TOOL_SCHEMA_BY_NAME,
    TOOL_SCHEMAS,
    get_tool_schema,
    list_tool_schemas,
)


EXPECTED_TOOL_NAMES = {
    "torque_stats",
    "torque_distribution",
    "torque_trend",
    "detect_torque_anomalies",
    "head_correlation",
}


def test_interface_version():
    assert (
        TOOL_INTERFACE_VERSION
        == "1.0"
    )


def test_exact_expected_tools_are_registered():
    names = {
        schema["name"]
        for schema in TOOL_SCHEMAS
    }

    assert (
        names
        == EXPECTED_TOOL_NAMES
    )


def test_tool_names_are_unique():
    names = [
        schema["name"]
        for schema in TOOL_SCHEMAS
    ]

    assert len(
        names
    ) == len(
        set(names)
    )


def test_registry_matches_schema_collection():
    assert set(
        TOOL_SCHEMA_BY_NAME
    ) == EXPECTED_TOOL_NAMES


def test_every_tool_has_valid_basic_structure():
    for schema in TOOL_SCHEMAS:

        assert isinstance(
            schema["name"],
            str,
        )

        assert schema[
            "name"
        ]

        assert isinstance(
            schema["description"],
            str,
        )

        assert schema[
            "description"
        ]

        input_schema = schema[
            "input_schema"
        ]

        assert (
            input_schema[
                "type"
            ]
            == "object"
        )

        assert isinstance(
            input_schema[
                "properties"
            ],
            dict,
        )

        assert isinstance(
            input_schema[
                "required"
            ],
            list,
        )

        assert (
            input_schema[
                "additionalProperties"
            ]
            is False
        )


def test_tool_schemas_are_json_serializable():
    encoded = json.dumps(
        list_tool_schemas()
    )

    assert isinstance(
        encoded,
        str,
    )


def test_runtime_internal_objects_are_not_exposed():
    forbidden_arguments = {
        "events",
        "event_table",
        "lazyframe",
        "dataframe",
        "config",
        "parquet_path",
        "csv_path",
        "window_seconds",
        "drift_window_seconds",
    }

    for schema in TOOL_SCHEMAS:

        properties = {
            name.lower()
            for name
            in schema[
                "input_schema"
            ][
                "properties"
            ]
        }

        assert (
            properties
            .isdisjoint(
                forbidden_arguments
            )
        )


@pytest.mark.parametrize(
    "tool_name",
    [
        "torque_stats",
        "torque_distribution",
        "torque_trend",
        "detect_torque_anomalies",
    ],
)
def test_analytics_tools_expose_status_filter(
    tool_name,
):
    schema = get_tool_schema(
        tool_name
    )

    status_filter = (
        schema[
            "input_schema"
        ][
            "properties"
        ][
            "status_filter"
        ]
    )

    variants = (
        status_filter[
            "oneOf"
        ]
    )

    assert {
        variant["type"]
        for variant
        in variants
    } == {
        "null",
        "string",
        "integer",
    }


def test_status_filter_string_is_restricted_to_successful():
    schema = get_tool_schema(
        "torque_stats"
    )

    variants = (
        schema[
            "input_schema"
        ][
            "properties"
        ][
            "status_filter"
        ][
            "oneOf"
        ]
    )

    string_schema = next(
        variant
        for variant in variants
        if variant["type"]
        == "string"
    )

    assert string_schema[
        "enum"
    ] == [
        "successful",
    ]


def test_distribution_bins_are_positive_integer():
    schema = get_tool_schema(
        "torque_distribution"
    )

    bins = (
        schema[
            "input_schema"
        ][
            "properties"
        ][
            "bins"
        ]
    )

    assert (
        bins["type"]
        == "integer"
    )

    assert (
        bins["minimum"]
        == 1
    )

    assert (
        bins["default"]
        == 10
    )


def test_head_correlation_requires_both_heads():
    schema = get_tool_schema(
        "head_correlation"
    )

    assert set(
        schema[
            "input_schema"
        ][
            "required"
        ]
    ) == {
        "head_a",
        "head_b",
    }


def test_head_correlation_has_no_status_filter():
    schema = get_tool_schema(
        "head_correlation"
    )

    properties = (
        schema[
            "input_schema"
        ][
            "properties"
        ]
    )

    assert (
        "status_filter"
        not in properties
    )


def test_get_tool_schema_returns_requested_tool():
    schema = get_tool_schema(
        "torque_stats"
    )

    assert (
        schema["name"]
        == "torque_stats"
    )


def test_unknown_tool_raises():
    with pytest.raises(
        KeyError,
        match="Unknown tool",
    ):
        get_tool_schema(
            "does_not_exist"
        )


def test_invalid_tool_name_type_raises():
    with pytest.raises(
        TypeError
    ):
        get_tool_schema(
            123
        )


def test_list_tool_schemas_returns_defensive_copy():
    schemas = (
        list_tool_schemas()
    )

    schemas[
        0
    ][
        "name"
    ] = "changed"

    fresh = (
        list_tool_schemas()
    )

    assert (
        fresh[0]["name"]
        != "changed"
    )


def test_get_tool_schema_returns_defensive_copy():
    schema = get_tool_schema(
        "torque_stats"
    )

    schema[
        "description"
    ] = "changed"

    fresh = get_tool_schema(
        "torque_stats"
    )

    assert (
        fresh["description"]
        != "changed"
    )