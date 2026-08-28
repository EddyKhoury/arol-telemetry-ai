"""Synthetic event-table generator with ground truth.

This is the placeholder handshake from contract.pdf, and it is Person B's
first deliverable for two reasons:

  1. It unblocks B. The whole agent - planner, dispatch, report assembler,
     CLI, plots - is built and tested against this while Person A builds WP1.
     When the real loader lands, `data.source: real` in config.yaml is the
     only change.

  2. It unblocks A. His Phase-4 anomaly evaluation needs faults whose location
     is known in advance. Real telemetry has no labels - Bad Closures are
     single-digit occurrences per file - so we manufacture the ground truth
     here. That is what turns "we detect drift" into a precision/recall number.

The generator is seeded: same seed, same table, byte for byte. The determinism
test depends on that, and so does any claim that a report is reproducible.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

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


def _plan_faults(rng, heads, start, end):
    """Decide which faults to inject. Returns the ground-truth records."""
    span = (end - start).total_seconds()

    bad_head = heads[rng.integers(0, len(heads))]
    drift_head = heads[rng.integers(0, len(heads))]
    while drift_head == bad_head and len(heads) > 1:
        drift_head = heads[rng.integers(0, len(heads))]

    drift_start = start + pd.Timedelta(seconds=span * 0.35)
    drift_end = start + pd.Timedelta(seconds=span * 0.75)
    idle_start = start + pd.Timedelta(seconds=span * 0.12)
    idle_end = idle_start + pd.Timedelta(seconds=min(5400, span * 0.06))

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
            "detectable_by": ["reject_rate_per_head", "anomaly_heads"],
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


def _head_frame(rng, head_id, head_index, ts, faults, machine_id, pool_id):
    """Generate one head's closure events over the given timestamps."""
    n = len(ts)
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
            idle = (ts >= pd.Timestamp(fault["start"])) & (ts < pd.Timestamp(fault["end"]))
            status[idle] = STATUS_NO_LOAD

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
            f_start = pd.Timestamp(fault["start"])
            f_end = pd.Timestamp(fault["end"])
            magnitude = fault["detail"]["torque_to"] - fault["detail"]["torque_from"]
            elapsed = (ts - f_start).total_seconds().to_numpy()
            total = (f_end - f_start).total_seconds()
            progress = np.clip(elapsed / total, 0.0, 1.0)
            torque = np.where(status == STATUS_OK, torque + magnitude * progress, torque)

    decoded = schema.decode_status_series(pd.Series(status))
    return pd.DataFrame({
        "ts": ts,
        "pool_id": pool_id,
        "machine_id": machine_id,
        "head_id": head_id,
        "head_index": np.int16(head_index),
        "torque": np.round(torque, 4),
        "status": status,
        "error_class": decoded["error_class"].to_numpy(),
        "reject_signal": decoded["reject_signal"].to_numpy(),
        "cap_present": decoded["cap_present"].to_numpy(),
        "count_delta": np.int32(1),
        "inferred": False,
    })


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
    t0 = pd.Timestamp(p["start"])
    span = pd.Timedelta(days=p["days"])
    t1 = t0 + span
    heads = [f"H{i:02d}" for i in range(1, int(p["n_heads"]) + 1)]
    faults = _plan_faults(rng, heads, t0, t1)

    interval = float(p["closure_interval_seconds"])
    per_head = max(1, int(span.total_seconds() / interval))
    jitter = interval * 0.15

    frames = []
    for index, head_id in enumerate(heads, start=1):
        offsets = np.arange(per_head) * interval
        offsets = offsets + rng.uniform(-jitter, jitter, per_head)
        # Telemetry is polled at 1 Hz, so a closure is observed on a whole second.
        offsets = np.clip(np.round(offsets), 0, span.total_seconds() - 1)
        ts = t0 + pd.to_timedelta(np.sort(offsets), unit="s")
        frames.append(_head_frame(rng, head_id, index, ts, faults,
                                  p["machine_id"], pool_id))

    events = pd.concat(frames, ignore_index=True)
    events = events.sort_values(["ts", "head_index"], kind="stable").reset_index(drop=True)

    # A handful of dropped polls: the counter jumped by 2 between samples, so
    # one closure was never observed directly. Exercises audit finding F6.
    if dropped_samples and len(events) > dropped_samples:
        picked = rng.choice(len(events), size=int(dropped_samples), replace=False)
        events.loc[picked, "count_delta"] = np.int32(2)
        events.loc[picked, "inferred"] = True

    events = schema.conform(events)

    ground_truth = {
        "schema_version": schema.SCHEMA_VERSION,
        "generator": "src/testing/synth.py",
        "seed": int(p["seed"]),
        "params": {k: (str(v) if isinstance(v, pd.Timestamp) else v)
                   for k, v in p.items()},
        "pool_id": pool_id,
        "n_events": int(len(events)),
        "ts_min": events["ts"].min().isoformat(),
        "ts_max": events["ts"].max().isoformat(),
        "n_inferred": int(events["inferred"].sum()),
        "faults": faults,
    }
    return events, ground_truth


def generate_from_config(cfg, pool_id="synthetic"):
    """Generate using the data.synthetic block of config.yaml."""
    return generate(pool_id=pool_id, **(cfg.get("data", {}).get("synthetic") or {}))


def save(events, ground_truth, out_dir):
    """Write the pair to disk: events.parquet + ground_truth.json."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    events.to_parquet(out / "events.parquet", index=False)
    (out / "ground_truth.json").write_text(
        json.dumps(ground_truth, indent=2), encoding="utf-8")
    return out
