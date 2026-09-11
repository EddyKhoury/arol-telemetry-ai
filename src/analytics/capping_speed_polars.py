import polars as pl


# =========================================================
# INPUT NORMALIZATION
# =========================================================

def _as_lazy(df):
    """
    Normalize supported Polars input to LazyFrame.
    """

    if isinstance(df, pl.LazyFrame):
        return df

    if isinstance(df, pl.DataFrame):
        return df.lazy()

    raise TypeError(
        "df must be a Polars DataFrame or LazyFrame"
    )


# =========================================================
# SCALAR COMPATIBILITY FUNCTIONS
# =========================================================

def incremental_average(
    current_mean,
    new_value,
    n,
):
    """
    Update a running arithmetic mean.

    This preserves the exact reference formula:

        new_mean =
            current_mean
            + (new_value - current_mean) / n
    """

    return (
        current_mean
        +
        (
            new_value
            -
            current_mean
        )
        /
        n
    )


def closures_to_pieces_per_hour(
    closures,
    interval_seconds,
):
    """
    Convert the number of closures observed in an interval
    into pieces per hour.

    Formula:

        closures * 3600 / interval_seconds
    """

    if interval_seconds <= 0:

        raise ValueError(
            "interval_seconds must be greater than zero"
        )

    return (
        closures
        *
        3600
        /
        interval_seconds
    )


# =========================================================
# VECTORIZED PRODUCTION CALCULATION
# =========================================================

def running_capping_speed_frame(
    df,
    interval_seconds,
    closures_col="closures",
):
    """
    Calculate instantaneous and running capping speed
    using Polars expressions.

    Expected input column:

        closures

    Output:

        closures
        pieces_per_hour
        running_mean

    The operation remains lazy.

    The running mean is mathematically equivalent to the
    incremental-average reference implementation:

        cumulative sum / number of intervals
    """

    if interval_seconds <= 0:

        raise ValueError(
            "interval_seconds must be greater than zero"
        )

    lazy_df = _as_lazy(
        df
    )

    schema = (
        lazy_df
        .collect_schema()
    )

    if closures_col not in schema:

        raise ValueError(
            f"missing closures column: {closures_col}"
        )

    result = (
        lazy_df

        # Number intervals from 1 instead of 0 so the row
        # index can be used directly as the running-mean
        # denominator.
        .with_row_index(
            "__interval_number",
            offset=1,
        )

        # Convert closure count to pieces/hour.
        .with_columns(
            (
                pl.col(
                    closures_col
                )
                .cast(
                    pl.Float64
                )
                *
                3600.0
                /
                float(
                    interval_seconds
                )
            )
            .alias(
                "pieces_per_hour"
            )
        )

        # Running arithmetic mean:
        #
        #   cumulative speed / interval number
        #
        # This is mathematically equivalent to repeatedly
        # calling incremental_average().
        .with_columns(
            (
                pl.col(
                    "pieces_per_hour"
                )
                .cum_sum()
                /
                pl.col(
                    "__interval_number"
                )
                .cast(
                    pl.Float64
                )
            )
            .alias(
                "running_mean"
            )
        )

        .select(
            pl.col(
                closures_col
            ),

            pl.col(
                "pieces_per_hour"
            ),

            pl.col(
                "running_mean"
            ),
        )
    )

    return result


# =========================================================
# LIST COMPATIBILITY WRAPPER
# =========================================================

def running_capping_speed(
    closures_per_interval,
    interval_seconds,
):
    """
    Compatibility wrapper preserving the original API.

    Input:

        [2, 3, 1]

    Output:

        [7200.0, 9000.0, 7200.0]

    The calculation itself uses the vectorized Polars
    production implementation.
    """

    if interval_seconds <= 0:

        raise ValueError(
            "interval_seconds must be greater than zero"
        )

    if len(
        closures_per_interval
    ) == 0:

        return []

    df = (
        pl.DataFrame({
            "closures": (
                closures_per_interval
            )
        })
        .lazy()
    )

    result = (
        running_capping_speed_frame(
            df,
            interval_seconds=
                interval_seconds,
        )
        .select(
            "running_mean"
        )
        .collect()
    )

    return (
        result[
            "running_mean"
        ]
        .to_list()
    )