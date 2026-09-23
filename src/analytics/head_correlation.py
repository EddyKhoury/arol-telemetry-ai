import math

import polars as pl

from src.analytics.torque_stats import (
    _as_lazy,
)


STRONG_CORRELATION = 0.8
MODERATE_CORRELATION = 0.5
CORRELATION_EPSILON = 1e-12


def _validate_head_correlation_schema(
    events: pl.LazyFrame,
) -> None:
    """
    Validate the columns required for head-to-head
    comparison.
    """

    schema = events.collect_schema()

    required = {
        "ts",
        "head_id",
        "torque",
        "status",
        "error_class",
    }

    missing = (
        required
        - set(
            schema.names()
        )
    )

    if missing:
        missing_text = ", ".join(
            sorted(missing)
        )

        raise ValueError(
            "Missing required event columns: "
            f"{missing_text}"
        )

    if (
        schema["ts"].base_type()
        != pl.Datetime
    ):
        raise TypeError(
            "ts must be a Polars Datetime column"
        )


def _validate_head_ids(
    head_a,
    head_b,
) -> None:
    """
    Validate requested head identifiers.
    """

    if not isinstance(
        head_a,
        str,
    ):
        raise TypeError(
            "head_a must be a string"
        )

    if not isinstance(
        head_b,
        str,
    ):
        raise TypeError(
            "head_b must be a string"
        )

    if not head_a.strip():
        raise ValueError(
            "head_a must not be empty"
        )

    if not head_b.strip():
        raise ValueError(
            "head_b must not be empty"
        )

    if head_a == head_b:
        raise ValueError(
            "head_a and head_b must be different"
        )


def _finite_torque_rows(
    events: pl.DataFrame,
) -> pl.DataFrame:
    """
    Keep only valid finite torque observations.
    """

    return events.filter(
        pl.col("torque")
        .is_not_null()
        & pl.col("torque")
        .is_finite()
    )


def _head_summary(
    events: pl.DataFrame,
    head_id: str,
) -> dict:
    """
    Calculate independent summary information for one
    head.

    No Load events are excluded from the success-rate
    denominator because they represent no cap being
    present rather than a failed cap closure.
    """

    head_events = events.filter(
        pl.col("head_id")
        == head_id
    )

    event_count = int(
        head_events.height
    )

    torque_events = (
        _finite_torque_rows(
            head_events
        )
    )

    torque_sample_size = int(
        torque_events.height
    )

    if torque_sample_size == 0:
        mean_torque = None

    else:
        mean_value = (
            torque_events
            .select(
                pl.col("torque")
                .mean()
            )
            .item()
        )

        mean_torque = float(
            mean_value
        )

    success_evaluable = (
        head_events
        .filter(
            pl.col("error_class")
            != "No Load"
        )
    )

    success_evaluable_count = int(
        success_evaluable.height
    )

    success_count = int(
        success_evaluable
        .filter(
            pl.col("status")
            == 0
        )
        .height
    )

    if success_evaluable_count == 0:
        success_rate = None

    else:
        success_rate = float(
            success_count
            / success_evaluable_count
        )

    return {
        "head_id": head_id,
        "found": (
            event_count > 0
        ),
        "event_count": event_count,
        "torque_sample_size": (
            torque_sample_size
        ),
        "mean_torque": (
            mean_torque
        ),
        "success_count": (
            success_count
        ),
        "success_evaluable_count": (
            success_evaluable_count
        ),
        "success_rate": (
            success_rate
        ),
    }


def _matched_torque_pairs(
    events: pl.DataFrame,
    head_a: str,
    head_b: str,
) -> pl.DataFrame:
    """
    Pair torque observations from two heads using the
    same event timestamp.

    This avoids pairing observations merely by row
    position when the two heads have different event
    counts.
    """

    head_a_events = (
        _finite_torque_rows(
            events.filter(
                pl.col("head_id")
                == head_a
            )
        )
        .select(
            "ts",
            pl.col("torque")
            .cast(
                pl.Float64
            )
            .alias(
                "torque_a"
            ),
        )
    )

    head_b_events = (
        _finite_torque_rows(
            events.filter(
                pl.col("head_id")
                == head_b
            )
        )
        .select(
            "ts",
            pl.col("torque")
            .cast(
                pl.Float64
            )
            .alias(
                "torque_b"
            ),
        )
    )

    return (
        head_a_events
        .join(
            head_b_events,
            on="ts",
            how="inner",
        )
        .sort(
            "ts"
        )
    )


def _calculate_torque_correlation(
    matched: pl.DataFrame,
) -> float | None:
    """
    Calculate Pearson torque correlation over timestamps
    shared by both heads.

    At least two matched observations and non-constant
    torque values on both heads are required.
    """

    if matched.height < 2:
        return None

    if (
        matched[
            "torque_a"
        ].n_unique()
        < 2
    ):
        return None

    if (
        matched[
            "torque_b"
        ].n_unique()
        < 2
    ):
        return None

    value = (
        matched
        .select(
            pl.corr(
                "torque_a",
                "torque_b",
            )
            .alias(
                "correlation"
            )
        )
        .item()
    )

    if value is None:
        return None

    value = float(
        value
    )

    if not math.isfinite(
        value
    ):
        return None

    return value


def _interpret_correlation(
    correlation: float | None,
    matched_count: int,
) -> str:
    """
    Convert the numerical Pearson correlation into a
    deterministic interpretable category.
    """

    if correlation is None:

        if matched_count < 2:
            return (
                "insufficient_overlap"
            )

        return (
            "undefined_constant_torque"
        )

    if (
        correlation
        >= STRONG_CORRELATION
    ):
        return (
            "strong_positive"
        )

    if (
        correlation
        >= MODERATE_CORRELATION
    ):
        return (
            "moderate_positive"
        )

    if (
        correlation
        <= -STRONG_CORRELATION
    ):
        return (
            "strong_negative"
        )

    if (
        correlation
        <= -MODERATE_CORRELATION
    ):
        return (
            "moderate_negative"
        )

    if (
        abs(correlation)
        <= CORRELATION_EPSILON
    ):
        return (
            "no_linear_correlation"
        )

    return (
        "weak_linear_correlation"
    )


def _success_rate_comparison(
    rate_a: float | None,
    rate_b: float | None,
) -> tuple[
    float | None,
    float | None,
    str,
]:
    """
    Compare success rates.

    Returns:
        difference as fraction
        difference in percentage points
        direction label
    """

    if (
        rate_a is None
        or rate_b is None
    ):
        return (
            None,
            None,
            "insufficient_data",
        )

    difference = float(
        rate_a - rate_b
    )

    percentage_points = float(
        difference
        * 100.0
    )

    if (
        abs(difference)
        <= CORRELATION_EPSILON
    ):
        direction = "equal"

    elif difference > 0:
        direction = (
            "head_a_higher"
        )

    else:
        direction = (
            "head_b_higher"
        )

    return (
        difference,
        percentage_points,
        direction,
    )


def head_correlation(
    events: pl.DataFrame | pl.LazyFrame,
    head_a: str,
    head_b: str,
) -> dict:
    """
    Compare the behavior of two capping heads.

    The comparison includes:

        - event counts
        - mean torque
        - torque correlation at shared timestamps
        - success rates
        - success-rate difference

    Torque correlation uses Pearson correlation over
    observations occurring at timestamps shared by both
    heads.

    Success rate excludes No Load events from the
    denominator.

    The function handles unequal head event counts
    without requiring truncation or row-position pairing.

    Returns only JSON-safe Python values.
    """

    _validate_head_ids(
        head_a,
        head_b,
    )

    lazy_events = _as_lazy(
        events
    )

    _validate_head_correlation_schema(
        lazy_events
    )

    # Collect only the two requested heads. The whole
    # event table is not materialized unnecessarily.
    selected = (
        lazy_events
        .filter(
            pl.col("head_id")
            .is_in(
                [
                    head_a,
                    head_b,
                ]
            )
        )
        .select(
            "ts",
            "head_id",
            "torque",
            "status",
            "error_class",
        )
        .collect()
    )

    summary_a = _head_summary(
        selected,
        head_a,
    )

    summary_b = _head_summary(
        selected,
        head_b,
    )

    matched = _matched_torque_pairs(
        selected,
        head_a,
        head_b,
    )

    matched_count = int(
        matched.height
    )

    torque_correlation = (
        _calculate_torque_correlation(
            matched
        )
    )

    correlation_interpretation = (
        _interpret_correlation(
            torque_correlation,
            matched_count,
        )
    )

    (
        success_rate_difference,
        success_rate_difference_pp,
        success_rate_direction,
    ) = _success_rate_comparison(
        summary_a[
            "success_rate"
        ],
        summary_b[
            "success_rate"
        ],
    )

    return {
        "head_a": summary_a,
        "head_b": summary_b,
        "matched_torque_samples": (
            matched_count
        ),
        "torque_correlation": (
            torque_correlation
        ),
        "torque_correlation_interpretation": (
            correlation_interpretation
        ),
        "success_rate_difference": (
            success_rate_difference
        ),
        "success_rate_difference_percentage_points": (
            success_rate_difference_pp
        ),
        "success_rate_direction": (
            success_rate_direction
        ),
    }