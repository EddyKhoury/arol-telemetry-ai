"""The integration contract: schema, status decoding, envelope, registry.

These are the tests that make swapping Person A's real loader in for the
synthetic generator a one-line change. If they pass for both sources, the two
halves of the project fit together.
"""

import json

import polars as pl
import pytest

from src.common import registry as R
from src.common import schema
from src.common.envelope import envelope, failure, jsonable


# --- status decoding (audit F11) ------------------------------------------

@pytest.mark.parametrize("code,error_class,reject,cap", [
    (0, "Closure OK", False, True),
    (2, "No Load", False, False),
    (65, "Bad Closure", True, True),
])
def test_observed_status_codes_decode_as_documented(code, error_class, reject, cap):
    got = schema.decode_status(code)
    assert got["error_class"] == error_class
    assert got["reject_signal"] is reject
    assert got["cap_present"] is cap
    assert got["confirmed"] is True


def test_bit_zero_is_the_reject_flag():
    """65 == 64 | 1: same category as 64, but rejected."""
    assert schema.decode_status(64)["error_class"] == \
        schema.decode_status(65)["error_class"]
    assert schema.decode_status(64)["reject_signal"] is False
    assert schema.decode_status(65)["reject_signal"] is True


def test_unknown_codes_degrade_instead_of_crashing():
    """A grading dataset with new codes must not take the pipeline down."""
    got = schema.decode_status(255)
    assert got["error_class"] == "Unknown (255)"
    assert got["confirmed"] is False


def test_vectorised_decode_matches_scalar():
    codes = [0, 2, 65, 3, 4, 17, 255]
    frame = schema.decode_status_series(pl.Series(codes))
    for i, code in enumerate(codes):
        scalar = schema.decode_status(code)
        assert frame["error_class"][i] == scalar["error_class"]
        assert bool(frame["reject_signal"][i]) == scalar["reject_signal"]
        assert bool(frame["cap_present"][i]) == scalar["cap_present"]


# --- the event table ------------------------------------------------------

def test_empty_events_conforms():
    assert schema.validate_events(schema.empty_events(), strict=False) == []


def test_synthetic_events_conform(events):
    assert schema.validate_events(events, strict=False) == []


def test_validate_rejects_a_missing_column(events):
    broken = events.drop("torque")
    with pytest.raises(schema.SchemaError, match="missing columns"):
        schema.validate_events(broken)


def test_validate_rejects_a_wrong_dtype(events):
    broken = events.with_columns(pl.col("status").cast(pl.Int64))
    problems = schema.validate_events(broken, strict=False)
    assert any("status" in p for p in problems)


def test_validate_rejects_tz_aware_timestamps(events):
    """Audit F5: a UTC shift would move closures across midnight."""
    broken = events.with_columns(pl.col("ts").dt.replace_time_zone("UTC"))
    problems = schema.validate_events(broken, strict=False)
    assert any("timezone-aware" in p or "ts" in p for p in problems)


# --- the envelope (audit F14, F15) ----------------------------------------

def test_envelope_always_has_all_four_keys():
    for result in (envelope({"x": 1}, n=5), failure("boom")):
        assert set(result) == {"ok", "result", "error", "meta"}
        assert "n" in result["meta"]


def test_envelope_is_json_serialisable_with_engine_types():
    import numpy as np
    result = envelope({"rate": np.float64(0.5), "n": np.int64(3),
                       "flag": bool(np.bool_(True)), "nan": float("nan"),
                       "series": pl.Series([1, 2, 3])}, n=3)
    text = json.dumps(result)          # must not raise
    assert json.loads(text)["result"]["rate"] == 0.5
    assert json.loads(text)["result"]["nan"] is None


def test_jsonable_handles_timestamps():
    from datetime import datetime
    assert jsonable(datetime(2026, 2, 1)) == "2026-02-01T00:00:00"


# --- the registry (audit F3, F4) ------------------------------------------

def test_every_registered_tool_uses_the_shared_vocabulary():
    """Audit F4: no tool may invent its own parameter names."""
    for name in R.list_tools():
        spec = R.get(name)
        unknown = [p for p in spec.params if p not in R.PARAM_VOCABULARY]
        assert unknown == [], f"{name} uses non-vocabulary params {unknown}"


def test_tool_specs_are_valid_json_schema():
    for spec in R.get_tool_specs():
        assert spec["name"] and spec["description"]
        assert spec["input_schema"]["type"] == "object"
        json.dumps(spec)


def test_aliases_are_normalised(events):
    """An LLM saying 'head' instead of 'head_id' must not break dispatch."""
    out = R.call_tool("idle_periods", events, head="H01")
    assert out["ok"]
    assert any("alias" in f for f in out["meta"]["filters_applied"])


def test_unknown_parameter_returns_an_envelope_not_an_exception(events):
    out = R.call_tool("success_rate", events, colour="red")
    assert out["ok"] is False
    assert "does not accept" in out["error"]


def test_unknown_tool_returns_an_envelope(events):
    out = R.call_tool("does_not_exist", events)
    assert out["ok"] is False and "no such tool" in out["error"]


def test_a_tool_that_raises_is_caught(events):
    @R.tool(name="_explodes", description="Test double.", params=[], agent="kpi")
    def _explodes(ev):
        raise RuntimeError("simulated bug")

    out = R.call_tool("_explodes", events)
    assert out["ok"] is False and "simulated bug" in out["error"]


def test_meta_carries_what_the_trace_log_needs(events):
    """Audit F15."""
    meta = R.call_tool("success_rate", events)["meta"]
    for key in ("tool", "agent", "n", "params", "elapsed_ms", "data_window"):
        assert key in meta
