import polars as pl

from src.analytics.torque_stats import (
    _apply_status_filter,
    _as_lazy,
    _validate_event_schema,
)


def _validate_bins(bins):
    """
    Validate the requested number of histogram bins.
    """

    if isinstance(bins, bool):
        raise TypeError(
            "bins must be a positive integer"
        )

    if not isinstance(bins, int):
        raise TypeError(
            "bins must be a positive integer"
        )

    if bins <= 0:
        raise ValueError(
            "bins must be greater than zero"
        )


def _prepare_torque_events(
    events: pl.DataFrame | pl.LazyFrame,
    status_filter=None,
) -> pl.LazyFrame:
    """
    Prepare valid torque observations from the clean
    event table.

    Null, NaN, and infinite torque values are excluded.
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

    return filtered.filter(
        pl.col("torque").is_not_null()
        & pl.col("torque").is_finite()
    )


def _build_bin_edges(
    minimum: float,
    maximum: float,
    bins: int,
) -> list[float]:
    """
    Build equal-width histogram bin edges.

    If all torque observations have the same value,
    create a small symmetric range around that value
    so a valid histogram can still be returned.
    """

    if minimum == maximum:
        minimum = minimum - 0.5
        maximum = maximum + 0.5

    width = (
        maximum - minimum
    ) / bins

    edges = [
        minimum + width * index
        for index in range(
            bins + 1
        )
    ]

    # Avoid floating-point accumulation making the
    # final edge slightly different from the maximum.
    edges[-1] = maximum

    return [
        float(edge)
        for edge in edges
    ]


def _count_histogram_bins(
    events: pl.LazyFrame,
    bin_edges: list[float],
) -> list[int]:
    """
    Count torque observations in each histogram bin.

    Histogram convention:

        [left, right)

    for every bin except the final bin, which is:

        [left, right]

    This ensures the maximum torque observation is
    included exactly once.
    """

    count_expressions = []

    last_bin_index = (
        len(bin_edges) - 2
    )

    for index in range(
        len(bin_edges) - 1
    ):
        left = bin_edges[index]
        right = bin_edges[index + 1]

        if index == last_bin_index:
            condition = (
                (pl.col("torque") >= left)
                & (pl.col("torque") <= right)
            )
        else:
            condition = (
                (pl.col("torque") >= left)
                & (pl.col("torque") < right)
            )

        count_expressions.append(
            condition
            .sum()
            .cast(pl.Int64)
            .alias(
                f"bin_{index}"
            )
        )

    result = (
        events
        .select(
            count_expressions
        )
        .collect()
    )

    return [
        int(value)
        for value in result.row(0)
    ]


def torque_distribution(
    events: pl.DataFrame | pl.LazyFrame,
    bins: int = 10,
    status_filter=None,
) -> dict:
    """
    Calculate the torque histogram for the clean
    event table.

    Parameters
    ----------
    events:
        Clean Polars event DataFrame or LazyFrame.

    bins:
        Number of equal-width histogram bins.

    status_filter:
        Optional filter using the same semantics as
        torque_stats():

        None
            all events

        "successful"
            status == 0

        integer
            exact raw AROL status code

    Returns
    -------
    dict
        {
            "bin_edges": list[float],
            "counts": list[int],
            "sample_size": int,
        }

    Notes
    -----
    Histogram bins use:

        [left, right)

    except the final bin, which includes its right edge.

    Null and non-finite torque values are excluded.

    Output consists only of plain Python values and is
    JSON serializable.
    """

    _validate_bins(
        bins
    )

    torque_events = _prepare_torque_events(
        events,
        status_filter,
    )

    summary = (
        torque_events
        .select(
            pl.len().alias(
                "sample_size"
            ),
            pl.col("torque")
            .min()
            .alias("minimum"),
            pl.col("torque")
            .max()
            .alias("maximum"),
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
            "bin_edges": [],
            "counts": [],
            "sample_size": 0,
        }

    minimum = float(
        summary["minimum"]
    )

    maximum = float(
        summary["maximum"]
    )

    bin_edges = _build_bin_edges(
        minimum,
        maximum,
        bins,
    )

    counts = _count_histogram_bins(
        torque_events,
        bin_edges,
    )

    return {
        "bin_edges": bin_edges,
        "counts": counts,
        "sample_size": sample_size,
    }