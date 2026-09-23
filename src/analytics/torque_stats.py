import polars as pl


SUCCESS_STATUS = 0


def _as_lazy(
    events: pl.DataFrame | pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Normalize a Polars DataFrame or LazyFrame to LazyFrame.
    """

    if isinstance(events, pl.LazyFrame):
        return events

    if isinstance(events, pl.DataFrame):
        return events.lazy()

    raise TypeError(
        "events must be a Polars DataFrame or LazyFrame"
    )


def _validate_event_schema(
    events: pl.LazyFrame,
) -> None:
    """
    Verify that the columns required for torque statistics exist.
    """

    schema = events.collect_schema()

    required_columns = {
        "torque",
        "status",
    }

    missing = required_columns - set(schema.names())

    if missing:
        missing_text = ", ".join(
            sorted(missing)
        )

        raise ValueError(
            f"Missing required event columns: {missing_text}"
        )


def _apply_status_filter(
    events: pl.LazyFrame,
    status_filter,
) -> pl.LazyFrame:
    """
    Apply the optional event-status filter.

    Supported values:

        None
            Use all events.

        "successful"
            Use Closure OK events only (status 0).

        int
            Use exactly that numeric AROL status code.
    """

    if status_filter is None:
        return events

    if isinstance(status_filter, str):

        normalized = (
            status_filter
            .strip()
            .lower()
        )

        if normalized == "successful":
            return events.filter(
                pl.col("status")
                == SUCCESS_STATUS
            )

        raise ValueError(
            "Unsupported status_filter string. "
            'Use "successful", an integer status code, '
            "or None."
        )

    if isinstance(status_filter, bool):
        raise TypeError(
            "status_filter must be None, "
            '"successful", or an integer status code'
        )

    if isinstance(status_filter, int):
        return events.filter(
            pl.col("status")
            == status_filter
        )

    raise TypeError(
        "status_filter must be None, "
        '"successful", or an integer status code'
    )


def torque_stats(
    events: pl.DataFrame | pl.LazyFrame,
    status_filter=None,
) -> dict:
    """
    Calculate deterministic torque statistics over the clean
    event table.

    Parameters
    ----------
    events:
        Clean Polars event DataFrame or LazyFrame.

    status_filter:
        Optional filter.

        None:
            all events

        "successful":
            status == 0

        integer:
            exact AROL status code

    Returns
    -------
    dict
        {
            "mean": float | None,
            "min": float | None,
            "max": float | None,
            "std": float | None,
            "sample_size": int,
        }

    Notes
    -----
    Standard deviation is the sample standard deviation
    (ddof=1).

    Null/non-finite torque values are excluded from the
    statistics.

    Output contains plain Python values and is therefore
    JSON serializable.
    """

    lazy_events = _as_lazy(
        events
    )

    _validate_event_schema(
        lazy_events
    )

    filtered = _apply_status_filter(
        lazy_events,
        status_filter,
    )

    # Analytics operate only on valid finite torque
    # observations from the clean event table.
    filtered = filtered.filter(
        pl.col("torque").is_not_null()
        & pl.col("torque").is_finite()
    )

    result = (
        filtered
        .select(
            pl.len().alias(
                "sample_size"
            ),
            pl.col("torque")
            .mean()
            .alias("mean"),
            pl.col("torque")
            .min()
            .alias("min"),
            pl.col("torque")
            .max()
            .alias("max"),
            pl.col("torque")
            .std(ddof=1)
            .alias("std"),
        )
        .collect()
        .row(
            0,
            named=True,
        )
    )

    sample_size = int(
        result["sample_size"]
    )

    def plain_float(value):
        if value is None:
            return None

        return float(value)

    return {
        "mean": plain_float(
            result["mean"]
        ),
        "min": plain_float(
            result["min"]
        ),
        "max": plain_float(
            result["max"]
        ),
        "std": plain_float(
            result["std"]
        ),
        "sample_size": sample_size,
    }