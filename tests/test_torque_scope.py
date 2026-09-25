"""Verify scope selection without silently broadening the query."""

from datetime import datetime, timedelta

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from src.analytics import registered_torque  # noqa: F401
from src.common.registry import call_tool


@pytest.fixture
def events():
    start = datetime(2026, 2, 1, 10)
    return pl.DataFrame({
        "ts": [start + timedelta(seconds=i) for i in [0, 0, 1, 2, 2, 3, 4]],
        "machine_id": ["M1", "M2", "M1", "M1", "M1", "M1", "M1"],
        "head_id": ["H01", "H01", "H02", "H01", "H01", "H01", "H01"],
        "torque": [1.0, 100.0, 3.0, 5.0, float("nan"), 7.0, 9.0],
        "status": [0, 0, 65, 0, 0, 65, 0],
    })


def test_combined_scope_and_actual_data_window(events):
    before = events.clone()
    response = call_tool(
        "torque_stats", events,
        head_id="H01", machine_id="M1",
        start="2026-02-01T10:00:02", end="2026-02-01T10:00:04",
    )
    assert response["ok"] is True
    assert response["result"]["sample_size"] == 2
    assert response["result"]["mean"] == 6.0
    assert response["meta"]["data_window"] == {
        "ts_min": "2026-02-01T10:00:02",
        "ts_max": "2026-02-01T10:00:03",
    }
    assert_frame_equal(events, before)


def test_scope_combines_with_successful_status(events):
    response = call_tool(
        "torque_stats", events,
        head_id="H01", machine_id="M1", status_filter="successful",
        start="2026-02-01T10:00:02", end="2026-02-01T10:00:04",
    )
    assert response["ok"] is True
    assert response["result"]["sample_size"] == 1
    assert response["result"]["mean"] == 5.0


def test_start_is_inclusive_and_end_is_exclusive(events):
    response = call_tool(
        "torque_stats", events, machine_id="M1",
        start="2026-02-01T10:00:01", end="2026-02-01T10:00:02",
    )
    assert response["ok"] is True
    assert response["result"]["sample_size"] == 1
    assert response["result"]["mean"] == 3.0


def test_multiple_heads(events):
    response = call_tool(
        "torque_stats", events, head_id=["H01", "H02"], machine_id="M1"
    )
    assert response["ok"] is True
    assert response["result"]["sample_size"] == 5
    assert response["result"]["mean"] == 5.0


def test_existing_parameter_aliases_preserve_scope(events):
    response = call_tool("torque_stats", events, head="H01", machine="M1")
    assert response["ok"] is True
    assert response["result"]["sample_size"] == 4
    assert response["result"]["mean"] == 5.5
    assert response["meta"]["params"] == {"head_id": "H01", "machine_id": "M1"}


@pytest.mark.parametrize("params", [
    {"head_id": "H99"},
    {"machine_id": "M99"},
    {"start": "2026-02-02"},
    {"status_filter": 999},
])
def test_valid_unmatched_scope_returns_empty_result(events, params):
    response = call_tool("torque_stats", events, **params)
    assert response["ok"] is True
    assert response["result"]["sample_size"] == 0
    assert response["result"]["mean"] is None
    assert response["meta"]["n"] == 0
    assert response["meta"]["data_window"] == {"ts_min": None, "ts_max": None}
    assert response["meta"]["params"] == params


@pytest.mark.parametrize("params", [
    {"start": ""},
    {"start": "null"},
    {"start": None},
    {"start": "not-a-date"},
    {"start": "2026-02-01T10:00:00Z"},
    {"end": "2026-02-01T11:00:00+01:00"},
    {"start": "2026-02-02", "end": "2026-02-01"},
    {"start": "2026-02-01", "end": "2026-02-01"},
    {"head_id": []},
    {"head_id": ["H01", None]},
    {"head_id": True},
    {"machine_id": ""},
])
def test_invalid_scope_fails_without_returning_broader_statistics(events, params):
    response = call_tool("torque_stats", events, **params)
    assert response["ok"] is False
    assert response["result"] is None
    assert response["error"]
