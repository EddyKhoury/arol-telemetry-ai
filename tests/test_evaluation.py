"""Ground-truth evaluation.

Real telemetry has no labels - Bad Closures are single-digit occurrences per
file - so the synthetic generator injects faults whose location we know in
advance. These tests measure detection against that ground truth, which is
what turns "we detect anomalies" into precision and recall.

Person A's Phase-4 evaluation runs the same comparison over his statistical
tools. The generator and the ground-truth format are shared.
"""

import polars as pl
import pytest
from datetime import datetime

from src.analytics import kpi  # noqa: F401 - registers the tools
from src.common import registry as R


def _prf(detected, expected):
    """Precision, recall, F1 over sets of head ids."""
    detected, expected = set(detected), set(expected)
    tp = len(detected & expected)
    precision = tp / len(detected) if detected else 0.0
    recall = tp / len(expected) if expected else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def test_anomaly_detection_is_perfect_on_the_injected_fault(events, faults):
    """The one head with an elevated reject rate must be the only one flagged."""
    injected = faults["elevated_reject_rate"]["head_id"]
    out = R.call_tool("anomaly_heads", events, sigma=3.0)
    assert out["ok"]

    detected = [h["head_id"] for h in out["result"]["flagged_heads"]]
    precision, recall, f1 = _prf(detected, {injected})

    assert recall == 1.0, f"missed the injected fault on {injected}"
    assert precision == 1.0, f"false positives: {set(detected) - {injected}}"
    assert f1 == 1.0


def test_the_flagged_head_is_the_worst_head(events, faults):
    injected = faults["elevated_reject_rate"]["head_id"]
    out = R.call_tool("success_rate_per_head", events)
    assert out["result"]["worst_head"] == injected


def test_a_clean_pool_produces_no_false_positives(events, faults):
    """Drop the faulty head; nothing should be flagged in what remains."""
    injected = faults["elevated_reject_rate"]["head_id"]
    clean = events.filter(pl.col("head_id") != injected)
    out = R.call_tool("anomaly_heads", clean, sigma=3.0)
    assert out["result"]["flagged_heads"] == []


def test_idle_detection_recovers_the_injected_window(events, faults):
    injected = faults["idle_period"]
    out = R.call_tool("idle_periods", events, window_seconds=300)
    assert out["ok"] and out["result"]["n_periods"] > 0

    expected_start = datetime.fromisoformat(injected["start"])
    expected_end = datetime.fromisoformat(injected["end"])
    longest = out["result"]["idle_periods"][0]

    # Within one polling interval of the injected boundaries.
    assert abs((datetime.fromisoformat(longest["start"]) - expected_start).total_seconds()) <= 60
    assert abs((datetime.fromisoformat(longest["end"]) - expected_end).total_seconds()) <= 60


def test_the_idle_window_affects_every_head(events, faults):
    """A simultaneous stall on all heads is a supply problem, and the report
    says so - this test protects that inference."""
    out = R.call_tool("idle_periods", events, window_seconds=300)
    assert len(out["result"]["heads_affected"]) == events["head_id"].n_unique()


def test_torque_drift_is_present_and_measurable(events, faults):
    """The drift fault is Person A's tool to detect; this asserts the signal
    is actually in the data, so a failure there is his code, not our fixture."""
    drift = faults["torque_drift"]
    f_start = datetime.fromisoformat(drift["start"])
    f_end = datetime.fromisoformat(drift["end"])
    ok = events.filter(pl.col("status") == 0)
    before = (ok.filter(pl.col("ts") < f_start)
                .group_by("head_id").agg(pl.col("torque").mean().alias("before")))
    after = (ok.filter(pl.col("ts") > f_end)
               .group_by("head_id").agg(pl.col("torque").mean().alias("after")))
    shift = (before.join(after, on="head_id")
                   .with_columns((pl.col("after") - pl.col("before")).alias("shift"))
                   .sort("shift", descending=True))

    assert shift["head_id"][0] == drift["head_id"]
    expected = drift["detail"]["torque_to"] - drift["detail"]["torque_from"]
    assert shift["shift"][0] == pytest.approx(expected, abs=0.05)
    # And it must stand well clear of the noise on every other head.
    assert shift["shift"][0] > 5 * abs(shift["shift"][1])
