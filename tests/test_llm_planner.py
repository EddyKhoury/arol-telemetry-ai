"""The LLM planner, tested without a model present.

Every test here fakes the HTTP call, so the suite runs on a machine with no
Ollama installed and no network. What is being tested is the wiring: that
tool specs reach the model in the right shape, that a reply becomes a Plan,
that a small model's mistakes are absorbed rather than propagated, and that
a dead server degrades to the keyword planner instead of losing the answer.
"""

import pytest

from src.agent.planner import LLMPlanner, RulePlanner, _to_ollama_tools
from src.analytics import kpi  # noqa: F401 - registers the tools
from src.common import registry as R


@pytest.fixture
def planner(cfg):
    cfg["agent"]["llm"] = {"host": "http://localhost:11434",
                           "model": "llama3.2:3b", "temperature": 0.0,
                           "seed": 42, "timeout_seconds": 5,
                           "fallback_to_rules": True}
    return LLMPlanner(cfg)


def _ollama_is_running(host="http://localhost:11434") -> bool:
    """Probe used only to skip the one live test below."""
    import urllib.request
    try:
        urllib.request.urlopen(f"{host}/api/tags", timeout=2).read()
        return True
    except Exception:
        return False


def _reply(tool_calls=None, content=""):
    return {"message": {"content": content, "tool_calls": tool_calls or []}}


def _call(name, arguments):
    return {"function": {"name": name, "arguments": arguments}}


# --- the tool catalogue handed to the model -------------------------------

def test_tool_specs_convert_to_the_ollama_function_shape():
    tools = _to_ollama_tools(R.get_tool_specs())
    assert tools, "no tools registered"
    for tool in tools:
        assert tool["type"] == "function"
        function = tool["function"]
        assert function["name"] and function["description"]
        assert function["parameters"]["type"] == "object"


def test_every_registered_tool_is_offered_to_the_model():
    offered = {t["function"]["name"] for t in _to_ollama_tools(R.get_tool_specs())}
    assert offered == set(R.list_tools())


# --- a normal reply becomes a Plan ----------------------------------------

def test_a_tool_call_becomes_a_plan(planner, monkeypatch):
    monkeypatch.setattr(planner, "_chat", lambda q, t: _reply(
        [_call("success_rate_per_head", {})], "Rank the heads."))
    plan = planner.plan("which head is performing worst?", {})
    assert plan.ambiguous is False
    assert plan.calls == [("success_rate_per_head", {})]
    assert plan.goal == "Rank the heads."


def test_arguments_are_passed_through(planner, monkeypatch):
    monkeypatch.setattr(planner, "_chat", lambda q, t: _reply(
        [_call("idle_periods", {"head_id": "H05", "window_seconds": 600})]))
    plan = planner.plan("idle on head 5 over 10 minutes", {})
    assert plan.calls == [("idle_periods", {"head_id": "H05",
                                            "window_seconds": 600})]


def test_arguments_may_arrive_as_a_json_string(planner, monkeypatch):
    """Some models return `arguments` already serialised."""
    monkeypatch.setattr(planner, "_chat", lambda q, t: _reply(
        [_call("success_rate", '{"bucket": "day"}')]))
    assert planner.plan("kpis per day", {}).calls == [("success_rate",
                                                       {"bucket": "day"})]


def test_several_tools_are_kept_in_order(planner, monkeypatch):
    monkeypatch.setattr(planner, "_chat", lambda q, t: _reply(
        [_call("anomaly_heads", {}), _call("success_rate_per_head", {})]))
    assert [n for n, _ in planner.plan("anything wrong?", {}).calls] == \
        ["anomaly_heads", "success_rate_per_head"]


# --- a small model's mistakes are absorbed --------------------------------

def test_an_invented_tool_is_dropped(planner, monkeypatch):
    """A 3B model will occasionally hallucinate a tool name."""
    monkeypatch.setattr(planner, "_chat", lambda q, t: _reply(
        [_call("head_statistics_v2", {}), _call("success_rate", {})]))
    assert planner.plan("kpis", {}).calls == [("success_rate", {})]


def test_an_invented_parameter_is_dropped(planner, monkeypatch):
    monkeypatch.setattr(planner, "_chat", lambda q, t: _reply(
        [_call("success_rate", {"bucket": "day", "colour": "red"})]))
    assert planner.plan("kpis per day", {}).calls == [("success_rate",
                                                       {"bucket": "day"})]


def test_an_alias_is_normalised(planner, monkeypatch):
    """'head' instead of 'head_id' must not cost a wasted step."""
    monkeypatch.setattr(planner, "_chat", lambda q, t: _reply(
        [_call("idle_periods", {"head": "H03"})]))
    assert planner.plan("idle on head 3", {}).calls == [("idle_periods",
                                                         {"head_id": "H03"})]


def test_empty_arguments_are_stripped(planner, monkeypatch):
    monkeypatch.setattr(planner, "_chat", lambda q, t: _reply(
        [_call("success_rate", {"start": None, "end": "", "bucket": "hour"})]))
    assert planner.plan("hourly kpis", {}).calls == [("success_rate",
                                                      {"bucket": "hour"})]


def test_no_tool_selected_asks_for_clarification(planner, monkeypatch):
    monkeypatch.setattr(planner, "_chat", lambda q, t: _reply(
        [], "I can only answer questions about capping telemetry."))
    plan = planner.plan("what is the weather", {})
    assert plan.ambiguous is True
    assert "capping telemetry" in plan.clarification


# --- the fallback ---------------------------------------------------------

def test_a_dead_server_falls_back_to_the_rule_planner(planner, monkeypatch):
    """No Ollama running is the normal case on a fresh machine, and during
    the demo it is the difference between an answer and a dead screen."""
    def boom(query, tools):
        raise ConnectionRefusedError("[Errno 111] Connection refused")
    monkeypatch.setattr(planner, "_chat", boom)

    plan = planner.plan("is anything wrong with the machine?", {})
    assert plan.ambiguous is False
    assert [n for n, _ in plan.calls] == ["anomaly_heads", "success_rate_per_head"]
    assert "fell back to rules" in plan.rationale
    assert "ConnectionRefusedError" in planner.last_error


def test_the_fallback_can_be_switched_off(cfg, monkeypatch):
    cfg["agent"]["llm"] = {"fallback_to_rules": False, "timeout_seconds": 1}
    planner = LLMPlanner(cfg)
    monkeypatch.setattr(planner, "_chat",
                        lambda q, t: (_ for _ in ()).throw(TimeoutError("slow")))
    with pytest.raises(TimeoutError):
        planner.plan("kpis", {})


def test_available_is_false_when_nothing_is_listening(cfg):
    """Real call, no mock. Port 1 is privileged and never has a server on it,
    so this holds whether or not Ollama is installed - the earlier version
    asserted "no Ollama on this machine" and started failing the day one was.
    """
    cfg["agent"]["llm"] = {"host": "http://localhost:1", "model": "llama3.2:3b",
                           "timeout_seconds": 2, "fallback_to_rules": True}
    assert LLMPlanner(cfg).available() is False


@pytest.mark.skipif(not _ollama_is_running(),
                    reason="no local Ollama; the mocked tests cover the wiring")
def test_available_is_true_against_a_real_server(planner):
    """The live counterpart. Skipped on a machine without Ollama, so CI and a
    fresh clone stay green, but it proves the probe on the demo machine."""
    assert planner.available() is True


def test_a_malformed_reply_falls_back(planner, monkeypatch):
    monkeypatch.setattr(planner, "_chat", lambda q, t: "not a dict at all")
    plan = planner.plan("kpis", {})
    assert "fell back to rules" in plan.rationale


# --- the orchestrator does not care which planner it got ------------------

def test_the_orchestrator_accepts_an_llm_planner(cfg, monkeypatch):
    from src.agent.orchestrator import Orchestrator

    cfg["agent"]["llm"] = {"fallback_to_rules": True, "timeout_seconds": 1}
    planner = LLMPlanner(cfg)
    monkeypatch.setattr(planner, "_chat", lambda q, t: _reply(
        [_call("success_rate", {})], "Summarise performance."))

    answer = Orchestrator(cfg, planner=planner).answer("how is it doing?")
    assert answer["status"] == "ok"
    assert "## 4. Findings" in answer["markdown"]
    assert answer["trace"].planner == "llm"


def test_a_fallback_is_visible_in_the_report(cfg, monkeypatch):
    """The header names the planner. If the model was unavailable and the
    keyword rules answered, the report must say so rather than claim the
    model produced it."""
    from src.agent.orchestrator import Orchestrator

    cfg["agent"]["llm"] = {"fallback_to_rules": True, "timeout_seconds": 1}
    planner = LLMPlanner(cfg)
    monkeypatch.setattr(planner, "_chat", lambda q, t: (_ for _ in ()).throw(
        ConnectionRefusedError("nothing listening")))

    answer = Orchestrator(cfg, planner=planner).answer("is anything wrong?")
    assert answer["status"] == "ok"                      # still answered
    assert "fallback" in answer["markdown"]              # and admitted it
    assert any("unavailable" in n for n in answer["trace"].notes)
