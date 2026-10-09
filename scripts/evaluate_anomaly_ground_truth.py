"""Score the production anomaly route against independent, predeclared fixture labels.

From the repository root: python -m scripts.evaluate_anomaly_ground_truth
The fixed truth set describes synthetic torque deviations, not physical faults.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import polars as pl

from src.agent.orchestrator import Orchestrator
from src.common import datasource
from src.ingestion.event_pool import build_event_pool
from scripts.evaluate_agent import plant_input, scalar_events


ROOT = Path(__file__).resolve().parents[1]
TRUTH_PATH = ROOT / "benchmarks/evaluation/anomaly_truth_v1.json"


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def path_for_evidence(path: str) -> str:
    file = Path(path).resolve()
    return file.relative_to(ROOT).as_posix() if file.is_relative_to(ROOT) else str(file)


def plant_contextual_input(directory: Path, spec: dict) -> list[Path]:
    """Generate stable controls and deviations from the declared fixture spec."""
    begin = datetime.fromisoformat(spec["start"])
    overrides = {int(key): value for key, value in spec["overrides"].items()}
    assert set(overrides) == set(spec["positive_seconds"])
    rows = []
    for second in range(spec["raw_rows"]):
        torque = overrides.get(second, spec["normal_torques"][second % len(spec["normal_torques"])])
        rows.append({"timestamp": begin + timedelta(seconds=second),
                     "H05 Count": 100 + second, "H05 AppTorque": torque,
                     "H05 Status": 0})
    directory.mkdir(parents=True, exist_ok=False)
    original = pl.DataFrame(rows)
    paths = [directory / "input-1.csv", directory / "input-2.csv"]
    for path, part in zip(paths, (original[:26], original[26:])):
        part.write_csv(path)
    return paths


def raw_oracle(paths: list[Path], *, machine_id: str, head_id: str) -> tuple[dict, int]:
    """Independently count increments and keep current-row torque/status values."""
    previous = None
    observed = {}
    boundary = 0
    for file_index, path in enumerate(paths):
        with path.open(newline="", encoding="utf-8") as stream:
            for row_index, row in enumerate(csv.DictReader(stream)):
                count = int(row[f"{head_id} Count"])
                if previous is not None and count - previous == 1:
                    key = (datetime.fromisoformat(row["timestamp"]).isoformat(), machine_id, head_id)
                    assert key not in observed, "Fixture must identify each observed event uniquely"
                    observed[key] = (float(row[f"{head_id} AppTorque"]),
                                     int(row[f"{head_id} Status"]))
                    boundary += int(file_index > 0 and row_index == 0)
                previous = count
    return observed, boundary


def score_flags(observed: set[tuple], truth: set[tuple], flagged: list[dict]) -> dict:
    """Count each selected event once, comparing event IDs rather than torque values."""
    if not truth <= observed:
        raise ValueError("A positive label is not an observed event")
    predicted = [(datetime.fromisoformat(row["ts"]).isoformat(),
                  row["machine_id"], row["head_id"]) for row in flagged]
    if len(predicted) != len(set(predicted)) or not set(predicted) <= observed:
        raise ValueError("Anomaly output has duplicate or out-of-scope event IDs")
    found = set(predicted)
    tp, fp, fn, tn = (len(found & truth), len(found - truth),
                      len(truth - found), len(observed - truth - found))
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "false_positive_rate": fp / (fp + tn) if fp + tn else None,
            "missed_event_ids": [list(key) for key in sorted(truth - found)],
            "flagged_event_ids": [list(key) for key in sorted(found)]}


def evaluate_case(spec: dict, directory: Path, parameters: dict) -> dict:
    """Build the fixture, select the declared scope, and run the public agent."""
    if spec["fixture"] == "existing_controlled":
        paths = plant_input(directory / "raw")
        independent, boundary = scalar_events(paths)
        assert len(independent) == 48 and boundary == 4
    elif spec["fixture"] == "masked_contextual":
        paths = plant_contextual_input(directory / "raw", spec)
    else:
        raise ValueError("Unknown fixed fixture")
    observed, boundary = raw_oracle(paths, machine_id=spec["machine_id"],
                                    head_id=spec["head_id"])
    assert len(observed) == spec["raw_rows"] - 1
    assert boundary == 1
    manifest_path = build_event_pool(paths, directory / "pool", machine_id=spec["machine_id"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["summary"]["boundary_exact_plus_one"] == (4 if spec["fixture"] == "existing_controlled" else 1)
    end = (datetime.fromisoformat(spec["start"]) + timedelta(seconds=spec["raw_rows"])).isoformat()
    args = {"machine_id": spec["machine_id"], "start": spec["start"],
            "end": end, "head_id": spec["head_id"]}
    cfg = {"data": {"source": "person_a_pool", "person_a": {"truth": str(manifest_path)},
                    "max_loaded_events": 1000, "verify_pool_hashes": True},
           "agent": {"planner": "rules", "report_dir": str(directory / "reports"),
                     "trace_dir": str(directory / "traces"), "max_steps": 8},
           "analytics": {"min_n": 3, **parameters}}
    source = datasource.get_source(cfg)
    selected, meta = source.load_for_plan("truth", [("detect_torque_anomalies", args)])
    actual = {(row["ts"].isoformat(), row["machine_id"], row["head_id"]):
              (row["torque"], row["status"]) for row in selected.to_dicts()}
    assert len(actual) == len(selected) == len(observed) and actual == observed
    assert meta["loaded_events"] == len(observed)
    query = (f"Find torque anomalies for head 5 for machine {spec['machine_id']} "
             f"from {spec['start']} until {end}")
    agent = Orchestrator(cfg=cfg)
    answer = agent.answer(query, pool="truth")
    assert answer["status"] == "ok", answer.get("message")
    assert answer["plan"].calls == [("detect_torque_anomalies", args)]
    assert answer["trace"].to_dict()["n_tool_calls"] == 1
    name, response = answer["results"][0]
    assert name == "detect_torque_anomalies" and response["ok"]
    result = response["result"]
    assert result["sample_size"] == len(observed) and result["anomaly_count"] == len(result["anomalies"])
    origin = datetime.fromisoformat(spec["start"])
    positives = {(origin + timedelta(seconds=i)).isoformat() for i in spec["positive_seconds"]}
    truth = {(ts, spec["machine_id"], spec["head_id"]) for ts in positives}
    scored = score_flags(set(observed), truth, result["anomalies"])
    artifacts = agent.deliver(answer, formats=["markdown"])
    return {"case": spec["id"], "machine_id": spec["machine_id"], "head_id": spec["head_id"],
            "question": query, "n_observed": len(observed), "n_truth": len(truth),
            "n_flagged": result["anomaly_count"],
            "boundary_events": manifest["summary"]["boundary_exact_plus_one"],
            "selected_head_boundary_events": boundary,
            **scored,
            "flagged_reasons": {row["ts"]: row["reason"] for row in result["anomalies"]},
            "source_sha256": [fingerprint(p) for p in paths],
            "report": path_for_evidence(artifacts["report"]),
            "trace": path_for_evidence(artifacts["trace"])}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New run folder (default: ignored data/integration_smoke/)")
    parser.add_argument("--evidence", type=Path, help="Evidence JSON path (default: inside run folder)")
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != ROOT:
        parser.error("Run from the repository root")
    spec = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    assert spec["version"] == 1 and len(spec["cases"]) == 2
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    run_dir = (args.output or ROOT / "data/integration_smoke" / f"anomaly-truth-{stamp}-{uuid4().hex[:8]}").resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    records = []
    for case in spec["cases"]:
        try:
            record = evaluate_case(case, run_dir / case["id"], spec["parameters"])
            record["checked"] = True
        except Exception as exc:
            record = {"case": case["id"], "checked": False, "error": f"{type(exc).__name__}: {exc}"}
        records.append(record)
        print(f"{case['id']}: {'CHECKED' if record['checked'] else 'FAILED'}", flush=True)
    checked = all(r["checked"] for r in records)
    totals = {key: sum(r[key] for r in records) for key in ("tp", "fp", "fn", "tn")} if checked else None
    summary = None if totals is None else {
        **totals,
        "precision": totals["tp"] / (totals["tp"] + totals["fp"]) if totals["tp"] + totals["fp"] else None,
        "recall": totals["tp"] / (totals["tp"] + totals["fn"]) if totals["tp"] + totals["fn"] else None,
        "false_positive_rate": totals["fp"] / (totals["fp"] + totals["tn"]) if totals["fp"] + totals["tn"] else None}
    evidence = {"version": 1, "truth_sha256": fingerprint(TRUTH_PATH),
                "evaluation_script_sha256": fingerprint(Path(__file__)),
                "case_results": records, "aggregate": summary,
                "labels": "predeclared synthetic torque deviations, not confirmed physical machine faults",
                "definition": "precision=TP/(TP+FP); recall=TP/(TP+FN); false_positive_rate=FP/(FP+TN); event IDs=(stored timestamp,machine,head)",
                "scope": "Two short synthetic pools, exact +1 events and deterministic rules routing; configured 1.5–2.5 Nm and sigma=3.0; neither real-data fault prevalence nor physical failure detection is measured.",
                "limits": ["In-range contextual deviation is a predeclared synthetic label, not a verified bad closure or a confirmed engineering specification.",
                           "Score depends on selected fixture, thresholds, pooled mean and sample standard deviation.",
                           "The evaluator uses known valid question phrasing; it does not test arbitrary language or live Ollama.",
                           "Do not extrapolate rates from these small controlled fixtures to factory production."]}
    output = (args.evidence or run_dir / "evidence.json").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("ANOMALY GROUND-TRUTH MEASUREMENT")
    print(json.dumps({"checked": checked, "aggregate": summary,
                      "evidence": str(output)}, indent=2))
    return 0 if checked else 1


if __name__ == "__main__":
    raise SystemExit(main())
