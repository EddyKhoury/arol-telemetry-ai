"""LLM scope validation without Ollama; accepted and rejected actual dispatch."""
from copy import deepcopy
import json
import pytest

from src.agent.planner import LLMPlanner, RulePlanner
from src.agent.orchestrator import Orchestrator
from src.common import registry
from src.agent.llm_validation import VERIFIED_TOOLS
from src.ingestion.event_table_polars import write_event_table_parquet

QUERY = ("Show torque distribution with 3 bins for head 5 for machine MiXeD "
         "from 2026-02-01T00:00:00 until 2026-02-01T12:00:00 for successful closures")
PARAMS = dict(bins=3, head_id="H05", machine_id="MiXeD", start="2026-02-01T00:00:00",
              end="2026-02-01T12:00:00", status_filter="successful")


def reply(name="torque_distribution", args=None, content=""):
    return {"message": {"content": content, "tool_calls": [
        {"function": {"name": name, "arguments": deepcopy(PARAMS if args is None else args)}}
    ]}}


@pytest.fixture
def planner():
    return LLMPlanner({"agent": {"llm": {"fallback_to_rules": True}}})


@pytest.mark.parametrize("query", [
    "Average torque for head 5 on 2026-02-01",
    QUERY,
    "Show torque trend for head 5 for machine M1",
    "Find torque anomalies for status 65",
    "Compare torque between H05 and H06 for machine M1",
])
def test_all_five_exact_proposals_are_accepted(planner, monkeypatch, query):
    expected = RulePlanner().plan(query, {})
    name, params = expected.calls[0]
    offered = []
    def chat(q, tools):
        offered.extend(tool["function"]["name"] for tool in tools)
        return reply(name, params)
    monkeypatch.setattr(planner, "_chat", chat)
    plan = planner.plan(query, {})
    assert plan.ambiguous is False
    assert plan.calls == expected.calls
    assert plan.filters == expected.filters
    assert set(offered) == VERIFIED_TOOLS
    assert planner.last_error is None
    assert planner.validation_error is None
    assert planner.dropped_args == []


@pytest.mark.parametrize("key", list(PARAMS))
def test_every_omitted_requested_argument_is_rejected(planner, monkeypatch, key):
    params = dict(PARAMS)
    del params[key]
    monkeypatch.setattr(planner, "_chat", lambda q, t: reply(args=params))
    plan = planner.plan(QUERY, {})
    assert plan.ambiguous and plan.calls == []
    assert planner.validation_error
    assert planner.last_error is None  # rejected proposal, not transport fallback


@pytest.mark.parametrize("key,value", [
    ("head_id", "H06"), ("machine_id", "mixed"), ("status_filter", 0),
    ("start", "2026-01-01T00:00:00"), ("end", "2026-03-01T00:00:00"),
    ("bins", 10), ("start", "today"), ("start", None), ("end", ""),
    ("start", "2026-02-01T00:00:00+02:00"), ("end", "2026-01-01T00:00:00"),
    ("status_filter", True), ("bins", True), ("bins", "3"),
    ("head_id", ["H05"]), ("status_filter", None),
])
def test_changed_or_invalid_values_are_never_repaired(planner, monkeypatch, key, value):
    params = dict(PARAMS, **{key: value})
    monkeypatch.setattr(planner, "_chat", lambda q, t: reply(args=params))
    plan = planner.plan(QUERY, {})
    assert plan.ambiguous and plan.calls == []
    assert planner.dropped_args == []


@pytest.mark.parametrize("key,value", [
    ("config", "null"), ("sigma", 1), ("window_seconds", 5),
    ("head", "H05"), ("events", None), ("colour", "red"),
])
def test_unknown_alias_and_configuration_arguments_reject_entire_proposal(planner, monkeypatch, key, value):
    monkeypatch.setattr(planner, "_chat", lambda q, t: reply(args=dict(PARAMS, **{key: value})))
    plan = planner.plan(QUERY, {})
    assert plan.ambiguous and plan.calls == []
    assert "Unsupported argument" in planner.validation_error


@pytest.mark.parametrize("bad_reply", [
    None, "bad", {}, {"message": []}, {"message": {"tool_calls": []}},
    {"message": {"tool_calls": "wrong"}},
    reply(name="invented"), reply(name="torque_stats"),
    reply(args="{broken"), reply(args="[]"), reply(args=[]),
    reply(args='{"bins":3,"bins":4}'),
    {"message": {"tool_calls": [{"function": {"name": "torque_distribution"}}]}},
    {"message": {"tool_calls": reply()["message"]["tool_calls"] * 2}},
])
def test_malformed_unknown_and_extra_calls_do_not_fall_back(planner, monkeypatch, bad_reply):
    monkeypatch.setattr(planner, "_chat", lambda q, t: bad_reply)
    plan = planner.plan(QUERY, {})
    assert plan.ambiguous and plan.calls == []
    assert planner.last_error is None
    assert planner.validation_error


def test_valid_json_arguments_are_accepted_without_coercion(planner, monkeypatch):
    monkeypatch.setattr(planner, "_chat", lambda q, t: reply(args=json.dumps(PARAMS)))
    assert planner.plan(QUERY, {}).calls == [("torque_distribution", PARAMS)]


def test_unsolicited_narrowing_is_rejected(planner, monkeypatch):
    monkeypatch.setattr(planner, "_chat", lambda q, t: reply("torque_stats", {"head_id": "H05"}))
    assert planner.plan("Average torque", {}).ambiguous is True


def test_required_comparison_heads_cannot_be_missing(planner, monkeypatch):
    monkeypatch.setattr(planner, "_chat", lambda q, t: reply("head_correlation", {"head_a": "H05"}))
    assert planner.plan("Compare torque between H05 and H06", {}).calls == []
    assert "Missing required" in planner.validation_error


@pytest.mark.parametrize("query", ["success rate", "What is torque doing?", "Average torque yesterday",
                                       "Compare torque between H05 and H06 for successful closures"])
def test_unverified_language_never_contacts_model(planner, monkeypatch, query):
    def chat(*args):
        pytest.fail("Model must not be contacted for an unverified scope")
    monkeypatch.setattr(planner, "_chat", chat)
    plan = planner.plan(query, {})
    assert plan.ambiguous and plan.calls == []


def test_model_prose_cannot_become_a_report_finding(planner, monkeypatch):
    monkeypatch.setattr(planner, "_chat", lambda q, t: reply(content="The machine is broken; replace the head."))
    plan = planner.plan(QUERY, {})
    assert "broken" not in plan.goal
    assert "replace" not in plan.goal


def test_transport_fallback_preserves_entire_scope(planner, monkeypatch):
    def offline(*args):
        raise ConnectionRefusedError("offline")
    monkeypatch.setattr(planner, "_chat", offline)
    plan = planner.plan(QUERY, {})
    assert plan.calls == [("torque_distribution", PARAMS)]
    assert "fell back to rules" in plan.rationale
    assert "ConnectionRefusedError" in planner.last_error
    assert planner.validation_error is None


def test_disabled_transport_fallback_raises(planner, monkeypatch):
    planner.fallback = False
    def offline(*args):
        raise TimeoutError("offline")
    monkeypatch.setattr(planner, "_chat", offline)
    with pytest.raises(TimeoutError):
        planner.plan(QUERY, {})


def test_state_does_not_leak_between_queries(planner, monkeypatch):
    monkeypatch.setattr(planner, "_chat", lambda q, t: reply(args={}))
    assert planner.plan(QUERY, {}).ambiguous
    monkeypatch.setattr(planner, "_chat", lambda q, t: reply())
    assert not planner.plan(QUERY, {}).ambiguous
    assert planner.validation_error is None and planner.last_error is None


@pytest.mark.parametrize("names,expected", [(["llama3.2:1b"], False), (["llama3.2:3b-extra"], False),
                                           (["llama3.2:3b"], True), ([], False)])
def test_available_checks_exact_model_tag(planner, monkeypatch, names, expected):
    import io
    import urllib.request
    planner.model = "llama3.2:3b"
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(json.dumps({"models": [{"name": n} for n in names]}).encode()))
    assert planner.available() is expected


@pytest.fixture
def engine(planner, tmp_path):
    import polars as pl
    from datetime import datetime
    events = pl.DataFrame({
        "ts": [datetime(2026, 2, 1, 1), datetime(2026, 2, 1, 2)],
        "machine_id": ["MiXeD"] * 2, "head_id": ["H05"] * 2,
        "torque": [1.9, 2.1], "status": [0, 0], "error_class": ["Closure OK"] * 2,
        "reject_signal": [False, False], "cap_present": [True, True],
    })
    path = write_event_table_parquet(events, tmp_path / "events.parquet")
    cfg = {"data": {"source": "person_a", "person_a": {"fixture": str(path)}}}
    return Orchestrator(cfg=cfg, planner=planner)


def test_accepted_llm_proposal_reaches_report(engine, planner, monkeypatch):
    monkeypatch.setattr(planner, "_chat", lambda q, t: reply())
    answer = engine.answer(QUERY, pool="fixture")
    assert answer["status"] == "ok"
    response = answer["results"][0][1]
    assert response["result"]["sample_size"] == 2
    assert response["meta"]["params"] == PARAMS
    assert answer["trace"].to_dict()["n_tool_calls"] == 1
    assert answer["trace"].planner == "llm"
    assert "torque_distribution" in answer["markdown"]


def test_rejected_proposal_cannot_load_data_or_call_tools(engine, planner, monkeypatch):
    monkeypatch.setattr(planner, "_chat", lambda q, t: reply(args={}))
    monkeypatch.setattr(engine.source, "load_pool", lambda p: pytest.fail("Must not load data"))
    answer = engine.answer(QUERY, pool="fixture")
    assert answer["status"] == "needs_clarification"
    assert answer["results"] == []
    trace = answer["trace"].to_dict()
    assert trace["n_tool_calls"] == 0
    assert any("LLM proposal rejected" in s.get("rationale", "") for s in trace["steps"])


def test_transport_fallback_is_labelled_in_actual_trace(engine, planner, monkeypatch):
    def offline(*args):
        raise ConnectionRefusedError("offline")
    monkeypatch.setattr(planner, "_chat", offline)
    answer = engine.answer(QUERY, pool="fixture")
    assert answer["status"] == "ok"
    assert answer["results"][0][1]["meta"]["params"] == PARAMS
    assert answer["trace"].planner == "llm->rules (fallback)"
