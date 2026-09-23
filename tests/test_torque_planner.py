"""Question-to-tool routing checks for the first torque integration."""

import polars as pl
import pytest

from src.agent.planner import RulePlanner
from src.common.registry import call_tool


@pytest.mark.parametrize("query, params", [
    ("Torque statistics", {}),
    ("What is the average torque?", {}),
    (
        "What is the average torque for successful closures?",
        {"status_filter": "successful"},
    ),
    ("Minimum torque for status 65", {"status_filter": 65}),
    ("Show me the torque summary for all closures", {}),
])
def test_supported_questions_route_to_torque(query, params):
    plan = RulePlanner().plan(query, {"pool": "fixture"})
    assert plan.ambiguous is False
    assert plan.calls == [("torque_stats", params)]
    assert plan.filters == params


@pytest.mark.parametrize("query", [
    "Average torque for head 5 excluding H02",
    "Average torque from 2026-02-02 until 2026-02-01",
    "Average torque yesterday",
    'Is torque drifting excluding head 3',
    'Compare torque between H01 and H02 excluding head 3',
    'Show torque distribution excluding head 3',
    "Average torque above 2 Nm",
])
def test_unsupported_scope_is_not_silently_dropped(query):
    plan = RulePlanner().plan(query, {"pool": "fixture"})
    assert plan.ambiguous is True
    assert plan.calls == []
    assert plan.clarification


@pytest.mark.parametrize("query, expected_n, expected_mean", [
    ("Average torque", 3, 16 / 3),
    ("Average torque for successful closures", 2, 3.0),
])
def test_question_dispatches_to_real_analytics(
    query, expected_n, expected_mean
):
    events = pl.DataFrame({
        "torque": [1.0, 10.0, 5.0],
        "status": [0, 65, 0],
    })
    plan = RulePlanner().plan(query, {"pool": "fixture"})
    name, params = plan.calls[0]
    response = call_tool(name, events, **params)

    assert response["ok"] is True
    assert response["result"]["sample_size"] == expected_n
    assert response["result"]["mean"] == pytest.approx(expected_mean)
    assert response["meta"]["n"] == expected_n


def test_existing_non_torque_routing_is_preserved():
    plan = RulePlanner().plan("success rate", {"pool": "fixture"})
    assert plan.ambiguous is False
    assert [name for name, _ in plan.calls] == [
        "success_rate", "success_rate_per_head",
    ]
