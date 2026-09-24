"""Verify real scoped orchestration against an independent two-CSV reference."""
import argparse
import json
import math
import subprocess
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

from src.agent.orchestrator import Orchestrator
from src.analytics.torque_stats import torque_stats
from src.analytics.head_correlation import head_correlation
from src.common import config, datasource
from src.common.envelope import jsonable
from src.ingestion.conversion import scan_csv_telemetry
from src.ingestion.event_table_polars import build_event_table_frame, EVENT_SCHEMA
from src.ingestion.event_pool import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def equal(actual, expected, path="result"):
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise AssertionError(f"{path}: dictionary keys differ")
        for key in expected:
            equal(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise AssertionError(f"{path}: list lengths differ")
        for index, (left, right) in enumerate(zip(actual, expected)):
            equal(left, right, f"{path}[{index}]")
    elif isinstance(expected, float):
        if not isinstance(actual, (int, float)) or not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
            raise AssertionError(f"{path}: numerical values differ: {actual!r}, {expected!r}")
    elif actual != expected:
        raise AssertionError(f"{path}: {actual!r} != {expected!r}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != ROOT:
        parser.error("Run from the repository root")
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    machine = manifest["summary"]["machine_id"]
    if len(manifest["partitions"]) < 2:
        parser.error("At least two input files are required for boundary verification")
    first_two = manifest["partitions"][:2]
    source_hashes = {str(p.relative_to(ROOT)): sha256_file(p) for p in sorted((ROOT / "src").rglob("*.py"))}
    source_hashes["scripts/verify_scoped_event_pool.py"] = sha256_file(Path(__file__))
    code_state = {
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "git_status_before_run": subprocess.check_output(["git", "status", "--short"], text=True).strip(),
        "source_code_sha256": source_hashes,
    }
    print("Loading the first two original CSVs for an independent continuous reference...", flush=True)
    raw_frames = []
    for entry in first_two:
        path = ROOT / "data" / entry["input_file"]
        if sha256_file(path) != entry["input_sha256"]:
            raise ValueError(f"Original CSV differs from the built pool: {path.name}")
        raw_frames.append(scan_csv_telemetry(path).collect())
    raw = pl.concat(raw_frames, how="vertical_relaxed")
    del raw_frames
    base_reference = build_event_table_frame(raw, machine)
    boundary_time = datetime.fromisoformat(first_two[1]["ts_min"])
    boundary_start = (boundary_time - timedelta(seconds=2)).isoformat()
    boundary_end = (boundary_time + timedelta(seconds=3)).isoformat()
    cases = [
        ("known_scoped_stats", "torque_stats", {
            "head_id": "H05", "machine_id": machine,
            "start": "2026-02-01T00:00:00", "end": "2026-02-01T12:00:00",
            "status_filter": "successful",
        }),
        ("file_boundary_stats", "torque_stats", {
            "machine_id": machine, "start": boundary_start, "end": boundary_end,
        }),
        ("scoped_head_comparison", "head_correlation", {
            "head_a": "H05", "head_b": "H06", "machine_id": machine,
            "start": "2026-02-01T00:00:00", "end": "2026-02-01T12:00:00",
        }),
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    run_dir = ROOT / "data/integration_smoke" / f"scoped-pool-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    cfg = config.load()
    cfg["data"].update(source="person_a_pool", person_a={"full_pool": str(manifest_path)},
                       max_loaded_events=1_000_000, verify_pool_hashes=False)
    cfg.setdefault("agent", {})["planner"] = "rules"
    results = []
    for index, (case, tool, params) in enumerate(cases, 1):
        query = ("Average torque" if tool == "torque_stats" else "Compare torque between H05 and H06")
        query += f" for machine {machine} from {params['start']} until {params['end']}"
        if "head_id" in params:
            query += " for head 5 for successful closures"
        print(f"{index}/3 {case}: {query}", flush=True)
        # Reference selection does not use the source or shared filter helper.
        reference = base_reference.filter(
            (pl.col("machine_id") == machine)
            & (pl.col("ts") >= datetime.fromisoformat(params["start"]))
            & (pl.col("ts") < datetime.fromisoformat(params["end"]))
        )
        if "head_id" in params:
            reference = reference.filter((pl.col("head_id") == "H05") & (pl.col("status") == 0))
        if tool == "head_correlation":
            reference = reference.filter(pl.col("head_id").is_in(["H05", "H06"]))
        expected_events = reference.collect()
        expected = (torque_stats(expected_events, status_filter=params.get("status_filter"))
                    if tool == "torque_stats" else head_correlation(expected_events, "H05", "H06"))
        case_cfg = deepcopy(cfg)
        case_cfg["agent"].update(report_dir=str(run_dir / case / "reports"),
                                 trace_dir=str(run_dir / case / "traces"))
        source = datasource.get_source(case_cfg)
        loaded = []
        original_load = source.load_for_plan
        def recording_load(pool, calls):
            events, meta = original_load(pool, calls)
            loaded.append(events.select(list(EVENT_SCHEMA)))
            return events, meta
        source.load_for_plan = recording_load
        engine = Orchestrator(cfg=case_cfg, source=source)
        answer = engine.answer(query, pool="full_pool")
        if answer["status"] != "ok":
            raise AssertionError(f"{case}: {answer['status']}: {answer.get('message')}; {answer.get('results')}")
        if answer["plan"].calls != [(tool, params)]:
            raise AssertionError(f"{case}: planned scope changed")
        assert len(loaded) == 1
        assert_frame_equal(loaded[0], expected_events)
        result = answer["results"][0][1]
        equal(jsonable(result["result"]), jsonable(expected))
        assert answer["trace"].to_dict()["n_tool_calls"] == 1
        assert answer["pool_meta"]["loaded_events"] == len(expected_events)
        assert answer["pool_meta"]["pool_total_events"] == manifest["summary"]["observed_events"]
        if case == "known_scoped_stats":
            assert result["result"]["sample_size"] == 7575
        boundary_count = None
        if case == "file_boundary_stats":
            boundary_count = loaded[0].filter(pl.col("ts") == boundary_time).height
            assert boundary_count == first_two[1]["boundary_counts"]["exact_plus_one"]
        artifacts = engine.deliver(answer, formats=["markdown"])
        results.append({
            "case": case, "query": query, "tool": tool, "parameters": params,
            "loaded_events": len(expected_events), "pool_total_events": answer["pool_meta"]["pool_total_events"],
            "full_event_field_parity": True, "complete_result_matches": True,
            "sample_n": result["meta"]["n"], "boundary_events": boundary_count,
            "direct_result": jsonable(expected), "reported_result": result["result"],
            "trace_planner": answer["trace"].planner, "tool_calls": 1,
            "artifacts": {key: Path(value).relative_to(ROOT).as_posix() for key, value in artifacts.items()},
        })
        print(f"    PASS: loaded {len(expected_events):,} of {manifest['summary']['observed_events']:,}; fields and result match", flush=True)
        del loaded, expected_events
    if any(sha256_file(ROOT / name) != value for name, value in source_hashes.items()):
        raise RuntimeError("Source code changed during verification")
    evidence = {
        **code_state, "manifest": str(manifest_path.relative_to(ROOT)),
        "manifest_sha256": sha256_file(manifest_path), "verified": True,
        "planner": "rules", "live_model_requests": 0, "results": results,
        "float_tolerance": {"relative": 1e-12, "absolute": 1e-12},
        "limits": ["Three specified queries, with a reference built from the first two original CSVs.",
                   "The complete event pool is configured; only matching event rows are collected by the agent source.",
                   "All partition schemas are checked; physical reads depend on Parquet predicate pushdown.",
                   "Peak memory and runtime performance were not benchmarked.",
                   "Hash checks for all event partitions were disabled; source checks manifest and file stat stability.",
                   "No live LLM request, reconstructed closure, or production-completeness claim."],
    }
    output = ROOT / "benchmarks/integration" / f"scoped_event_pool_{stamp}.json"
    output.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    heading = f"## Integration measurement — scoped event-pool orchestration {stamp}"
    entry = (heading + "\n\n- Three deterministic real-data queries passed.\n"
             "- Scoped statistics, file-boundary statistics, and head comparison matched an independently filtered two-CSV reference.\n"
             "- All eight original event fields were compared; each request executed one tool.\n"
             "- Agent source collected only the requested scope from the configured full event pool.\n"
             "- No live model request or measured peak-memory claim.\n"
             f"- Evidence: {output.relative_to(ROOT).as_posix()}.\n\n"
             "Next action: review the results and regression, then record the scoped-source checkpoint.\n")
    for name in ("PROJECT-AUDIT.md", "INTEGRATION-TRACKER.md"):
        path = ROOT / "docs" / name
        text = path.read_text(encoding="utf-8")
        if heading not in text:
            path.write_text(text.rstrip() + "\n\n" + entry, encoding="utf-8")
    print("\nALL THREE SCOPED POOL QUERIES VERIFIED")
    print(json.dumps([{key: item[key] for key in ("case", "loaded_events", "sample_n", "boundary_events", "complete_result_matches")}
                      for item in results], indent=2))
    print(f"Evidence: {output.relative_to(ROOT).as_posix()}")
    print("Updated both audit documents. Run git status --short.")


if __name__ == "__main__":
    main()
