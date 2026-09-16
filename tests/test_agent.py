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


# --- bugs found by running the real model, not a mock ---------------------

def test_two_bad_filters_are_relaxed_cumulatively(cfg, events):
    """The first live run of the LLM planner set BOTH start and end to "now".

    The old _retry dropped one filter, restored it, then dropped the next, so
    every attempt still carried one impossible bound: three retries, three
    identical failures, and a report with no findings. Relaxation has to be
    cumulative.
    """
    from src.agent.planner import Plan

    class _Fixed:
        name = "rules"
        def plan(self, query, context):
            # A future start AND a past end. Each one empties the window on
            # its own, so dropping either alone still fails - only dropping
            # both recovers. start=2030/end=2030 would NOT test this: losing
            # the start bound alone already reopens the whole pool.
            return Plan(goal="g", calls=[("success_rate",
                                          {"start": "2030-01-01",
                                           "end": "2020-01-01"})])

    agent = Orchestrator(cfg, planner=_Fixed())
    answer = agent.answer("kpis")

    assert answer["status"] == "ok", "cumulative relaxation should recover"
    dropped = [s["dropped"] for s in answer["trace"].to_dict()["steps"]
               if s["kind"] == "retry"]
    assert dropped == ["start", "end"]
    assert "retried without start, end" in answer["markdown"]


def test_a_relative_time_word_is_dropped_before_dispatch(cfg, monkeypatch):
    """`start="now"` is not ISO-8601, and resolving it against a February pool
    would produce an empty window dressed up as an answer. It is dropped, and
    the trace says so."""
    from src.agent.planner import LLMPlanner

    cfg["agent"]["llm"] = {"fallback_to_rules": True, "timeout_seconds": 1}
    planner = LLMPlanner(cfg)
    monkeypatch.setattr(planner, "_chat", lambda q, t: {"message": {
        "content": "Ranking heads.",
        "tool_calls": [{"function": {"name": "success_rate",
                                     "arguments": {"start": "now",
                                                   "end": "today",
                                                   "bucket": "day"}}}]}})

    plan = planner.plan("how are the heads doing now?", {})
    assert plan.calls == [("success_rate", {"bucket": "day"})]
    assert len(planner.dropped_args) == 2

    answer = Orchestrator(cfg, planner=planner).answer("how are the heads now?")
    assert answer["status"] == "ok"
    assert any("dropped before dispatch" in n for n in answer["trace"].notes)


def test_a_valid_bound_is_not_dropped(cfg, monkeypatch):
    """The guard must only remove what the parser genuinely cannot read."""
    from src.agent.planner import LLMPlanner

    cfg["agent"]["llm"] = {"fallback_to_rules": True, "timeout_seconds": 1}
    planner = LLMPlanner(cfg)
    monkeypatch.setattr(planner, "_chat", lambda q, t: {"message": {
        "tool_calls": [{"function": {"name": "success_rate",
                                     "arguments": {"start": "2026-02-01"}}}]}})
    assert planner.plan("kpis from february", {}).calls == [
        ("success_rate", {"start": "2026-02-01"})]
    assert planner.dropped_args == []


def test_the_string_null_is_treated_as_not_supplied(cfg, monkeypatch):
    """llama3.2:3b fills optional slots with the STRING "null" rather than
    omitting the key. Taken literally that is a type error on every optional
    argument, which killed three of the first six live questions."""
    from src.agent.planner import LLMPlanner

    cfg["agent"]["llm"] = {"fallback_to_rules": True, "timeout_seconds": 1}
    planner = LLMPlanner(cfg)
    monkeypatch.setattr(planner, "_chat", lambda q, t: {"message": {
        "tool_calls": [{"function": {"name": "anomaly_heads",
                                     "arguments": {"min_n": "null",
                                                   "sigma": "null",
                                                   "start": "None"}}}]}})
    assert planner.plan("is anything wrong?", {}).calls == [("anomaly_heads", {})]


def test_the_planner_absorbs_what_call_tool_rejects(cfg, events, monkeypatch):
    """The split: model noise is absorbed so the answer still lands, but the
    same argument arriving from code is a bug and stays loud."""
    from src.agent.planner import LLMPlanner
    from src.common import registry as R

    cfg["agent"]["llm"] = {"fallback_to_rules": True, "timeout_seconds": 1}
    planner = LLMPlanner(cfg)
    monkeypatch.setattr(planner, "_chat", lambda q, t: {"message": {
        "tool_calls": [{"function": {"name": "success_rate",
                                     "arguments": {"min_n": "lots"}}}]}})

    assert planner.plan("kpis", {}).calls == [("success_rate", {})]   # absorbed
    assert planner.dropped_args                                       # and noted
    assert R.call_tool("success_rate", events, min_n="lots")["ok"] is False  # loud


def test_the_llm_planner_also_honours_a_named_head(cfg, monkeypatch):
    """The rule planner has always done this. The LLM planner did not, so on
    the first live run "is anything wrong with head 26?" came back as a
    fleet-wide scan - the silently-widened question, reintroduced."""
    from src.agent.planner import LLMPlanner

    cfg["agent"]["llm"] = {"fallback_to_rules": True, "timeout_seconds": 1}
    planner = LLMPlanner(cfg)
    monkeypatch.setattr(planner, "_chat", lambda q, t: {"message": {
        "tool_calls": [{"function": {"name": "anomaly_heads",
                                     "arguments": {}}}]}})

    plan = planner.plan("is anything wrong with head 26?", {})
    assert plan.calls[0] == ("head_detail", {"head_id": "H26"})
    assert [n for n, _ in plan.calls] == ["head_detail", "anomaly_heads"]
    assert "H26" in plan.goal


def test_a_head_the_model_already_handled_is_not_duplicated(cfg, monkeypatch):
    from src.agent.planner import LLMPlanner

    cfg["agent"]["llm"] = {"fallback_to_rules": True, "timeout_seconds": 1}
    planner = LLMPlanner(cfg)
    monkeypatch.setattr(planner, "_chat", lambda q, t: {"message": {
        "tool_calls": [{"function": {"name": "head_detail",
                                     "arguments": {"head_id": "H26"}}}]}})
    assert planner.plan("anything wrong with head 26?", {}).calls == [
        ("head_detail", {"head_id": "H26"})]


def test_a_fleet_question_is_left_alone(cfg, monkeypatch):
    """The guard must only fire when a head is actually named."""
    from src.agent.planner import LLMPlanner

    cfg["agent"]["llm"] = {"fallback_to_rules": True, "timeout_seconds": 1}
    planner = LLMPlanner(cfg)
    monkeypatch.setattr(planner, "_chat", lambda q, t: {"message": {
        "tool_calls": [{"function": {"name": "anomaly_heads",
                                     "arguments": {}}}]}})
    assert planner.plan("is anything wrong?", {}).calls == [("anomaly_heads", {})]


@pytest.mark.parametrize("query", [
    "which head is worst",
    "which head is the best",
    "rank the heads",
    "compare the heads",
])
def test_comparative_phrasings_reach_the_rule_planner(query):
    """The LLM planner routes these fine. The rule planner did not, and the
    rule planner is what answers when the model is unreachable - i.e. exactly
    when a live demo needs it. "which head is worst" returned a clarification
    request until `worst`/`best`/`rank`/`compare` became keywords."""
    from src.agent.planner import RulePlanner

    plan = RulePlanner().plan(query, {})
    assert plan.ambiguous is False, f"{query!r} still asks for clarification"
    assert "success_rate_per_head" in [name for name, _ in plan.calls]
