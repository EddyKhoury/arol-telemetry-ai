"""The ground-truth score uses independent event labels and a production run."""

import json
from pathlib import Path

import pytest

from scripts import evaluate_anomaly_ground_truth as evaluation


def test_scoring_uses_event_identity_and_reports_false_negatives():
    normal = ("2026-02-01T00:00:01", "M1", "H05")
    planted = ("2026-02-01T00:00:02", "M1", "H05")
    same_torque_other_head = ("2026-02-01T00:00:02", "M1", "H06")
    flags = [{"ts": "2026-02-01 00:00:02.000000", "machine_id": "M1", "head_id": "H06"}]
    scored = evaluation.score_flags({normal, planted, same_torque_other_head}, {planted}, flags)
    assert (scored["tp"], scored["fp"], scored["fn"], scored["tn"]) == (0, 1, 1, 1)
    assert scored["precision"] == 0 and scored["recall"] == 0
    assert scored["false_positive_rate"] == pytest.approx(0.5)


def test_scoring_rejects_duplicate_or_unknown_predictions():
    key = ("2026-02-01T00:00:02", "M1", "H05")
    row = {"ts": key[0], "machine_id": key[1], "head_id": key[2]}
    with pytest.raises(ValueError, match="duplicate"):
        evaluation.score_flags({key}, {key}, [row, row])
    with pytest.raises(ValueError, match="not an observed event"):
        evaluation.score_flags(set(), {key}, [])


def test_two_planted_scenarios_run_through_real_orchestrator(tmp_path):
    spec = json.loads(evaluation.TRUTH_PATH.read_text(encoding="utf-8"))
    assert spec["version"] == 1
    assert spec["cases"][1]["overrides"]["11"] == 2.3
    results = [evaluation.evaluate_case(case, tmp_path / case["id"], spec["parameters"])
               for case in spec["cases"]]
    assert [(r["tp"], r["fp"], r["fn"], r["tn"]) for r in results] == [
        (2, 0, 0, 10), (2, 0, 1, 49)]
    assert results[0]["boundary_events"] == 4
    assert results[1]["boundary_events"] == 1
    assert results[1]["missed_event_ids"] == [["2026-02-02T00:00:11", "M2", "H05"]]
    assert all((evaluation.ROOT / r["report"]).is_file() and
               (evaluation.ROOT / r["trace"]).is_file() for r in results)
