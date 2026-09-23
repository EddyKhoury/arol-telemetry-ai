"""Verify the deterministic question-to-report chain."""

from datetime import datetime, timedelta

import polars as pl
import pytest

from src.agent.planner import RulePlanner
from src.agent.report import assemble
from src.agent.trace import Trace
from src.common.registry import call_tool


@pytest.fixture
def events():
    start = datetime(2026, 2, 1, 10)
    return pl.DataFrame({
        "ts": [start + timedelta(seconds=i) for i in range(6)],
        "machine_id": ["M1"] * 6,
        "head_id": ["H01"] * 6,
        "torque": [1.0, 3.0, None, float("nan"), float("inf"), 5.0],
        "status": [0, 65, 0, 0, 0, 0],
    })


def render(events, query="Average torque"):
    planner = RulePlanner()
    plan = planner.plan(query, {"pool": "fixture"})
    assert not plan.ambiguous

    trace = Trace(query, planner=planner.name)
    results = []
    for name, params in plan.calls:
        response = call_tool(name, events, **params)
        trace.tool_call(name, params, response)
        results.append((name, response))

    pool_meta = {
        "pool": "fixture",
        "source": "test-fixture",
        "schema_version": "test-fixture",
        "n_events": len(events),
        "heads": events["head_id"].unique().to_list(),
        "machines": events["machine_id"].unique().to_list(),
        "ts_min": events["ts"].min(),
        "ts_max": events["ts"].max(),
        "timezone": None,
        "warnings": [],
    }
    markdown = assemble(
        query, plan, results, pool_meta, trace, min_n=30
    )
    return markdown, results, trace


def test_question_to_report_contains_calculated_values(events):
    markdown, results, trace = render(events)
    assert results[0][1]["result"]["sample_size"] == 3
    assert "Finite torque observations: **3**" in markdown
    assert "Mean: **3 Nm**" in markdown
    assert "minimum: **1 Nm**" in markdown
    assert "maximum: **5 Nm**" in markdown
    assert "Sample standard deviation (ddof=1): **2 Nm**" in markdown
    assert trace.to_dict()["n_tool_calls"] == 1

    for number, title in enumerate([
        "Goal", "Data used", "Analyses executed",
        "Findings", "Confidence and limits", "Next checks",
    ], start=1):
        assert f"## {number}. {title}" in markdown

    assert "Nothing anomalous surfaced" not in markdown
    assert "machine is stable" not in markdown
    assert "Rates are computed over cap-present" not in markdown
    assert "do not establish whether torque meets engineering limits" in markdown


def test_successful_filter_reaches_report(events):
    markdown, results, _ = render(
        events, "Average torque for successful closures"
    )
    response = results[0][1]
    assert response["meta"]["params"] == {"status_filter": "successful"}
    assert response["result"]["sample_size"] == 2
    assert "Finite torque observations: **2**" in markdown
    assert "Sample standard deviation (ddof=1): **2.82843 Nm**" in markdown


def test_single_observation_does_not_claim_zero_variation(events):
    markdown, results, _ = render(events, "Average torque for status 65")
    assert results[0][1]["result"]["std"] is None
    assert "Mean: **3 Nm**" in markdown
    assert "undefined for fewer than two observations" in markdown
    assert "standard deviation (ddof=1): **0 Nm**" not in markdown


@pytest.mark.parametrize("kind", ["empty", "nonfinite"])
def test_no_finite_sample_does_not_fabricate_statistics(events, kind):
    if kind == "empty":
        selected = events.head(0)
    else:
        selected = events.slice(2, 3)
    markdown, results, _ = render(selected)
    assert results[0][1]["result"]["sample_size"] == 0
    assert "No finite torque observations matched" in markdown
    assert "Mean: **" not in markdown
    assert "Nothing anomalous surfaced" not in markdown


def test_notes_and_small_sample_limit_both_appear(events):
    markdown, _, _ = render(events)
    assert "Counter discontinuities are not reconstructed as closures" in markdown
    assert "n=3 is below min_n=30" in markdown


def test_tool_failure_is_reported_without_statistics(events):
    markdown, results, _ = render(events.drop("torque"))
    assert results[0][1]["ok"] is False
    assert "Missing required event columns" in markdown
    assert "No analysis produced a result" in markdown
    assert "Mean: **" not in markdown
