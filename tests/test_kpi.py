"""KPI tools, including the success-rate denominator decision.

The denominator test is the important one. contract.pdf's OPEN item 1 asked
whether No Load cycles belong in the denominator; these tests pin the agreed
answer down in code so it cannot drift later without a test failing.
"""

import pandas as pd
import pytest

from src.analytics import kpi
from src.common import registry as R
from src.common import schema


def _frame(statuses, head="H01", start="2026-02-01 00:00:00", step_s=6):
    """Build a tiny conforming event table from a list of status codes."""
    ts = pd.date_range(start, periods=len(statuses), freq=f"{step_s}s")
    decoded = schema.decode_status_series(pd.Series(statuses))
    return schema.conform(pd.DataFrame({
        "ts": ts,
        "pool_id": "test",
        "machine_id": "M1",
        "head_id": head,
        "head_index": 1,
        "torque": 2.0,
        "status": statuses,
        "error_class": decoded["error_class"].to_numpy(),
        "reject_signal": decoded["reject_signal"].to_numpy(),
        "cap_present": decoded["cap_present"].to_numpy(),
        "count_delta": 1,
        "inferred": False,
    }))


# --- the denominator (contract OPEN item 1) -------------------------------

def test_no_load_is_excluded_from_the_success_denominator():
    """8 OK, 1 Bad Closure, 91 No Load.

    Cap-present closures are 9, of which 8 succeeded -> 88.89%.
    Counting No Load as failure would report 8% instead. The two must not be
    confused, and both must be returned.
    """
    frame = _frame([0] * 8 + [65] + [2] * 91)
    out = R.call_tool("success_rate", frame)
    overall = out["result"]["overall"]

    assert overall["n_cycles"] == 100
    assert overall["n_cap_present"] == 9
    assert overall["n_success"] == 8
    assert overall["success_rate"] == pytest.approx(8 / 9)
    assert overall["success_rate_all_cycles"] == pytest.approx(0.08)
    assert overall["no_load_rate"] == pytest.approx(0.91)


def test_the_denominator_is_always_explained():
    """A report must never be ambiguous about which denominator it used."""
    out = R.call_tool("success_rate", _frame([0] * 40 + [2] * 10))
    assert "cap-present" in out["result"]["denominator_explained"]


def test_all_no_load_yields_no_success_rate_not_zero():
    """No cap was ever present, so the success rate is undefined, not 0%."""
    out = R.call_tool("success_rate", _frame([2] * 50))
    assert out["result"]["overall"]["success_rate"] is None
    assert out["result"]["overall"]["no_load_rate"] == 1.0


# --- filters and empties --------------------------------------------------

def test_empty_filter_returns_a_failure_envelope_not_an_exception():
    out = R.call_tool("success_rate", _frame([0] * 10), start="2030-01-01")
    assert out["ok"] is False
    assert out["meta"]["n"] == 0


def test_low_n_is_reported_in_the_notes():
    """meta.n drives the confidence section - never prose."""
    out = R.call_tool("success_rate", _frame([0] * 5), min_n=30)
    assert "below min_n" in out["meta"]["notes"]


def test_filters_are_recorded_for_the_trace(events):
    out = R.call_tool("success_rate", events, head_id="H01")
    assert any("head_id" in f for f in out["meta"]["filters_applied"])


# --- throughput -----------------------------------------------------------

def test_throughput_counts_inferred_closures(events):
    """Audit F6: a counter jump of 2 is two closures, not one row."""
    out = R.call_tool("throughput", events)
    assert out["result"]["total_closures"] >= len(events)


def test_throughput_buckets_cover_the_window(events):
    out = R.call_tool("throughput", events, bucket="hour")
    assert len(out["result"]["by_bucket"]) == 24


# --- idle -----------------------------------------------------------------

def test_idle_requires_a_sustained_run():
    """Two isolated No Loads are not an idle period."""
    frame = _frame([0] * 10 + [2, 0, 2] + [0] * 10)
    out = R.call_tool("idle_periods", frame, window_seconds=300)
    assert out["result"]["n_periods"] == 0


def test_idle_detects_a_long_run():
    frame = _frame([0] * 5 + [2] * 100 + [0] * 5, step_s=6)  # 100 * 6s = 594s
    out = R.call_tool("idle_periods", frame, window_seconds=300)
    assert out["result"]["n_periods"] == 1
    assert out["result"]["idle_periods"][0]["duration_seconds"] >= 300


# --- determinism ----------------------------------------------------------

@pytest.mark.parametrize("tool_name", ["success_rate", "success_rate_per_head",
                                       "anomaly_heads", "idle_periods",
                                       "throughput"])
def test_same_input_same_numbers(events, tool_name):
    """The claim the whole project rests on: repeatable outputs."""
    first = R.call_tool(tool_name, events)["result"]
    second = R.call_tool(tool_name, events)["result"]
    assert first == second
