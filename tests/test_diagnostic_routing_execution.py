"""Execute diagnostic catalogue plans instead of checking only list structure."""
from datetime import datetime, timedelta

import polars as pl
import pytest

from src.agent.diagnostic_queries import DIAGNOSTIC_QUERY_CASES
from src.agent.planner import RulePlanner, LLMPlanner, Plan
from src.agent.orchestrator import Orchestrator
from src.common.runtime import dispatch_tool
from src.ingestion.event_pool import build_event_pool
from src.ingestion.event_table_polars import build_event_table, write_event_table_parquet

DEFERRED = {"head_behaves_differently", "why_head_failing"}
CATALOGUE = [(case, question) for case in DIAGNOSTIC_QUERY_CASES for question in case["questions"]]


@pytest.mark.parametrize("case,question", CATALOGUE, ids=[f"{c['id']}-{i}" for i, (c, _) in enumerate(CATALOGUE)])
def test_actual_planner_outcome_for_each_catalogue_question(case, question):
    plan = RulePlanner().plan(question, {})
    if case["id"] in DEFERRED:
        assert plan.ambiguous and plan.calls == []
        assert "baseline" in plan.clarification
    else:
        assert plan.ambiguous is False
        assert [name for name, _ in plan.calls] == case["expected_tools"]
        for _, params in plan.calls:
            for key, value in case.get("expected_arguments", {}).items():
                assert params[key] == value


@pytest.mark.parametrize("question", [
    "Give me a summary of closure torque",
    "How is torque distributed",
    "Is torque drifting over time",
    "Find anomalous closures",
    "Summarize torque and show its distribution",
    "Is torque drifting and are there anomalies",
])
def test_alias_and_combination_scope_is_preserved_in_every_call(question):
    query = (question + " for head 5 for machine MiXeD_01 from 2026-02-01T00:00:00 "
             "until 2026-02-01T12:00:00 for successful closures")
    expected = dict(head_id="H05", machine_id="MiXeD_01", start="2026-02-01T00:00:00",
                    end="2026-02-01T12:00:00", status_filter="successful")
    plan = RulePlanner().plan(query, {})
    assert not plan.ambiguous
    assert all(params == expected for _, params in plan.calls)


def test_combined_histogram_bins_apply_only_to_distribution():
    plan = RulePlanner().plan("Summarize torque and show its distribution with 7 bins for head 5", {})
    assert plan.calls == [("torque_stats", {"head_id": "H05"}),
                          ("torque_distribution", {"head_id": "H05", "bins": 7})]


@pytest.mark.parametrize("query", [
    "Give me a summary of closure torque excluding status 65",
    "Find anomalous closures yesterday",
    "Does H01 behave like H05 for successful closures",
    "Compare H01 and H01",
    "What is different between head H01 and H05 and H06",
    "Show torque statistics only for good closures for status 65",
    "How does torque look when status is successful for all closures",
    "Summarize torque and show its distribution with 0 bins",
    "Summarize torque and show its distribution with 7 bins with 8 bins",
    "Summarize torque and show its distribution for head 5 for head 6",
    "Is torque drifting and are there anomalies with sigma 7",
    "Is torque drifting and are there anomalies with 7 bins",
    "Check both torque trend and abnormal events except head 5",
    "Do we have a drift problem or isolated outliers from 2026-02-02 until 2026-02-01",
    "Summarize torque and show its distribution for machine null",
    "Summarize torque and show its distribution from 2026-02-01T00:00:00Z until 2026-02-02T00:00:00Z",
])
def test_unconsumed_or_conflicting_scope_remains_blocked(query):
    plan = RulePlanner().plan(query, {})
    assert plan.ambiguous and not plan.calls


@pytest.fixture
def fixture_data(tmp_path):
    raw = pl.DataFrame({
        "timestamp": [datetime(2026, 2, 1) + timedelta(seconds=i) for i in range(7)],
        "H01 Count": list(range(10, 17)), "H05 Count": list(range(20, 27)),
        "H01 AppTorque": [0., 1., 2., 3., 4., 5., 6.],
        "H05 AppTorque": [0., 1.5, 99., 2., 2.5, 3., 3.5],
        "H01 Status": [0, 0, 0, 65, 0, 3, 0],
        "H05 Status": [0, 0, 65, 0, 0, 0, 0],
    })
    paths = []
    for i, frame in enumerate([raw[:3], raw[3:]]):
        path = tmp_path / f"raw-{i}.csv"
        frame.write_csv(path)
        paths.append(path)
    manifest = build_event_pool(paths, tmp_path / "pool", machine_id="M1")
    events = build_event_table(raw, "M1")
    single = write_event_table_parquet(events, tmp_path / "single.parquet")
    configs = {}
    for source, path in [("person_a", single), ("person_a_pool", manifest)]:
        configs[source] = {
            "data": {"source": source, "person_a": {"fixture": str(path)}},
            "agent": {"planner": "rules"},
            "analytics": {"torque_expected_min": 1.5, "torque_expected_max": 2.5,
                          "drift_window_seconds": 3, "anomaly_sigma": 3.0},
        }
    return configs, events


@pytest.mark.parametrize("source", ["person_a", "person_a_pool"])
@pytest.mark.parametrize("question,tools", [
    ("Summarize torque and show its distribution", ["torque_stats", "torque_distribution"]),
    ("Check both torque trend and abnormal events", ["torque_trend", "detect_torque_anomalies"]),
])
def test_combined_question_executes_both_results_with_the_same_scope(fixture_data, source, question, tools):
    configs, events = fixture_data
    cfg = configs[source]
    query = (question + " for head 5 for machine M1 from 2026-02-01T00:00:00 "
             "until 2026-02-01T00:00:05 for successful closures")
    answer = Orchestrator(cfg=cfg).answer(query)
    assert answer["status"] == "ok"
    assert [name for name, _ in answer["results"]] == tools
    assert answer["trace"].to_dict()["n_tool_calls"] == 2
    expected_scope = {"head_id": "H05", "machine_id": "M1", "start": "2026-02-01T00:00:00",
                      "end": "2026-02-01T00:00:05", "status_filter": "successful"}
    for name, response in answer["results"]:
        direct = dispatch_tool(name, events, config=cfg, arguments=expected_scope)
        assert response["ok"] and direct["ok"]
        assert response["result"] == direct["result"]
        assert response["meta"]["params"] == expected_scope
        assert response["meta"]["n"] == 3
        assert f"**{name}**" in answer["markdown"]
    assert "must not be added" in answer["markdown"]
    if source == "person_a_pool":
        assert answer["pool_meta"]["loaded_events"] == 3
        assert len(answer["pool_meta"]["planned_calls"]) == 2


def test_combined_source_rejects_different_scopes(fixture_data):
    configs, _ = fixture_data
    engine = Orchestrator(cfg=configs["person_a_pool"])
    with pytest.raises(ValueError, match="exactly the same"):
        engine.source.load_for_plan("fixture", [("torque_stats", {"head_id": "H01"}),
                                                ("torque_distribution", {"head_id": "H05"})])


def test_combined_source_rejects_different_status_scopes(fixture_data):
    configs, _ = fixture_data
    engine = Orchestrator(cfg=configs["person_a_pool"])
    with pytest.raises(ValueError, match="exactly the same"):
        engine.source.load_for_plan("fixture", [("torque_trend", {"status_filter": "successful"}),
                                                ("detect_torque_anomalies", {})])


def test_tool_budget_does_not_silently_truncate_combined_analysis(fixture_data):
    configs, _ = fixture_data
    cfg = configs["person_a_pool"]
    cfg["agent"]["max_steps"] = 1
    answer = Orchestrator(cfg=cfg).answer("Summarize torque and show its distribution")
    assert answer["status"] == "needs_clarification"
    assert answer["results"] == []
    assert answer["trace"].to_dict()["n_tool_calls"] == 0
    assert not any(step["kind"] == "load_pool" for step in answer["trace"].steps)


@pytest.mark.parametrize("case,question", [(c,q) for c,q in CATALOGUE if c["id"] in DEFERRED])
def test_deferred_diagnostics_stop_before_loading(fixture_data, case, question, monkeypatch):
    configs, _ = fixture_data
    engine = Orchestrator(cfg=configs["person_a_pool"])
    def forbidden(*args, **kwargs):
        raise AssertionError("Unspecified diagnostic must not load events")
    monkeypatch.setattr(engine.source, "load_for_plan", forbidden)
    answer = engine.answer(question)
    assert answer["status"] == "needs_clarification"
    assert answer["trace"].to_dict()["n_tool_calls"] == 0


@pytest.mark.parametrize("question", ["Summarize torque and show its distribution",
                                      "Is torque drifting and are there anomalies"])
def test_llm_combined_analysis_is_blocked_before_inference(question, monkeypatch):
    planner = LLMPlanner({"agent": {"llm": {"fallback_to_rules": False}}})
    def forbidden(*args, **kwargs):
        raise AssertionError("Combined LLM routing is not verified")
    monkeypatch.setattr(planner, "_chat", forbidden)
    plan = planner.plan(question, {})
    assert plan.ambiguous and not plan.calls
    assert "rules" in plan.clarification
    assert planner.last_error is None


def test_single_diagnostic_alias_still_requires_exact_llm_scope(monkeypatch):
    planner = LLMPlanner({"agent": {"llm": {"fallback_to_rules": False}}})
    monkeypatch.setattr(planner, "_chat", lambda *args: {
        "message": {"tool_calls": [{"function": {
            "name": "torque_stats", "arguments": {"head_id": "H05"},
        }}]},
    })
    query = "Give me a summary of closure torque for head 5"
    assert planner.plan(query, {}).calls == [("torque_stats", {"head_id": "H05"})]
    assert planner.plan(query + " for successful closures", {}).ambiguous
