"""Expose Person A's torque statistics through the shared registry."""

import polars as pl

from ..common.envelope import data_window, envelope
from ..common.registry import tool
from .event_filters import filter_events
from .torque_stats import (
    _apply_status_filter,
    torque_stats as calculate_torque_stats,
)


@tool(
    name="torque_stats",
    description=(
        "Mean, minimum, maximum and sample standard deviation of finite "
        "torque readings from observed exact +1 closure events. "
        "Optionally select successful closures or an exact status code."
    ),
    params=["start", "end", "head_id", "machine_id", "status_filter"],
    agent="analytics",
    owner="A",
)
def registered_torque_stats(events, *, status_filter=None,
                            start=None, end=None, head_id=None, machine_id=None):
    # The existing analytics function remains responsible for the numbers.
    scoped, applied = filter_events(
        events, start=start, end=end, head_id=head_id, machine_id=machine_id
    )
    result = calculate_torque_stats(scoped, status_filter=status_filter)

    # Metadata describes the observations actually used in the calculation.
    used = _apply_status_filter(scoped, status_filter).filter(
        pl.col("torque").is_not_null() & pl.col("torque").is_finite()
    ).collect()

    filters = applied + ["torque is non-null and finite"]
    if status_filter is not None:
        filters.insert(0, f"status_filter={status_filter!r}")

    notes = (
        "Statistics describe observed exact +1 closure events. "
        "Counter discontinuities are not reconstructed as closures. "
        "Standard deviation uses ddof=1."
    )
    if result["sample_size"] == 0:
        notes += " No finite torque observations matched."

    return envelope(
        result,
        n=result["sample_size"],
        tool="torque_stats",
        filters_applied=filters,
        notes=notes,
        units={key: "Nm" for key in ("mean", "min", "max", "std")},
        window=data_window(used),
    )
