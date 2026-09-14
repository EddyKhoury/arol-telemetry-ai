"""KPI tools, including the success-rate denominator decision.

The denominator test is the important one. contract.pdf's OPEN item 1 asked
whether No Load cycles belong in the denominator; these tests pin the agreed
answer down in code so it cannot drift later without a test failing.

On the real machine the two denominators differ by 44 percentage points, so
this is not a hypothetical.
"""

from datetime import datetime, timedelta

import polars as pl
import pytest

from src.analytics import kpi
from src.common import registry as R
from src.common import schema


def _frame(statuses, head="H01", start="2026-02-01 00:00:00", step_s=6):
    """Build a tiny conforming event table from a list of status codes."""
    t0 = datetime.fromisoformat(start.replace(" ", "T"))
    n = len(statuses)
    frame = pl.DataFrame({
        "ts": [t0 + timedelta(seconds=i * step_s) for i in range(n)],
        "pool_id": pl.Series(["test"] * n, dtype=pl.String),
        "machine_id": pl.Series(["M1"] * n, dtype=pl.String),
        "head_id": pl.Series([head] * n, dtype=pl.String),
        "head_index": pl.Series([1] * n, dtype=pl.Int16),
        "torque": pl.Series([2.0] * n, dtype=pl.Float64),
        "status": pl.Series(statuses, dtype=pl.Int16),
        "count_delta": pl.Series([1] * n, dtype=pl.Int32),
        "inferred": pl.Series([False] * n, dtype=pl.Boolean),
    })
    decoded = schema.decode_status_series(frame["status"]).drop("confirmed")
    return schema.conform(frame.hstack(decoded))


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
    assert out["result"]["total_closures"] >= events.height


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


def test_idle_ordering_is_total(events):
    """Two stretches can share a duration to the second; the sort key must
    still put them in one reproducible order (caught by the golden diff)."""
    first = R.call_tool("idle_periods", events)["result"]["idle_periods"]
    second = R.call_tool("idle_periods", events)["result"]["idle_periods"]
    assert first == second


# --- determinism ----------------------------------------------------------

@pytest.mark.parametrize("tool_name", ["success_rate", "success_rate_per_head",
                                       "anomaly_heads", "idle_periods",
                                       "throughput"])
def test_same_input_same_numbers(events, tool_name):
    """The claim the whole project rests on: repeatable outputs."""
    first = R.call_tool(tool_name, events)["result"]
    second = R.call_tool(tool_name, events)["result"]
    assert first == second
