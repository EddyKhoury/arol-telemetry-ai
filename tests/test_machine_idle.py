"""Real pool build -> raw scoped read -> idle report, including file boundaries."""

from datetime import datetime, timedelta
import json

import polars as pl

from src.agent.orchestrator import Orchestrator
from src.ingestion.event_pool import build_event_pool


def _pool(tmp_path, offsets, status_a, status_b, *, float_status=False):
    origin = datetime(2026, 2, 1)
    raw = pl.DataFrame({
        "timestamp": [origin + timedelta(seconds=i) for i in offsets],
        "H01 Count": list(range(10, 10 + len(offsets))),
        "H02 Count": list(range(20, 20 + len(offsets))),
        "H01 AppTorque": [2.0] * len(offsets),
        "H02 AppTorque": [2.0] * len(offsets),
        "H01 Status": status_a, "H02 Status": status_b,
    })
    if float_status:
        raw = raw.with_columns(pl.col('H01 Status').cast(pl.Float64),
                               pl.col('H02 Status').cast(pl.Float64))
    paths = []
    for index, frame in enumerate((raw[:2], raw[2:])):
        path = tmp_path / f"input-{index}.csv"
        frame.write_csv(path)
        paths.append(path)
    manifest = build_event_pool(paths, tmp_path / "pool", machine_id="M1")
    cfg = {"data": {"source": "person_a_pool", "person_a": {"fixture": str(manifest)}},
           "agent": {"planner": "rules", "report_dir": str(tmp_path / "reports"),
                     "trace_dir": str(tmp_path / "traces")},
           "analytics": {"idle_window_seconds": 3}}
    return Orchestrator(cfg=cfg)


QUERY = ("Machine idle for machine M1 from 2026-02-01T00:00:00 "
         "until 2026-02-01T00:00:10")


def test_all_heads_no_load_continues_across_files(tmp_path):
    agent = _pool(tmp_path, [0, 1, 2, 3, 4], [2, 3, 2, 2, 0], [2, 2, 3, 2, 2])
    answer = agent.answer(QUERY)
    assert answer["status"] == "ok", answer.get("message")
    assert answer["plan"].calls[0][0] == "machine_idle"
    result = answer["results"][0][1]["result"]
    assert result["n_raw_readings"] == 5
    assert result["n_all_heads_no_load"] == 4
    assert result["idle_periods"] == [{"start": "2026-02-01T00:00:00",
                                       "end": "2026-02-01T00:00:04",
                                       "duration_seconds": 4, "n_readings": 4}]
    assert "5 raw status readings across 2 heads" in answer["markdown"]
    assert "not proof of zero production" in answer["markdown"]
    assert answer["trace"].to_dict()["n_tool_calls"] == 1


def test_missing_and_duplicate_polls_break_a_run(tmp_path):
    agent = _pool(tmp_path, [0, 1, 3, 4, 4, 5, 6], [2] * 7, [2] * 6 + [0])
    answer = agent.answer(QUERY)
    assert answer["status"] == "ok"
    result = answer["results"][0][1]["result"]
    assert result["n_periods"] == 0
    assert result["timestamp_gaps"] == 1
    assert result["duplicate_timestamps"] == 1


def test_missing_scope_never_opens_data(tmp_path):
    agent = _pool(tmp_path, [0, 1, 2], [2] * 3, [2] * 3)
    answer = agent.answer("Machine idle for machine M1")
    assert answer["status"] == "needs_clarification"
    assert answer["trace"].to_dict()["n_tool_calls"] == 0


def test_whole_number_float_statuses_from_csv_are_accepted(tmp_path):
    agent = _pool(tmp_path, [0, 1, 2, 3, 4], [2, 3, 2, 2, 0],
                  [2, 2, 3, 2, 2], float_status=True)
    answer = agent.answer(QUERY)
    assert answer['status'] == 'ok', answer.get('message')
    result = answer['results'][0][1]['result']
    assert result['idle_periods'][0]['duration_seconds'] == 4


def test_fractional_raw_status_stops_without_a_tool_call(tmp_path):
    agent = _pool(tmp_path, [0, 1, 2, 3, 4], [2, 2, 2, 2, 0],
                  [2, 2, 2, 2, 0], float_status=True)
    manifest_path = agent.source.paths['fixture']
    manifest = json.loads(manifest_path.read_text())
    raw_path = manifest_path.parent / manifest['partitions'][0]['raw_parquet']
    raw = pl.read_parquet(raw_path)
    raw.with_columns(pl.Series('H01 Status', [2.5, 2.0])).write_parquet(raw_path)
    answer = agent.answer(QUERY)
    assert answer['status'] == 'degraded'
    assert 'whole numbers' in answer['message']
    assert answer['trace'].to_dict()['n_tool_calls'] == 0
