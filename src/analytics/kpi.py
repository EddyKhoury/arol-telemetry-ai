"""KPI tools - Person B's half of WP2.

Person A owns the statistical tools (torque distributions, drift, correlation,
torque-based anomaly). This module owns the counting: success rates, per-head
aggregation, time bucketing, idle detection, throughput.

Every function here is deterministic. The planner decides *which* of these to
call and with what arguments; it never computes a number itself. That is the
design decision the whole project rests on, so nothing in this file may ever
call a model.

THE SUCCESS-RATE DENOMINATOR (contract.pdf OPEN item 1, resolved)
    A No Load cycle is not a failed closure - there was no cap in the head to
    close. Counting it as a failure makes every success rate meaningless.

        success_rate = closures with status 0  /  closures where a cap was present

    Both denominators are always returned, and `denominator_explained` states
    in words which one was used, so a report can never be ambiguous about it.
    No Load is reported as its own KPI: sustained No Load means bottles are not
    arriving, which is a real operational signal, not noise to hide.
"""

from __future__ import annotations

import numpy as np
from scipy import stats
import pandas as pd

from ..common import timeutils
from ..common.envelope import data_window, envelope, failure
from ..common.registry import tool
from ..common.schema import TORQUE_UNIT

DEFAULT_MIN_N = 30


def _apply_filters(events, *, start=None, end=None, head_id=None,
                   machine_id=None, cap_present_only=False):
    """The one place filters are applied, so every tool filters identically."""
    applied: list[str] = []
    out = events

    lo = timeutils.parse_bound(start)
    if lo is not None:
        out = out[out["ts"] >= lo]
        applied.append(f"start>={lo.isoformat()}")
    hi = timeutils.parse_bound(end)
    if hi is not None:
        out = out[out["ts"] < hi]
        applied.append(f"end<{hi.isoformat()}")

    if head_id is not None:
        heads = [head_id] if isinstance(head_id, str) else list(head_id)
        out = out[out["head_id"].isin(heads)]
        applied.append(f"head_id in {heads}")

    if machine_id is not None:
        out = out[out["machine_id"] == machine_id]
        applied.append(f"machine_id={machine_id}")

    if cap_present_only:
        out = out[out["cap_present"]]
        applied.append("cap_present=True")

    return out, applied


def _confidence_note(n, min_n):
    """The honest caveat. meta.n drives it - never prose."""
    if n == 0:
        return "no events matched; nothing can be concluded"
    if n < min_n:
        return f"n={n} is below min_n={min_n}; treat as indicative, not significant"
    return ""


def _rates(frame):
    """The KPI block computed on one group of events."""
    n_all = int(len(frame))
    cap = frame["cap_present"]
    n_cap = int(cap.sum())
    n_ok = int((frame["status"] == 0).sum())
    n_reject = int(frame["reject_signal"].sum())
    n_no_load = int(n_all - n_cap)
    return {
        "n_cycles": n_all,
        "n_cap_present": n_cap,
        "n_success": n_ok,
        "n_reject": n_reject,
        "n_no_load": n_no_load,
        # The agreed denominator.
        "success_rate": (n_ok / n_cap) if n_cap else None,
        "reject_rate": (n_reject / n_cap) if n_cap else None,
        # The other one, always reported so the report cannot mislead.
        "success_rate_all_cycles": (n_ok / n_all) if n_all else None,
        "no_load_rate": (n_no_load / n_all) if n_all else None,
    }


DENOMINATOR_NOTE = (
    "success_rate and reject_rate use cap-present closures (status 0 or 65) as "
    "the denominator; No Load cycles (status 2) are excluded because no cap was "
    "present to close. success_rate_all_cycles uses every cycle instead."
)


@tool(name="success_rate",
      description=("Overall capping KPIs: success rate, reject rate and No Load "
                   "rate, optionally grouped into time buckets. Use this for "
                   "'how is the machine performing' questions."),
      params=["start", "end", "head_id", "machine_id", "bucket", "min_n"],
      agent="kpi", owner="B")
def success_rate(events, *, start=None, end=None, head_id=None,
                 machine_id=None, bucket=None, min_n=DEFAULT_MIN_N):
    frame, applied = _apply_filters(events, start=start, end=end,
                                    head_id=head_id, machine_id=machine_id)
    if frame.empty:
        return failure("no closures matched the requested filters",
                       tool="success_rate", n=0)

    result = {"overall": _rates(frame), "denominator_explained": DENOMINATOR_NOTE}

    if bucket:
        keys = timeutils.floor_to(frame["ts"], bucket)
        rows = []
        for key, group in frame.groupby(keys, sort=True):
            row = {"bucket_start": key.isoformat(), "bucket": bucket}
            row.update(_rates(group))
            rows.append(row)
        result["by_bucket"] = rows
        applied.append(f"bucket={bucket}")

    return envelope(result, n=len(frame), tool="success_rate",
                    filters_applied=applied, window=data_window(frame),
                    units={"torque": TORQUE_UNIT, "rates": "fraction of 1"},
                    notes=_confidence_note(len(frame), min_n))


@tool(name="success_rate_per_head",
      description=("Per-head breakdown of success, reject and No Load rates, "
                   "ranked worst-first. Use this to find which head is "
                   "underperforming."),
      params=["start", "end", "machine_id", "min_n"],
      agent="kpi", owner="B")
def success_rate_per_head(events, *, start=None, end=None, machine_id=None,
                          min_n=DEFAULT_MIN_N):
    frame, applied = _apply_filters(events, start=start, end=end,
                                    machine_id=machine_id)
    if frame.empty:
        return failure("no closures matched the requested filters",
                       tool="success_rate_per_head", n=0)

    rows = []
    for (head, index), group in frame.groupby(["head_id", "head_index"], sort=True):
        row = {"head_id": head, "head_index": int(index)}
        row.update(_rates(group))
        row["below_min_n"] = row["n_cap_present"] < min_n
        rows.append(row)

    # Worst success rate first; heads with no cap-present closures go last.
    rows.sort(key=lambda r: (r["success_rate"] is None,
                             r["success_rate"] if r["success_rate"] is not None else 0))

    return envelope(
        {"per_head": rows,
         "n_heads": len(rows),
         "worst_head": rows[0]["head_id"] if rows else None,
         "denominator_explained": DENOMINATOR_NOTE},
        n=len(frame), tool="success_rate_per_head", filters_applied=applied,
        window=data_window(frame), units={"rates": "fraction of 1"},
        notes=_confidence_note(len(frame), min_n))


@tool(name="anomaly_heads",
      description=("Flag heads whose reject rate is a statistical outlier "
                   "against the other heads on the same machine. Use this for "
                   "'is anything wrong' and anomaly-summary questions."),
      params=["start", "end", "machine_id", "sigma", "min_n"],
      agent="kpi", owner="B")
def anomaly_heads(events, *, start=None, end=None, machine_id=None,
                  sigma=3.0, min_n=DEFAULT_MIN_N):
    frame, applied = _apply_filters(events, start=start, end=end,
                                    machine_id=machine_id,
                                    cap_present_only=True)
    if frame.empty:
        return failure("no cap-present closures matched the requested filters",
                       tool="anomaly_heads", n=0)

    per_head = frame.groupby("head_id").agg(
        n_cap_present=("reject_signal", "size"),
        n_reject=("reject_signal", "sum"),
    )
    per_head["reject_rate"] = per_head["n_reject"] / per_head["n_cap_present"]

    # Why not a z-score on the rates: reject counts are small integers, so when
    # most heads sit on 0 or 1 rejects the standard deviation - and the median
    # absolute deviation with it - collapses towards zero, and a head with two
    # rejects instead of one scores as a wild outlier. Any purely rate-based
    # spread measure ignores how many closures the rate was computed from.
    #
    # Instead: take the fleet median rate as the null hypothesis (robust - one
    # bad head cannot drag the median), then ask how surprising each head's
    # reject count is under an exact binomial test given ITS OWN sample size.
    # Bonferroni-correct across heads, because we are running one test per head.
    rates = per_head["reject_rate"]
    median = float(rates.median())
    total = int(per_head["n_cap_present"].sum())
    # A null rate below "one reject in the entire dataset" is not credible.
    null_rate = max(median, 0.5 / total if total else 0.5)

    # sigma stays the user-facing knob (it is in the shared vocabulary);
    # convert it to a one-sided normal tail probability.
    alpha = float(stats.norm.sf(float(sigma)))
    alpha_corrected = alpha / max(len(per_head), 1)

    rows = []
    for head, row in per_head.iterrows():
        n_head = int(row["n_cap_present"])
        k = int(row["n_reject"])
        if n_head < min_n:
            continue
        p_value = float(stats.binomtest(k, n_head, null_rate,
                                        alternative="greater").pvalue)
        if p_value < alpha_corrected:
            rows.append({
                "head_id": head,
                "reject_rate": float(row["reject_rate"]),
                "n_cap_present": n_head,
                "n_reject": k,
                "expected_rejects": round(null_rate * n_head, 2),
                "rate_ratio": round(float(row["reject_rate"]) / null_rate, 1),
                "p_value": p_value,
            })
    rows.sort(key=lambda r: (-r["reject_rate"], r["head_id"]))

    return envelope(
        {"flagged_heads": rows,
         "n_flagged": len(rows),
         "fleet_median_reject_rate": median,
         "null_reject_rate": null_rate,
         "sigma": float(sigma),
         "alpha": alpha_corrected,
         "method": (f"exact binomial upper-tail test per head against the fleet "
                    f"median reject rate ({null_rate:.2%}), Bonferroni-corrected "
                    f"across {len(per_head)} heads at sigma={sigma} "
                    f"(alpha={alpha_corrected:.2e}); cap-present closures only")},
        n=len(frame), tool="anomaly_heads", filters_applied=applied,
        window=data_window(frame), units={"rates": "fraction of 1"},
        notes=_confidence_note(len(frame), min_n))


@tool(name="idle_periods",
      description=("Find sustained No Load stretches per head - the machine "
                   "cycling with no bottles arriving. Use this for idle, "
                   "downtime or starvation questions."),
      params=["start", "end", "head_id", "window_seconds", "min_n"],
      agent="kpi", owner="B")
def idle_periods(events, *, start=None, end=None, head_id=None,
                 window_seconds=300, min_n=DEFAULT_MIN_N):
    frame, applied = _apply_filters(events, start=start, end=end, head_id=head_id)
    if frame.empty:
        return failure("no closures matched the requested filters",
                       tool="idle_periods", n=0)
    applied.append(f"window_seconds={window_seconds}")

    periods = []
    for head, group in frame.groupby("head_id", sort=True):
        group = group.sort_values("ts")
        no_load = ~group["cap_present"]
        # A new run starts wherever the head was NOT idle.
        run_id = (~no_load).cumsum()
        for _, run in group[no_load].groupby(run_id[no_load]):
            duration = (run["ts"].iloc[-1] - run["ts"].iloc[0]).total_seconds()
            if duration >= float(window_seconds):
                periods.append({
                    "head_id": head,
                    "start": run["ts"].iloc[0].isoformat(),
                    "end": run["ts"].iloc[-1].isoformat(),
                    "duration_seconds": float(duration),
                    "n_cycles": int(len(run)),
                })

    periods.sort(key=lambda p: (-p["duration_seconds"], p["head_id"]))
    total = sum(p["duration_seconds"] for p in periods)

    return envelope(
        {"idle_periods": periods,
         "n_periods": len(periods),
         "total_idle_seconds": total,
         "heads_affected": sorted({p["head_id"] for p in periods}),
         "threshold_seconds": float(window_seconds)},
        n=len(frame), tool="idle_periods", filters_applied=applied,
        window=data_window(frame), units={"duration": "seconds"},
        notes=_confidence_note(len(frame), min_n))


@tool(name="throughput",
      description=("Capping speed: closures per hour, overall and per time "
                   "bucket. Use this for output, speed or productivity "
                   "questions."),
      params=["start", "end", "head_id", "machine_id", "bucket", "min_n"],
      agent="kpi", owner="B")
def throughput(events, *, start=None, end=None, head_id=None, machine_id=None,
               bucket="hour", min_n=DEFAULT_MIN_N):
    frame, applied = _apply_filters(events, start=start, end=end,
                                    head_id=head_id, machine_id=machine_id)
    if frame.empty:
        return failure("no closures matched the requested filters",
                       tool="throughput", n=0)

    # count_delta, not row count: a dropped poll means the counter advanced by
    # more than one and those closures really happened (audit F6).
    total_closures = int(frame["count_delta"].sum())
    span_hours = max(
        (frame["ts"].max() - frame["ts"].min()).total_seconds() / 3600.0, 1e-9)

    rows = []
    if bucket:
        keys = timeutils.floor_to(frame["ts"], bucket)
        grouped = frame.groupby(keys, sort=True)["count_delta"].sum()
        width = {"hour": 1.0, "shift": 8.0, "day": 24.0, "week": 168.0}[bucket]
        rows = [{"bucket_start": key.isoformat(),
                 "closures": int(value),
                 "closures_per_hour": float(value) / width}
                for key, value in grouped.items()]
        applied.append(f"bucket={bucket}")

    return envelope(
        {"total_closures": total_closures,
         "span_hours": round(span_hours, 4),
         "mean_closures_per_hour": total_closures / span_hours,
         "n_inferred_closures": int(frame.loc[frame["inferred"], "count_delta"].sum()
                                    - frame["inferred"].sum()),
         "by_bucket": rows},
        n=len(frame), tool="throughput", filters_applied=applied,
        window=data_window(frame),
        units={"throughput": "closures/hour"},
        notes=_confidence_note(len(frame), min_n))
