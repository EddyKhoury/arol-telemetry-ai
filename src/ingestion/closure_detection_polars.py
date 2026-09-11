import polars as pl


def _as_lazy(df):
    """
    Normalize supported Polars input to a LazyFrame.

    Production telemetry normally arrives as a LazyFrame
    from the Parquet loader, but accepting DataFrame makes
    the function easier to reuse and test.
    """

    if isinstance(df, pl.LazyFrame):
        return df

    if isinstance(df, pl.DataFrame):
        return df.lazy()

    raise TypeError(
        "df must be a Polars DataFrame or LazyFrame"
    )


def detect_head_closures_frame(
    df,
    head_id,
):
    """
    Detect closures for one capping head using Polars.

    Closure rule:

        current Count - previous Count == 1

    The event attributes belong to the CURRENT row,
    which is the row where the counter increment occurs.

    Returns a LazyFrame with:

        row_index
        head_id
        torque
        status
        timestamp

    No Python loop is performed over telemetry rows.
    """

    lazy_df = _as_lazy(df)

    count_col = (
        f"{head_id} Count"
    )

    torque_col = (
        f"{head_id} AppTorque"
    )

    status_col = (
        f"{head_id} Status"
    )

    closures = (
        lazy_df

        # Preserve the original row position before
        # filtering out non-closure rows.
        .with_row_index(
            "__row_index"
        )

        # Compare each Count with the Count immediately
        # before it.
        .with_columns(
            (
                pl.col(
                    count_col
                )
                -
                pl.col(
                    count_col
                ).shift(1)
            )
            .alias(
                "__count_delta"
            )
        )

        # EXACTLY +1 means one real closure.
        #
        # 0    -> no closure
        # >1   -> no closure
        # <0   -> reset/decrease, no closure
        .filter(
            pl.col(
                "__count_delta"
            )
            == 1
        )

        # Keep only the event information needed by
        # the next pipeline stage.
        .select(
            pl.col(
                "__row_index"
            ).alias(
                "row_index"
            ),

            pl.lit(
                head_id
            ).alias(
                "head_id"
            ),

            pl.col(
                torque_col
            ).alias(
                "torque"
            ),

            pl.col(
                status_col
            ).alias(
                "status"
            ),

            pl.col(
                "timestamp"
            ).alias(
                "timestamp"
            ),
        )
    )

    return closures


def detect_head_closures(
    df,
    head_id,
):
    """
    Compatibility wrapper around the lazy production
    implementation.

    Returns the same logical structure as the original
    pandas implementation:

    [
        {
            "row_index": ...,
            "head_id": ...,
            "torque": ...,
            "status": ...,
            "timestamp": ...
        }
    ]

    The expensive telemetry work remains inside Polars.
    Only actual closure rows are collected and converted
    into Python dictionaries.
    """

    closure_df = (
        detect_head_closures_frame(
            df,
            head_id,
        )
        .collect()
    )

    closures = []

    for row in closure_df.iter_rows(
        named=True
    ):

        closures.append({
            "row_index": int(
                row[
                    "row_index"
                ]
            ),

            "head_id":
                row[
                    "head_id"
                ],

            "torque":
                row[
                    "torque"
                ],

            "status":
                row[
                    "status"
                ],

            "timestamp":
                row[
                    "timestamp"
                ],
        })

    return closures