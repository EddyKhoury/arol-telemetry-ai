"""The scaling benchmark - Q3 objective 5.

The benchmark's whole value rests on one property: the two implementations
must compute the SAME answer. A speedup against a monolith that quietly got a
different number would be meaningless, and worse than no benchmark at all.

Tested on a hand-built CSV rather than the real archive, so this runs in
milliseconds and on a machine without the telemetry.
"""

import io
from pathlib import Path

import pytest

from src.testing import benchmark


def _csv(rows, heads=("H01", "H02")) -> bytes:
    """A miniature raw telemetry file in AROL's column layout."""
    header = ["timestamp"]
    header += [f"{h} Count" for h in heads]
    header += [f"{h} AppTorque" for h in heads]
    header += [f"{h} Status" for h in heads]
    lines = [",".join(header)]
    for i, row in enumerate(rows):
        cells = [f"2026-02-01T08:{i // 60:02d}:{i % 60:02d}"]
        cells += [str(row[h]["count"]) for h in heads]
        cells += [f"{row[h]['torque']:.2f}" for h in heads]
        cells += [str(row[h]["status"]) for h in heads]
        lines.append(",".join(cells))
    return ("\n".join(lines) + "\n").encode()


def _sample():
    """Two heads over 10 seconds, with closures, a No Load and a reject."""
    counts = {"H01": 100, "H02": 200}
    rows, plan = [], [
        # (head that closes, status) or None for a quiet second
        None, ("H01", 0), None, ("H02", 2), ("H01", 65),
        None, ("H01", 0), ("H02", 0), None, ("H02", 0),
    ]
    for step in plan:
        row = {h: {"count": counts[h], "torque": 0.0, "status": 0}
               for h in counts}
        if step is not None:
            head, status = step
            counts[head] += 1
            row[head] = {"count": counts[head],
                         "torque": 2.0 if status == 0 else 0.5,
                         "status": status}
        rows.append(row)
    return [("sample.csv", _csv(rows))]


# --- the property the benchmark depends on --------------------------------

def test_the_two_implementations_agree():
    """If these diverge, the speedup number means nothing."""
    files = _sample()
    mono = benchmark.monolithic(files)
    agent, _ = benchmark.agent_pipeline(files)

    for key in ("n_cycles", "n_cap_present", "n_success", "n_reject"):
        assert mono[key] == agent[key], f"{key}: {mono[key]} vs {agent[key]}"
    assert mono["success_rate"] == pytest.approx(agent["success_rate"])


def test_the_counts_are_what_the_sample_actually_contains():
    """Pin the expected answer, so a bug that breaks BOTH implementations
    identically still fails."""
    mono = benchmark.monolithic(_sample())
    assert mono["n_cycles"] == 6        # 6 counter increments in the plan
    assert mono["n_cap_present"] == 5   # one of them was No Load
    assert mono["n_success"] == 4       # one of the five was a Bad Closure
    assert mono["n_reject"] == 1        # status 65, bit 0 set


def test_the_event_table_conforms():
    from src.common import schema
    events = benchmark.build_events(_sample())
    assert schema.validate_events(events, strict=False) == []
    assert events.height == 6


# --- the report -----------------------------------------------------------

def test_markdown_reports_both_tables():
    report = {"generated": "2026-09-15", "rows": [{
        "day_files": 1, "events": 765_711,
        "monolithic_seconds": 14.586, "monolithic_peak_mb": 54.5,
        "agent_seconds": 1.017, "agent_peak_mb": 54.5, "speedup": 14.3,
        "agent_followup_seconds": 0.3,
        "monolithic_5_questions_seconds": 72.93,
        "agent_5_questions_seconds": 1.322, "results_identical": True}]}
    md = benchmark.to_markdown(report)
    assert "765,711" in md and "14.3x" in md
    assert "Five questions instead of one" in md
    assert "72.93s" in md and "1.322s" in md


# --- the real run, only when the archive is here --------------------------

@pytest.mark.skipif(not Path(benchmark.ARCHIVE).exists(),
                    reason="telemetry archive not present")
def test_one_real_day_runs_and_agrees():
    report = benchmark.run(sizes=(1,), extra_questions=1)
    assert report["rows"], "no sizes completed"
    row = report["rows"][0]
    assert row["results_identical"] is True
    assert row["agent_seconds"] < row["monolithic_seconds"]
