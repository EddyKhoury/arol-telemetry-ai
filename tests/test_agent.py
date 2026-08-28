"""The orchestrator, end to end.

Covers the whole loop from reference diagram 02, including the paths that only
show up when something goes wrong - which is the graceful-failure demo the
plan calls for.
"""

import re

import pytest

from src.agent.orchestrator import Orchestrator
from src.agent.planner import RulePlanner, parse_intent
from src.common import datasource

REQUIRED_SECTIONS = [
    "## 1. Goal",
    "## 2. Data used",
    "## 3. Analyses executed",
    "## 4. Findings",
    "## 5. Confidence and limits",
    "## 6. Next checks",
]


@pytest.fixture
def agent(cfg):
    return Orchestrator(cfg)


# --- intent parsing -------------------------------------------------------

@pytest.mark.parametrize("query,intent", [
    ("is anything wrong with the machine", "anomalies"),
    ("show me idle periods", "idle"),
    ("what is the throughput by hour", "throughput"),
    ("give me a kpi summary", "kpi"),
])
def test_intent_routing(query, intent):
    assert parse_intent(query)[0] == intent


@pytest.mark.parametrize("query,expected", [
    ("problems on head 5", {"head_id": "H05"}),
    ("kpi for H12", {"head_id": "H12"}),
    ("kpi from 2026-02-01 to 2026-02-02",
     {"start": "2026-02-01", "end": "2026-02-02"}),
    ("throughput per shift", {"bucket": "shift"}),
])
def test_filter_extraction(query, expected):
    filters = parse_intent(query)[1]
    for key, value in expected.items():
        assert filters[key] == value


# --- the happy path -------------------------------------------------------

def test_report_has_all_six_sections_in_order(agent):
    answer = agent.answer("kpi summary")
    assert answer["status"] == "ok"
    positions = [answer["markdown"].index(s) for s in REQUIRED_SECTIONS]
    assert positions == sorted(positions), "sections are out of order"


def test_report_names_the_data_it_used(agent):
    answer = agent.answer("kpi summary")
    assert "closure events" in answer["markdown"]
    assert "SYNTHETIC DATA" in answer["markdown"], \
        "a synthetic run must say so in the report"


def test_every_report_carries_a_trace(agent):
    answer = agent.answer("is anything wrong")
    trace = answer["trace"].to_dict()
    assert trace["n_tool_calls"] >= 1
    assert [s["kind"] for s in trace["steps"]][0] == "plan"
    assert any(s["kind"] == "validate" for s in trace["steps"])


def test_the_anomaly_report_names_the_injected_head(agent, faults):
    answer = agent.answer("is anything wrong with the machine")
    assert faults["elevated_reject_rate"]["head_id"] in answer["markdown"]


# --- determinism ----------------------------------------------------------

def _stable_part(markdown):
    """Strip wall-clock timings so two runs can be compared."""
    body = markdown.split("## Trace")[0]
    return re.sub(r"\d+(\.\d+)? ms", "<ms>", re.sub(r"\*Generated:.*", "", body))


def test_the_same_query_produces_the_same_report(agent):
    """Repeatable outputs - the design claim the project rests on."""
    first = agent.answer("kpi summary")["markdown"]
    second = agent.answer("kpi summary")["markdown"]
    assert _stable_part(first) == _stable_part(second)


# --- the failure paths ----------------------------------------------------

def test_an_unrecognised_query_asks_for_clarification(agent):
    answer = agent.answer("what is the weather in Turin")
    assert answer["status"] == "needs_clarification"
    assert "could not tell" in answer["message"].lower()
    assert answer["results"] == []


def test_an_impossible_filter_is_retried_then_reported(agent):
    """Diagram 02's retry edge: relax a filter rather than give up."""
    answer = agent.answer("idle periods on head 3 on 2030-01-01")
    kinds = [s["kind"] for s in answer["trace"].to_dict()["steps"]]
    assert "retry" in kinds
    assert answer["status"] in ("ok", "partial")
    assert "retried without" in answer["markdown"]


def test_a_broken_data_source_degrades_instead_of_crashing(cfg):
    """Person A's loader is still a stub; asking for it must not traceback."""
    cfg["data"]["source"] = "real"
    cfg["data"]["pools"] = {"feb": ["nonexistent.csv"]}
    agent = Orchestrator(cfg)
    answer = agent.answer("kpi summary", pool="feb")
    assert answer["status"] == "degraded"
    assert "Could not load" in answer["markdown"]


def test_a_tool_that_fails_does_not_kill_the_report(agent, monkeypatch):
    from src.common import registry as R

    real_call = R.call_tool

    def flaky(name, events, **params):
        if name == "success_rate_per_head":
            return R.env.failure("simulated outage", tool=name, params=params)
        return real_call(name, events, **params)

    monkeypatch.setattr("src.agent.orchestrator.registry.call_tool", flaky)
    answer = agent.answer("kpi summary")
    assert answer["status"] == "partial"
    assert "simulated outage" in answer["markdown"]
    # The surviving tool still produced findings.
    assert "## 4. Findings" in answer["markdown"]


# --- the contract seam ----------------------------------------------------

def test_switching_source_is_the_only_change_needed(cfg):
    """Audit F1: synthetic and real are interchangeable behind get_source."""
    cfg["data"]["source"] = "synthetic"
    assert isinstance(datasource.get_source(cfg), datasource.SyntheticSource)
    cfg["data"]["source"] = "real"
    assert isinstance(datasource.get_source(cfg), datasource.RealSource)


def test_rule_planner_never_calls_an_unregistered_tool(cfg):
    from src.common import registry as R

    planner = RulePlanner()
    for query in ("kpi", "anomalies", "idle periods", "throughput by hour"):
        for tool_name, params in planner.plan(query, {}).calls:
            assert R.get(tool_name) is not None, f"{tool_name} is not registered"
            assert set(params) <= set(R.get(tool_name).params)
