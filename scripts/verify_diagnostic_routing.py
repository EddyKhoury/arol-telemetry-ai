"""Measure catalogue routing and two real combined-analysis reports."""
import argparse
import hashlib
import json
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

from src.agent.diagnostic_queries import DIAGNOSTIC_QUERY_CASES
from src.agent.planner import RulePlanner
from src.agent.orchestrator import Orchestrator
from src.analytics.torque_stats import torque_stats
from src.analytics.torque_distribution import torque_distribution
from src.analytics.trend_analysis import torque_trend
from src.analytics.anomaly_detection import detect_torque_anomalies
from src.common import config, datasource
from src.common.envelope import jsonable
from src.ingestion.conversion import scan_csv_telemetry
from src.ingestion.event_table_polars import build_event_table_frame, EVENT_SCHEMA
from src.ingestion.event_pool import sha256_file
from scripts.verify_scoped_event_pool import equal

ROOT = Path(__file__).resolve().parents[1]
DEFERRED = {"head_behaves_differently", "why_head_failing"}


def evaluate_catalogue():
    rows = []
    for case in DIAGNOSTIC_QUERY_CASES:
        for question in case["questions"]:
            plan = RulePlanner().plan(question, {})
            if case["id"] in DEFERRED:
                assert plan.ambiguous and plan.calls == [], (question, plan)
                outcome = "needs_clarification"
            else:
                assert not plan.ambiguous
                assert [name for name, _ in plan.calls] == case["expected_tools"], (question, plan)
                for _, arguments in plan.calls:
                    for key, value in case.get("expected_arguments", {}).items():
                        assert arguments[key] == value
                outcome = "routed_to_expected_tools"
            rows.append({"family": case["id"], "question": question, "outcome": outcome,
                         "calls": plan.calls, "clarification": plan.clarification})
    return rows


def _digest(value):
    return hashlib.sha256(json.dumps(jsonable(value), sort_keys=True, allow_nan=False).encode()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != ROOT:
        parser.error("Run from the repository root")
    source_hashes = {str(path.relative_to(ROOT)): sha256_file(path)
                     for path in sorted((ROOT / "src").rglob("*.py"))}
    for name in ("scripts/verify_diagnostic_routing.py", "scripts/verify_scoped_event_pool.py"):
        source_hashes[name] = sha256_file(ROOT / name)
    state = {
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "git_status_before_run": subprocess.check_output(["git", "status", "--short"], text=True).strip(),
        "source_code_sha256": source_hashes,
    }
    catalogue = evaluate_catalogue()
    routed = sum(row["outcome"] == "routed_to_expected_tools" for row in catalogue)
    print(f"Catalogue: {routed}/{len(catalogue)} questions routed; {len(catalogue)-routed} require clarification.", flush=True)
    print("This is regression coverage of known questions, not held-out language accuracy.", flush=True)
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    machine = manifest["summary"]["machine_id"]
    first = manifest["partitions"][0]
    csv_path = ROOT / "data" / first["input_file"]
    if sha256_file(csv_path) != first["input_sha256"]:
        raise ValueError("Original CSV differs from the event-pool input")
    print("Building an independent scoped reference from the first original CSV...", flush=True)
    reference = build_event_table_frame(scan_csv_telemetry(csv_path), machine).filter(
        (pl.col("head_id") == "H05") & (pl.col("machine_id") == machine) & (pl.col("status") == 0)
        & (pl.col("ts") >= datetime(2026, 2, 1)) & (pl.col("ts") < datetime(2026, 2, 1, 12))
    ).collect()
    scope = dict(head_id="H05", machine_id=machine, start="2026-02-01T00:00:00",
                 end="2026-02-01T12:00:00", status_filter="successful")
    cfg = config.load()
    cfg["data"].update(source="person_a_pool", person_a={"full_pool": str(manifest_path)},
                       max_loaded_events=1_000_000, verify_pool_hashes=False)
    cfg.setdefault("agent", {}).update(planner="rules", max_steps=8)
    cases = [
        ("summary_and_distribution", "Summarize torque and show its distribution with 10 bins", [
            ("torque_stats", dict(scope), torque_stats(reference, status_filter="successful")),
            ("torque_distribution", dict(scope, bins=10), torque_distribution(reference, bins=10, status_filter="successful")),
        ]),
        ("trend_and_anomalies", "Check both torque trend and abnormal events", [
            ("torque_trend", dict(scope), torque_trend(reference, cfg, status_filter="successful")),
            ("detect_torque_anomalies", dict(scope), detect_torque_anomalies(reference, cfg, status_filter="successful")),
        ]),
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    run_dir = ROOT / "data/integration_smoke" / f"diagnostics-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    verified = []
    for index, (name, base, expected) in enumerate(cases, 1):
        question = (base + f" for machine {machine} from {scope['start']} until {scope['end']} "
                    "for head 5 for successful closures")
        print(f"{index}/2 Verifying {name}...", flush=True)
        case_cfg = deepcopy(cfg)
        case_cfg["agent"].update(report_dir=str(run_dir / name / "reports"), trace_dir=str(run_dir / name / "traces"))
        source = datasource.get_source(case_cfg)
        captured = []
        original_load = source.load_for_plan
        def recording_load(pool, calls):
            events, meta = original_load(pool, calls)
            captured.append(events.select(list(EVENT_SCHEMA)))
            return events, meta
        source.load_for_plan = recording_load
        engine = Orchestrator(cfg=case_cfg, source=source)
        answer = engine.answer(question, pool="full_pool")
        assert answer["status"] == "ok", answer.get("message")
        assert answer["plan"].calls == [(tool, params) for tool, params, _ in expected]
        assert len(captured) == 1
        assert_frame_equal(captured[0], reference)
        assert answer["pool_meta"]["loaded_events"] == len(reference)
        assert answer["pool_meta"]["pool_total_events"] == manifest["summary"]["observed_events"]
        assert answer["trace"].to_dict()["n_tool_calls"] == 2
        assert "must not be added" in answer["markdown"]
        assert len(answer["results"]) == len(expected) == 2
        tool_summaries = []
        for (tool, response), (expected_tool, params, result) in zip(answer["results"], expected):
            assert tool == expected_tool and response["ok"]
            assert response["meta"]["params"] == params
            equal(jsonable(response["result"]), jsonable(result))
            tool_summaries.append({"tool": tool, "parameters": params, "n": response["meta"]["n"],
                                   "complete_result_matches": True,
                                   "direct_result_sha256": _digest(result),
                                   "reported_result_sha256": _digest(response["result"])})
        artifacts = engine.deliver(answer, formats=["markdown"])
        detail = run_dir / name / "complete_results.json"
        detail.write_text(json.dumps(jsonable({"direct": expected, "reported": answer["results"]}),
                                     indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts["complete_results"] = str(detail)
        verified.append({"case": name, "question": question, "loaded_events": len(reference),
                         "pool_total_events": manifest["summary"]["observed_events"],
                         "field_parity": True, "source_load_calls": 1, "tool_calls": 2,
                         "tools": tool_summaries, "details_sha256": sha256_file(detail),
                         "artifacts": {key: Path(path).relative_to(ROOT).as_posix() for key,path in artifacts.items()}})
        print(f"    PASS: one scoped load ({len(reference):,} events), two tools, both complete results match.", flush=True)
    if any(sha256_file(ROOT / name) != value for name,value in source_hashes.items()):
        raise RuntimeError("Source changed during verification")
    evidence = {
        **state, "manifest": manifest_path.relative_to(ROOT).as_posix(), "manifest_sha256": sha256_file(manifest_path),
        "catalogue_questions": len(catalogue), "routed_to_original_expected_tools": routed,
        "deferred_questions": len(catalogue)-routed, "deferred_families": sorted(DEFERRED),
        "catalogue": catalogue, "real_combined_queries": verified,
        "planner": "rules", "live_model_requests": 0, "verified": True,
        "float_tolerance": {"relative": 1e-12, "absolute": 1e-12},
        "limits": ["Known-catalogue regression, not held-out language understanding accuracy.",
                   "Six original diagnostic questions remain deferred and request clarification.",
                   "LLM combined-analysis routing remains blocked before inference; one-tool validation is unchanged.",
                   "Real checks use one specified H05/machine/time/status selection from the full configured pool.",
                   "Tool sample counts can describe the same observations and are not additive.",
                   "No failure-cause, engineering-compliance, production-completeness or measured peak-memory claim."],
    }
    output = ROOT / "benchmarks/integration" / f"diagnostic_routing_{stamp}.json"
    output.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    heading = f"## Integration measurement — diagnostic routing {stamp}"
    entry = (heading + f"\n\n- Known catalogue: {routed}/{len(catalogue)} routed to original expected tools.\n"
             f"- Remaining {len(catalogue)-routed} questions require clarification; their diagnostic features are deferred.\n"
             "- Two real combined queries passed: statistics/distribution and trend/anomalies.\n"
             "- Each used one scoped load, preserved all eight event fields, and executed two tools.\n"
             "- Complete results matched direct calculations with 1e-12 relative/absolute float tolerance.\n"
             "- Combined LLM proposals remain blocked before inference; no new live model requests.\n"
             f"- Evidence: {output.relative_to(ROOT).as_posix()}.\n\n"
             "Limits: this is known-question regression coverage and one real scope, not held-out accuracy or root-cause validation.\n\n"
             "Next action: record regression results, then resolve KPI denominator semantics and remaining diagnostic requirements.\n")
    for name in ("PROJECT-AUDIT.md", "INTEGRATION-TRACKER.md"):
        path = ROOT / "docs" / name
        text = path.read_text(encoding="utf-8")
        if heading not in text:
            path.write_text(text.rstrip() + "\n\n" + entry, encoding="utf-8")
    print("\nDIAGNOSTIC ROUTING VERIFICATION COMPLETE")
    print(json.dumps({"catalogue_routed": routed, "catalogue_total": len(catalogue),
                      "needs_clarification": len(catalogue)-routed, "real_combined_queries_verified": len(verified),
                      "live_model_requests": 0}, indent=2))
    print(f"Evidence: {output.relative_to(ROOT).as_posix()}")
    print("Updated both audit documents. Run git status --short.")


if __name__ == "__main__":
    main()
