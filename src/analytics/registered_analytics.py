"""Thin registered adapters for the remaining four Person A analytics tools."""

import polars as pl

from ..common.envelope import data_window, envelope
from ..common.registry import tool
from ..common.runtime import current_config
from . import registered_torque  # noqa: F401 - register the first tool too
from .event_filters import filter_events
from .torque_distribution import torque_distribution, _prepare_torque_events
from .trend_analysis import torque_trend, DRIFT_EPSILON
from .anomaly_detection import detect_torque_anomalies
from .head_correlation import (
    head_correlation, _validate_head_ids, _matched_torque_pairs,
)

SCOPE = ["start", "end", "head_id", "machine_id", "status_filter"]
OBSERVED_NOTE = (
    "Only supplied observed exact +1 events are analysed. "
    "Counter discontinuities are not reconstructed. "
)


def _finish(result, scoped, applied, status_filter, *, units, notes):
    used = _prepare_torque_events(scoped, status_filter).collect()
    filters = list(applied)
    if status_filter is not None:
        filters.append(f"status_filter={status_filter!r}")
    filters.append("torque is non-null and finite")
    if result["sample_size"] == 0:
        notes += " No finite torque observations matched."
    return envelope(
        result, n=result["sample_size"], filters_applied=filters,
        units=units, window=data_window(used), notes=OBSERVED_NOTE + notes,
    )


@tool(name="torque_distribution", description=(
    "Equal-width histogram of finite torque observations in the requested scope."
), params=SCOPE + ["bins"], owner="A")
def registered_distribution(events, *, bins=10, status_filter=None,
                            start=None, end=None, head_id=None, machine_id=None):
    scoped, applied = filter_events(
        events, start=start, end=end, head_id=head_id, machine_id=machine_id,
    )
    result = torque_distribution(scoped, bins=bins, status_filter=status_filter)
    return _finish(
        result, scoped, applied, status_filter,
        units={"bin_edges": "Nm", "counts": "observations"},
        notes=("Bins are left-inclusive and right-exclusive except the final bin, "
               "which includes its right edge. A histogram alone does not diagnose a fault."),
    )


@tool(name="torque_trend", description=(
    "Time-based torque moving average and numerical drift signal. "
    "The trailing window is supplied by trusted project configuration."
), params=SCOPE, owner="A")
def registered_trend(events, *, status_filter=None,
                     start=None, end=None, head_id=None, machine_id=None):
    scoped, applied = filter_events(
        events, start=start, end=end, head_id=head_id, machine_id=machine_id,
    )
    result = torque_trend(scoped, current_config(), status_filter=status_filter)
    return _finish(
        result, scoped, applied, status_filter,
        units={"moving_average": "Nm", "drift_slope_per_second": "Nm/s",
               "window_seconds": "s"},
        notes=(f"The configured trailing window is {result['window_seconds']} seconds. "
               f"The direction uses a numerical epsilon of {DRIFT_EPSILON:g} Nm/s, "
               "not an engineering or statistical significance threshold. "
               "Selected observations are pooled; this is not a separate trend per head. "
               "The requested scope supplies all available history for this calculation."),
    )


@tool(name="detect_torque_anomalies", description=(
    "Flag finite torque observations outside configured limits or a configured "
    "sample-standard-deviation threshold. Settings come from trusted configuration."
), params=SCOPE, owner="A")
def registered_anomalies(events, *, status_filter=None,
                         start=None, end=None, head_id=None, machine_id=None):
    scoped, applied = filter_events(
        events, start=start, end=end, head_id=head_id, machine_id=machine_id,
    )
    result = detect_torque_anomalies(
        scoped, current_config(), status_filter=status_filter,
    )
    return _finish(
        result, scoped, applied, status_filter,
        units={"mean": "Nm", "std": "Nm", "expected_min": "Nm",
               "expected_max": "Nm", "anomaly_rate": "fraction"},
        notes=(f"Configured limits: {result['expected_min']} to {result['expected_max']} Nm; "
               f"sigma={result['sigma']}. Statistical comparison pools the selected "
               "observations and uses sample standard deviation (ddof=1). "
               "Configuration values require process validation; flags do not establish a cause."),
    )


@tool(name="head_correlation", description=(
    "Compare two heads using same-timestamp finite torque pairs on one machine. "
    "Also return each head's existing Person A summaries and success denominator."
), params=["head_a", "head_b", "start", "end", "machine_id"],
      required=["head_a", "head_b"], owner="A")
def registered_head_correlation(events, *, head_a, head_b,
                                start=None, end=None, machine_id=None):
    _validate_head_ids(head_a, head_b)
    scoped, applied = filter_events(
        events, start=start, end=end, machine_id=machine_id,
    )
    if "machine_id" not in scoped.collect_schema():
        raise ValueError("head_correlation requires machine_id to prevent cross-machine pairing")
    selected = scoped.filter(pl.col("head_id").is_in([head_a, head_b])).collect()
    if selected.height:
        if selected["machine_id"].null_count() or selected["ts"].null_count():
            raise ValueError("Correlation requires non-null machine identifiers and timestamps")
        if selected["machine_id"].n_unique() != 1:
            raise ValueError("Select one machine_id before comparing heads")
        if selected.select("head_id", "ts").is_duplicated().any():
            raise ValueError("Duplicate head/timestamp observations make correlation pairing ambiguous")
    result = head_correlation(selected, head_a, head_b)
    matched = _matched_torque_pairs(selected, head_a, head_b)
    response = envelope(
        result, n=result["matched_torque_samples"],
        filters_applied=applied + [f"head pair: {head_a}, {head_b}"],
        units={"mean_torque": "Nm", "torque_correlation": "dimensionless",
               "success_rate_difference": "fraction",
               "success_rate_difference_percentage_points": "percentage points"},
        window=data_window(selected),
        notes=(OBSERVED_NOTE + "n counts matched finite torque pairs. The main data window "
               "covers both heads' summary observations. Person A's success denominator "
               "uses events with non-null error_class other than 'No Load'; it is not "
               "the cap_present=True denominator used by Person B's KPI tools. "
               "Correlation does not establish causation. Ambiguous pairings are rejected, "
               "not deduplicated or paired across machines."),
    )
    response["meta"]["correlation_data_window"] = data_window(matched)
    return response
