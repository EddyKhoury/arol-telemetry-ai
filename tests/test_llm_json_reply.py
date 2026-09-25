"""JSON-text transport support must not loosen argument or scope validation."""
from copy import deepcopy
import json
import pytest

from src.agent.planner import LLMPlanner
from src.agent.llm_validation import strict_calls
from src.common import registry

QUERY = ("Average torque for machine MCC777eda3db57348ef8a3113a642ae74db "
         "from 2026-02-01T00:00:00 until 2026-02-01T12:00:00 "
         "for head 5 for successful closures")
PARAMS = {"end": "2026-02-01T12:00:00", "head_id": "H05",
          "machine_id": "MCC777eda3db57348ef8a3113a642ae74db",
          "start": "2026-02-01T00:00:00", "status_filter": "successful"}
PROPOSAL = {"name": "torque_stats", "arguments": PARAMS}


def plan_for(monkeypatch, message, query=QUERY):
    planner = LLMPlanner({"agent": {"llm": {"fallback_to_rules": False}}})
    monkeypatch.setattr(planner, "_chat", lambda q, t: {"message": deepcopy(message)})
    return planner.plan(query, {}), planner


@pytest.mark.parametrize("style", ["plain", "json_fence", "bare_fence", "empty_native"])
def test_complete_json_proposal_passes_existing_scope_guard(monkeypatch, style):
    content = json.dumps(PROPOSAL)
    if style == "json_fence":
        content = "```json\n" + content + "\n```"
    elif style == "bare_fence":
        content = "```\n" + content + "\n```"
    message = {"content": content}
    if style == "empty_native":
        message["tool_calls"] = []
    before = deepcopy(message)
    plan, planner = plan_for(monkeypatch, message)
    assert not plan.ambiguous
    assert plan.calls == [("torque_stats", PARAMS)]
    assert planner.validation_error is None
    assert planner.last_error is None
    assert message == before


def test_observed_qwen_simple_placeholders_remain_rejected(monkeypatch):
    proposal = {"name": "torque_stats", "arguments": {
        "end": "", "head_id": "", "machine_id": "", "start": "", "status_filter": "successful",
    }}
    plan, planner = plan_for(monkeypatch, {"content": "```json\n" + json.dumps(proposal) + "\n```"}, "Average torque")
    assert plan.ambiguous and plan.calls == []
    assert planner.validation_error


@pytest.mark.parametrize("content", [
    "Here is the proposal: " + json.dumps(PROPOSAL),
    json.dumps(PROPOSAL) + "\nThe head is broken.",
    json.dumps(PROPOSAL) + "\n" + json.dumps(PROPOSAL),
    "```json\n" + json.dumps(PROPOSAL) + "\n```\nExtra explanation",
    "```python\n" + json.dumps(PROPOSAL) + "\n```",
    json.dumps([PROPOSAL]), "null", "42", "{broken",
    '{"name":"torque_stats","name":"torque_trend","arguments":{}}',
    '{"name":"torque_stats","arguments":{"head_id":"H05","head_id":"H06"}}',
    json.dumps(dict(PROPOSAL, explanation="a diagnosis")),
    json.dumps({"name": "torque_stats"}),
])
def test_ambiguous_or_embedded_json_is_rejected(monkeypatch, content):
    plan, planner = plan_for(monkeypatch, {"content": content})
    assert plan.ambiguous and plan.calls == []
    assert planner.last_error is None


@pytest.mark.parametrize("change", [
    {"status_filter": "0"}, {"head_id": "H06"}, {"machine_id": "other"},
    {"start": "null"}, {"start": "2026-01-01T00:00:00"},
    {"end": None}, {"config": "null"}, {"window_seconds": 5},
])
def test_json_transport_never_repairs_bad_or_changed_scope(monkeypatch, change):
    proposal = dict(PROPOSAL, arguments=dict(PARAMS, **change))
    plan, _ = plan_for(monkeypatch, {"content": json.dumps(proposal)})
    assert plan.ambiguous and plan.calls == []


def test_omitted_scope_in_json_still_rejected(monkeypatch):
    proposal = dict(PROPOSAL, arguments={})
    plan, _ = plan_for(monkeypatch, {"content": json.dumps(proposal)})
    assert plan.ambiguous and plan.calls == []


def test_unsolicited_status_in_json_still_rejected(monkeypatch):
    proposal = {"name": "torque_stats", "arguments": {"status_filter": "successful"}}
    plan, _ = plan_for(monkeypatch, {"content": json.dumps(proposal)}, "Average torque")
    assert plan.ambiguous and plan.calls == []


def test_string_bins_are_not_coerced_from_json(monkeypatch):
    proposal = {"name": "torque_distribution", "arguments": {"bins": "10"}}
    plan, _ = plan_for(monkeypatch, {"content": json.dumps(proposal)}, "Show torque distribution with 10 bins")
    assert plan.ambiguous and plan.calls == []


def test_native_calls_keep_their_original_validation(monkeypatch):
    # Valid text must not rescue a malformed native call.
    message = {"content": json.dumps(PROPOSAL), "tool_calls": [
        {"function": {"name": "torque_stats", "arguments": {}}},
    ]}
    plan, _ = plan_for(monkeypatch, message)
    assert plan.ambiguous and plan.calls == []


def test_non_list_native_calls_cannot_be_replaced_by_text(monkeypatch):
    plan, _ = plan_for(monkeypatch, {"content": json.dumps(PROPOSAL), "tool_calls": {}})
    assert plan.ambiguous and plan.calls == []


def test_native_prose_is_still_ignored_not_used_as_an_additional_call(monkeypatch):
    message = {"content": "The machine is broken.", "tool_calls": [{"function": PROPOSAL}]}
    plan, _ = plan_for(monkeypatch, message)
    assert not plan.ambiguous
    assert "broken" not in plan.goal


def test_format_adaptation_is_lossless():
    result = strict_calls({"content": json.dumps(PROPOSAL)}, registry.get)
    assert result == [("torque_stats", PARAMS)]
