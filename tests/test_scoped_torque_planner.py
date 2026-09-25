"""Verify scoped routing and execution through the orchestrator."""

from datetime import datetime

import polars as pl
import pytest

from src.agent.orchestrator import Orchestrator
from src.agent.planner import RulePlanner
from src.ingestion.event_table_polars import write_event_table_parquet


@pytest.mark.parametrize("query, expected", [
    ("Average torque for head 5", {"head_id": "H05"}),
    (
        "Average torque for H05 for successful closures",
        {"head_id": "H05", "status_filter": "successful"},
    ),
    (
        "Torque statistics for machine MCCaBc",
        {"machine_id": "MCCaBc"},
    ),
    (
        "Average torque for head 5 on 2026-02-01",
        {
            "head_id": "H05",
            "start": "2026-02-01T00:00:00",
            "end": "2026-02-02T00:00:00",
        },
    ),
    (
        "Average torque from 2026-02-01T10:00:00 until 2026-02-01T11:00:00",
        {"start": "2026-02-01T10:00:00", "end": "2026-02-01T11:00:00"},
    ),
    (
        "Average torque for all closures for head 5",
        {"head_id": "H05"},
    ),
    (
        "Average torque for successful closures and for head 5",
        {"status_filter": "successful", "head_id": "H05"},
    ),
])
def test_explicit_scope_reaches_the_plan(query, expected):
    plan = RulePlanner().plan(query, {"pool": "fixture"})
    assert plan.ambiguous is False
    assert plan.calls == [("torque_stats", expected)]
    assert plan.filters == expected


@pytest.mark.parametrize("query", [
    "Average torque for head 5 for head 6",
    "Average torque for all closures for status 65",
    "Average torque on 2026-02-01 on 2026-02-02",
    "Average torque on 2026-02-30",
    "Average torque from 2026-02-02 until 2026-02-01",
    "Average torque from 2026-02-01T10:00:00Z until 2026-02-01T11:00:00Z",
    "Average torque for head 5 excluding status 65",
])
def test_conflicting_or_unsupported_scope_calls_no_tool(query):
    plan = RulePlanner().plan(query, {"pool": "fixture"})
    assert plan.ambiguous is True
    assert plan.calls == []


@pytest.fixture
def engine(tmp_path):
    events = pl.DataFrame({
        "ts": [datetime.fromisoformat(value) for value in [
            "2026-01-31T23:59:59",
            "2026-02-01T00:00:00",
            "2026-02-01T12:00:00",
            "2026-02-01T23:59:59",
            "2026-02-02T00:00:00",
            "2026-02-01T12:00:00",
            "2026-02-01T12:00:00",
        ]],
        "machine_id": ["M1", "M1", "M1", "M1", "M1", "M1", "M2"],
        "head_id": ["H05", "H05", "H05", "H05", "H05", "H06", "H05"],
        "torque": [500.0, 1.0, 9.0, 5.0, 500.0, 700.0, 900.0],
        "status": [0, 0, 65, 0, 0, 0, 0],
        "error_class": [
            "Closure OK", "Closure OK", "Bad Closure",
            "Closure OK", "Closure OK", "Closure OK", "Closure OK",
        ],
        "reject_signal": [False, False, True, False, False, False, False],
        "cap_present": [True] * 7,
    })
    path = write_event_table_parquet(events, tmp_path / "events.parquet")
    return Orchestrator(cfg={
        "data": {
            "source": "person_a",
            "person_a": {"fixture": str(path)},
        },
        "agent": {"planner": "rules"},
    })


def test_full_question_excludes_other_heads_machines_dates_and_statuses(engine):
    answer = engine.answer(
        "Average torque for head 5 for machine M1 "
        "on 2026-02-01 for successful closures",
        pool="fixture",
    )
    assert answer["status"] == "ok"
    response = answer["results"][0][1]
    assert response["result"]["sample_size"] == 2
    assert response["result"]["mean"] == 3.0
    assert response["meta"]["params"] == {
        "head_id": "H05",
        "machine_id": "M1",
        "start": "2026-02-01T00:00:00",
        "end": "2026-02-02T00:00:00",
        "status_filter": "successful",
    }
    assert "Mean: **3 Nm**" in answer["markdown"]
    assert answer["trace"].to_dict()["n_tool_calls"] == 1


def test_unknown_head_does_not_return_another_heads_statistics(engine):
    answer = engine.answer("Average torque for head 99", pool="fixture")
    assert answer["status"] == "ok"
    response = answer["results"][0][1]
    assert response["result"]["sample_size"] == 0
    assert response["meta"]["params"] == {"head_id": "H99"}
    assert "No finite torque observations matched" in answer["markdown"]
    assert answer["trace"].to_dict()["n_tool_calls"] == 1
