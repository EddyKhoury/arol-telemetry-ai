from pathlib import Path

import polars as pl


def convert_csv_to_parquet(csv_path, parquet_path):
    csv_path = Path(csv_path)
    parquet_path = Path(parquet_path)

    parquet_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        pl.scan_csv(csv_path)
        .with_columns(
            pl.col("timestamp").str.strptime(
                pl.Datetime,
                format="%Y-%m-%d %H:%M:%S",
                strict=True,
            )
        )
        .sink_parquet(parquet_path)
    )

def convert_csv_pool_to_parquet(csv_paths, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    parquet_paths = []

    for csv_path in csv_paths:
        csv_path = Path(csv_path)

        parquet_path = output_dir / f"{csv_path.stem}.parquet"

        convert_csv_to_parquet(
            csv_path,
            parquet_path,
        )

        parquet_paths.append(parquet_path)

    return parquet_paths