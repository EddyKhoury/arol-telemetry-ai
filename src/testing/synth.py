"""Synthetic event-table generator with ground truth.

This is the placeholder handshake from contract.pdf, and it is Person B's
first deliverable for two reasons:

  1. It unblocks B. The whole agent - planner, dispatch, report assembler,
     CLI, plots - is built and tested against this while Person A builds WP1.

  2. It unblocks A. His Phase-4 anomaly evaluation needs faults whose location
     is known in advance. Real telemetry has no labels - the real machine
     produced 4 Bad Closures in 765,711 closures on 2026-02-01 - so we
     manufacture the ground truth here. That is what turns "we detect drift"
     into a precision/recall number.

The generator is seeded: same seed, same table, row for row. The determinism
test depends on that, and so does any claim that a report is reproducible.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from ..common import schema

# Defaults; config.yaml data.synthetic overrides all of them.
DEFAULTS = {
    "seed": 20260828,
    "days": 1,
    "n_heads": 36,
    "machine_id": "MCC777-01",
    "start": "2026-02-01 00:00:00",
    "closure_interval_seconds": 6.0,
}

# Nominal behaviour of a healthy head.
TORQUE_OK_MEAN = 2.0
TORQUE_OK_SD = 0.05
TORQUE_BAD_MEAN = 1.2          # a bad closure under-torques
TORQUE_BAD_SD = 0.30
TORQUE_NOLOAD_MEAN = 0.02      # nothing in the head: essentially zero
TORQUE_NOLOAD_SD = 0.01

P_NO_LOAD = 0.030              # background rate of empty cycles
P_REJECT = 0.0005              # background Bad Closure rate
P_REJECT_FAULTY = 0.030        # the injected bad head, ~60x baseline

STATUS_OK, STATUS_NO_LOAD, STATUS_BAD = 0, 2, 65


def _parse(text: str) -> datetime:
    return datetime.fromisoformat(str(text).replace(" ", "T"))


def _plan_faults(rng, heads, start: datetime, end: datetime):
    """Decide which faults to inject. Returns the ground-truth records."""
    span = (end - start).total_seconds()

    bad_head = heads[rng.integers(0, len(heads))]
    drift_head = heads[rng.integers(0, len(heads))]
    while drift_head == bad_head and len(heads) > 1:
        drift_head = heads[rng.integers(0, len(heads))]

    drift_start = start + timedelta(seconds=span * 0.35)
    drift_end = start + timedelta(seconds=span * 0.75)
    idle_start = start + timedelta(seconds=span * 0.12)
    idle_end = idle_start + timedelta(seconds=min(5400, span * 0.06))

    return [
        {
            "type": "elevated_reject_rate",
            "head_id": bad_head,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "detail": {
                "reject_rate": P_REJECT_FAULTY,
                "baseline_reject_rate": P_REJECT,
                "status_code": STATUS_BAD,
            },
            "detectable_by": ["anomaly_heads", "success_rate_per_head"],
        },
        {
            "type": "torque_drift",
            "head_id": drift_head,
            "start": drift_start.isoformat(),
            "end": drift_end.isoformat(),
            "detail": {
                "torque_from": TORQUE_OK_MEAN,
                "torque_to": TORQUE_OK_MEAN + 0.45,
                "shape": "linear ramp, then holds at the drifted value",
            },
            "detectable_by": ["torque_drift", "torque_stats"],
        },
        {
            "type": "idle_period",
            "head_id": None,                     # affects every head
            "start": idle_start.isoformat(),
            "end": idle_end.isoformat(),
            "detail": {
                "status_code": STATUS_NO_LOAD,
                "cause": "sustained No Load - no bottles arriving at the machine",
            },
            "detectable_by": ["idle_periods"],
        },
    ]


def _head_frame(rng, head_id, head_index, ts_us, faults, machine_id, pool_id):
    """Generate one head's closure events. `ts_us` is datetime64[us]."""
    n = len(ts_us)
    status = np.full(n, STATUS_OK, dtype=np.int16)

    reject_p = P_REJECT
    for fault in faults:
        if fault["type"] == "elevated_reject_rate" and fault["head_id"] == head_id:
            reject_p = fault["detail"]["reject_rate"]

    draw = rng.random(n)
    status[draw < P_NO_LOAD] = STATUS_NO_LOAD
    status[(draw >= P_NO_LOAD) & (draw < P_NO_LOAD + reject_p)] = STATUS_BAD

    # Idle window: every head cycles but no cap is present.
    for fault in faults:
        if fault["type"] == "idle_period":
            lo = np.datetime64(_parse(fault["start"]), "us")
            hi = np.datetime64(_parse(fault["end"]), "us")
            status[(ts_us >= lo) & (ts_us < hi)] = STATUS_NO_LOAD

    torque = rng.normal(TORQUE_OK_MEAN, TORQUE_OK_SD, n)
    bad = status == STATUS_BAD
    torque[bad] = rng.normal(TORQUE_BAD_MEAN, TORQUE_BAD_SD, bad.sum())
    empty = status == STATUS_NO_LOAD
    torque[empty] = np.abs(rng.normal(TORQUE_NOLOAD_MEAN, TORQUE_NOLOAD_SD, empty.sum()))

    # Torque drift: a linear ramp inside the window that then holds, so the
    # drift is still visible after the window closes (a real worn head does
    # not heal itself).
    for fault in faults:
        if fault["type"] == "torque_drift" and fault["head_id"] == head_id:
            f_start = np.datetime64(_parse(fault["start"]), "us")
            f_end = np.datetime64(_parse(fault["end"]), "us")
            magnitude = fault["detail"]["torque_to"] - fault["detail"]["torque_from"]
            elapsed = (ts_us - f_start) / np.timedelta64(1, "s")
            total = (f_end - f_start) / np.timedelta64(1, "s")
            progress = np.clip(elapsed / total, 0.0, 1.0)
            torque = np.where(status == STATUS_OK, torque + magnitude * progress, torque)

    frame = pl.DataFrame({
        "ts": ts_us,
        "pool_id": pl.Series([pool_id] * n, dtype=pl.String),
        "machine_id": pl.Series([machine_id] * n, dtype=pl.String),
        "head_id": pl.Series([head_id] * n, dtype=pl.String),
        "head_index": pl.Series(np.full(n, head_index, dtype=np.int16)),
        "torque": np.round(torque, 4),
        "status": status,
        "count_delta": np.ones(n, dtype=np.int32),
        "inferred": np.zeros(n, dtype=bool),
    })
    decoded = schema.decode_status_series(frame["status"]).drop("confirmed")
    return frame.hstack(decoded)


def generate(*, seed=None, days=None, n_heads=None, machine_id=None,
             start=None, closure_interval_seconds=None, pool_id="synthetic",
             dropped_samples=12):
    """Build a synthetic event table plus its ground truth.

    Returns (events, ground_truth). `events` conforms to schema.EVENT_COLUMNS;
    `ground_truth` names every injected fault, its head and its time window.
    """
    p = dict(DEFAULTS)
    for key, value in {
        "seed": seed, "days": days, "n_heads": n_heads,
        "machine_id": machine_id, "start": start,
        "closure_interval_seconds": closure_interval_seconds,
    }.items():
        if value is not None:
            p[key] = value

    rng = np.random.default_rng(p["seed"])
    t0 = _parse(p["start"])
    span_seconds = float(p["days"]) * 86_400.0
    t1 = t0 + timedelta(seconds=span_seconds)
    heads = [f"H{i:02d}" for i in range(1, int(p["n_heads"]) + 1)]
    faults = _plan_faults(rng, heads, t0, t1)

    interval = float(p["closure_interval_seconds"])
    per_head = max(1, int(span_seconds / interval))
    jitter = interval * 0.15
    base = np.datetime64(t0, "us")

    frames = []
    for index, head_id in enumerate(heads, start=1):
        offsets = np.arange(per_head) * interval
        offsets = offsets + rng.uniform(-jitter, jitter, per_head)
        # Telemetry is polled at 1 Hz, so a closure is observed on a whole second.
        offsets = np.clip(np.round(offsets), 0, span_seconds - 1)
        ts_us = base + np.sort(offsets).astype("timedelta64[s]").astype("timedelta64[us]")
        frames.append(_head_frame(rng, head_id, index, ts_us, faults,
                                  p["machine_id"], pool_id))

    events = pl.concat(frames).sort(["ts", "head_index"])

    # A handful of dropped polls: the counter jumped by 2 between samples, so
    # one closure was never observed directly. Exercises audit finding F6 -
    # and the real machine really does this 8 times a day.
    if dropped_samples and events.height > dropped_samples:
        picked = rng.choice(events.height, size=int(dropped_samples), replace=False)
        mask = np.zeros(events.height, dtype=bool)
        mask[picked] = True
        events = events.with_columns(
            pl.when(pl.Series(mask)).then(pl.lit(2, dtype=pl.Int32))
              .otherwise(pl.col("count_delta")).alias("count_delta"),
            pl.Series(mask).alias("inferred"),
        )

    events = schema.conform(events)

    ground_truth = {
        "schema_version": schema.SCHEMA_VERSION,
        "generator": "src/testing/synth.py",
        "seed": int(p["seed"]),
        "params": {k: str(v) if isinstance(v, datetime) else v for k, v in p.items()},
        "pool_id": pool_id,
        "n_events": int(events.height),
        "ts_min": events["ts"].min().isoformat(),
        "ts_max": events["ts"].max().isoformat(),
        "n_inferred": int(events["inferred"].sum()),
        "faults": faults,
    }
    return events, ground_truth


def generate_from_config(cfg, pool_id="synthetic"):
    """Generate using the data.synthetic block of config.yaml."""
    return generate(pool_id=pool_id, **(cfg.get("data", {}).get("synthetic") or {}))


def save(events: pl.DataFrame, ground_truth: dict, out_dir):
    """Write the pair to disk: events.parquet + ground_truth.json."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    events.write_parquet(out / "events.parquet")
    (out / "ground_truth.json").write_text(
        json.dumps(ground_truth, indent=2), encoding="utf-8")
    return out
