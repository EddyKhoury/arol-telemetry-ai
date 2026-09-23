from src.agent.diagnostic_queries import (
    DIAGNOSTIC_QUERY_CASES,
    list_diagnostic_query_cases,
)

from src.agent.tool_schemas import (
    TOOL_SCHEMA_BY_NAME,
)


def test_has_at_least_ten_query_families():
    assert len(
        DIAGNOSTIC_QUERY_CASES
    ) >= 10


def test_every_case_has_multiple_rephrasings():
    for case in DIAGNOSTIC_QUERY_CASES:
        assert len(
            case["questions"]
        ) >= 3


def test_every_expected_tool_exists():
    registered = set(
        TOOL_SCHEMA_BY_NAME
    )

    for case in DIAGNOSTIC_QUERY_CASES:
        for tool_name in case[
            "expected_tools"
        ]:
            assert (
                tool_name
                in registered
            )


def test_questions_are_non_empty():
    for case in DIAGNOSTIC_QUERY_CASES:
        for question in case[
            "questions"
        ]:
            assert isinstance(
                question,
                str,
            )

            assert question.strip()


def test_case_ids_are_unique():
    ids = [
        case["id"]
        for case
        in DIAGNOSTIC_QUERY_CASES
    ]

    assert len(ids) == len(
        set(ids)
    )


def test_defensive_copy():
    cases = (
        list_diagnostic_query_cases()
    )

    cases[0][
        "questions"
    ][0] = "changed"

    fresh = (
        list_diagnostic_query_cases()
    )

    assert (
        fresh[0]["questions"][0]
        != "changed"
    )