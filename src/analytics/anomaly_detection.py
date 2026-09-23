import math

import polars as pl

from src.analytics.torque_stats import (
    _apply_status_filter,
    _as_lazy,
)


def _validate_anomaly_schema(
    events: pl.LazyFrame,
) -> None:
    """
    Validate the clean event-table columns required
    by anomaly detection.
    """

    schema = events.collect_schema()

    required = {
        "ts",
        "machine_id",
        "head_id",
        "torque",
        "status",
    }

    missing = required - set(
        schema.names()
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


def _get_anomaly_config(
    config: dict,
) -> tuple[float, float, float]:
    """
    Read and validate anomaly configuration.

    Required:

        analytics:
            torque_expected_min
            torque_expected_max
            anomaly_sigma
    """

    try:
        analytics = config[
            "analytics"
        ]

        expected_min = analytics[
            "torque_expected_min"
        ]

        expected_max = analytics[
            "torque_expected_max"
        ]

        sigma = analytics[
            "anomaly_sigma"
        ]

    except (
        KeyError,
        TypeError,
    ) as exc:
        raise ValueError(
            "Missing anomaly configuration. "
            "Required: "
            "analytics.torque_expected_min, "
            "analytics.torque_expected_max, "
            "analytics.anomaly_sigma"
        ) from exc

    for name, value in (
        (
            "torque_expected_min",
            expected_min,
        ),
        (
            "torque_expected_max",
            expected_max,
        ),
        (
            "anomaly_sigma",
            sigma,
        ),
    ):
        if isinstance(
            value,
            bool,
        ):
            raise TypeError(
                f"analytics.{name} "
                "must be numeric"
            )

        if not isinstance(
            value,
            (int, float),
        ):
            raise TypeError(
                f"analytics.{name} "
                "must be numeric"
            )

        if not math.isfinite(
            float(value)
        ):
            raise ValueError(
                f"analytics.{name} "
                "must be finite"
            )

    expected_min = float(
        expected_min
    )

    expected_max = float(
        expected_max
    )

    sigma = float(
        sigma
    )

    if expected_min > expected_max:
        raise ValueError(
            "analytics.torque_expected_min "
            "must be <= "
            "analytics.torque_expected_max"
        )

    if sigma <= 0:
        raise ValueError(
            "analytics.anomaly_sigma "
            "must be greater than zero"
        )

    return (
        expected_min,
        expected_max,
        sigma,
    )


def _prepare_anomaly_events(
    events: pl.DataFrame | pl.LazyFrame,
    status_filter=None,
) -> pl.LazyFrame:
    """
    Prepare valid event-level torque observations.

    Null, NaN, and infinite torque values are excluded.
    """

    lazy_events = _as_lazy(
        events
    )

    _validate_anomaly_schema(
        lazy_events
    )

    filtered = _apply_status_filter(
        lazy_events,
        status_filter,
    )

    return (
        filtered
        .filter(
            pl.col("torque")
            .is_not_null()
            & pl.col("torque")
            .is_finite()
        )
        .sort(
            [
                "ts",
                "head_id",
            ]
        )
    )


def detect_torque_anomalies(
    events: pl.DataFrame | pl.LazyFrame,
    config: dict,
    status_filter=None,
) -> dict:
    """
    Detect torque anomalies using two deterministic
    mechanisms:

    1. configured engineering thresholds
    2. statistical deviation from the observed mean

    Parameters
    ----------
    events:
        Clean Polars event DataFrame or LazyFrame.

    config:
        Project configuration.

        Required values:

            analytics:
                torque_expected_min
                torque_expected_max
                anomaly_sigma

    status_filter:
        Optional filter with the same semantics used
        by the other torque analytics.

        None:
            all events

        "successful":
            status == 0

        integer:
            exact AROL status code

    Returns
    -------
    dict
        JSON-safe result containing:

            sample_size
            anomaly_count
            anomaly_rate
            mean
            std
            expected_min
            expected_max
            sigma
            anomalies

    Each anomaly contains a human-readable `reason`.

    Statistical deviation uses the sample standard
    deviation (ddof=1).
    """

    (
        expected_min,
        expected_max,
        sigma,
    ) = _get_anomaly_config(
        config
    )

    prepared = (
        _prepare_anomaly_events(
            events,
            status_filter,
        )
    )

    summary = (
        prepared
        .select(
            pl.len().alias(
                "sample_size"
            ),
            pl.col("torque")
            .mean()
            .alias("mean"),
            pl.col("torque")
            .std(
                ddof=1
            )
            .alias("std"),
        )
        .collect()
        .row(
            0,
            named=True,
        )
    )

    sample_size = int(
        summary["sample_size"]
    )

    if sample_size == 0:
        return {
            "sample_size": 0,
            "anomaly_count": 0,
            "anomaly_rate": 0.0,
            "mean": None,
            "std": None,
            "expected_min": (
                expected_min
            ),
            "expected_max": (
                expected_max
            ),
            "sigma": sigma,
            "anomalies": [],
        }

    mean = float(
        summary["mean"]
    )

    std_value = summary[
        "std"
    ]

    std = (
        None
        if std_value is None
        else float(
            std_value
        )
    )

    statistical_detection_available = (
        std is not None
        and std > 0.0
        and math.isfinite(
            std
        )
    )

    below_expected = (
        pl.col("torque")
        < expected_min
    )

    above_expected = (
        pl.col("torque")
        > expected_max
    )

    if statistical_detection_available:
        z_score_expression = (
            (
                pl.col("torque")
                - mean
            )
            .abs()
            / std
        )

        statistical_deviation = (
            z_score_expression
            > sigma
        )

    else:
        z_score_expression = pl.lit(
            None,
            dtype=pl.Float64,
        )

        statistical_deviation = pl.lit(
            False
        )

    annotated = (
        prepared
        .with_columns(
            below_expected.alias(
                "__below_expected"
            ),
            above_expected.alias(
                "__above_expected"
            ),
            z_score_expression.alias(
                "z_score"
            ),
            statistical_deviation.alias(
                "__statistical_deviation"
            ),
        )
        .with_columns(
            pl.concat_str(
                [
                    pl.when(
                        pl.col(
                            "__below_expected"
                        )
                    )
                    .then(
                        pl.lit(
                            "below_expected_min"
                        )
                    )
                    .otherwise(
                        pl.lit(
                            None,
                            dtype=pl.String,
                        )
                    ),

                    pl.when(
                        pl.col(
                            "__above_expected"
                        )
                    )
                    .then(
                        pl.lit(
                            "above_expected_max"
                        )
                    )
                    .otherwise(
                        pl.lit(
                            None,
                            dtype=pl.String,
                        )
                    ),

                    pl.when(
                        pl.col(
                            "__statistical_deviation"
                        )
                    )
                    .then(
                        pl.lit(
                            "statistical_deviation"
                        )
                    )
                    .otherwise(
                        pl.lit(
                            None,
                            dtype=pl.String,
                        )
                    ),
                ],
                separator="|",
                ignore_nulls=True,
            )
            .alias(
                "reason"
            )
        )
        .filter(
            pl.col(
                "__below_expected"
            )
            | pl.col(
                "__above_expected"
            )
            | pl.col(
                "__statistical_deviation"
            )
        )
        .select(
            pl.col("ts")
            .cast(pl.String)
            .alias("ts"),

            pl.col(
                "machine_id"
            ),

            pl.col(
                "head_id"
            ),

            pl.col(
                "torque"
            )
            .cast(
                pl.Float64
            ),

            pl.col(
                "status"
            )
            .cast(
                pl.Int64
            ),

            pl.col(
                "z_score"
            )
            .cast(
                pl.Float64
            ),

            pl.col(
                "reason"
            ),
        )
        .collect()
    )

    anomaly_count = int(
        annotated.height
    )

    anomaly_rate = (
        anomaly_count
        / sample_size
    )

    return {
        "sample_size": sample_size,
        "anomaly_count": (
            anomaly_count
        ),
        "anomaly_rate": float(
            anomaly_rate
        ),
        "mean": mean,
        "std": std,
        "expected_min": (
            expected_min
        ),
        "expected_max": (
            expected_max
        ),
        "sigma": sigma,
        "anomalies": (
            annotated.to_dicts()
        ),
    }