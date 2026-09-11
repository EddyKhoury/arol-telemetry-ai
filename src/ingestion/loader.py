# Path helps us work with file paths in a cleaner and more portable way
# than manually handling path strings.
from pathlib import Path

# Pandas is used to read CSV, JSON, and Parquet files
# and represent the telemetry data as DataFrames.
import pandas as pd

# PyYAML allows Python to read our config.yaml file.
import yaml

import polars as pl

# Custom error specifically for problems that happen during loading.
# This makes loader errors easier to understand than raw Python exceptions.
class LoaderError(Exception):
    """Raised when a dataset pool cannot be loaded correctly."""
    pass


def load_config(config_path):
    """
    Load config.yaml and return its contents as a Python dictionary.
    """

    # Convert the supplied path into a Path object.
    # Example:
    # "config.yaml" -> Path("config.yaml")
    config_path = Path(config_path)

    # Before trying to open the file, check that it actually exists.
    if not config_path.exists():
        raise LoaderError(
            f"Config file not found: {config_path}"
        )

    try:
        # Open the YAML file in read mode.
        with open(config_path, "r") as f:

            # Convert YAML into normal Python objects/dictionaries.
            #
            # Example:
            #
            # data:
            #   pools:
            #     sample:
            #       - data/sample.csv
            #
            # becomes roughly:
            #
            # {
            #   "data": {
            #       "pools": {
            #           "sample": ["data/sample.csv"]
            #       }
            #   }
            # }
            config = yaml.safe_load(f)

    # If the YAML itself has invalid syntax, give a clearer error.
    except yaml.YAMLError as exc:
        raise LoaderError(
            f"Could not parse config file: {config_path}"
        ) from exc

    # Give the loaded configuration back to the caller.
    return config


def get_pool_files(config, pool_name):
    """
    Get the ordered list of telemetry files belonging to a pool.

    Example:
    pool_name = "sample"

    returns:
    ["data/sample.csv"]
    """

    try:
        # Navigate through the nested config dictionary:
        #
        # config
        #   -> data
        #      -> pools
        pools = config["data"]["pools"]

    # If "data" or "pools" is missing, report a clear configuration problem.
    except (KeyError, TypeError) as exc:
        raise LoaderError(
            "Config must contain data -> pools."
        ) from exc

    # Check whether the requested pool actually exists.
    #
    # Example:
    # if we request "sample", there must be a "sample" entry in pools.
    if pool_name not in pools:
        raise LoaderError(
            f"Pool '{pool_name}' was not found in config."
        )

    # Get the list of files for this pool.
    files = pools[pool_name]

    # Every pool should contain a list with at least one file.
    #
    # Correct:
    # sample:
    #   - data/sample.csv
    #
    # Incorrect:
    # sample: []
    if not isinstance(files, list) or len(files) == 0:
        raise LoaderError(
            f"Pool '{pool_name}' must contain at least one file."
        )

    return files


def load_file(file_path):
    """
    Load ONE telemetry file.

    Supported formats:
    - CSV
    - JSON
    - Parquet

    The function returns the RAW wide DataFrame.

    It does NOT:
    - clean data
    - detect closures
    - convert statuses
    - detect heads
    - remove bad rows

    Those jobs belong to later pipeline steps.
    """

    # Convert the supplied file path into a Path object.
    file_path = Path(file_path)

    # Fail early with a clear message if the file does not exist.
    if not file_path.exists():
        raise LoaderError(
            f"Data file not found: {file_path}"
        )

    # Get the file extension and convert it to lowercase.
    #
    # Examples:
    # sample.csv     -> ".csv"
    # sample.JSON    -> ".json"
    # sample.parquet -> ".parquet"
    extension = file_path.suffix.lower()

    try:

        # Choose the correct pandas reader depending on the file type.
        if extension == ".csv":

            # Load a CSV file into a pandas DataFrame.
            df = pd.read_csv(file_path)

        elif extension == ".json":

            # Load a JSON file.
            df = pd.read_json(file_path)

        elif extension == ".parquet":

            # Load a Parquet file.
            # This uses the pyarrow package we installed.
            df = pd.read_parquet(file_path)

        else:
            # If the extension is something we do not support,
            # fail with a clear error instead of guessing.
            raise LoaderError(
                f"Unsupported file format '{extension}' "
                f"for file: {file_path}"
            )

    # If we intentionally raised LoaderError above,
    # allow that exact error to continue upward.
    except LoaderError:
        raise

    # Catch errors from pandas, corrupt files, invalid formats, etc.
    # and replace the long stack trace with a clearer loader message.
    except Exception as exc:
        raise LoaderError(
            f"Could not read data file: {file_path}"
        ) from exc

    # The telemetry files are expected to contain a timestamp column.
    if "timestamp" not in df.columns:
        raise LoaderError(
            f"File does not contain required "
            f"'timestamp' column: {file_path}"
        )

    try:
        # Convert timestamp values from strings such as:
        #
        # "2026-02-01T02:37:13.000"
        #
        # into real pandas datetime values.
        #
        # errors="raise" means:
        # if pandas finds an invalid timestamp, do not silently ignore it.
        df["timestamp"] = pd.to_datetime(
            df["timestamp"],
            errors="raise"
        )

    except Exception as exc:
        raise LoaderError(
            f"Could not parse timestamp column in: {file_path}"
        ) from exc

    # Return the loaded raw DataFrame.
    return df


def load_pool(pool_name, config_path="config.yaml"):
    """
    Load ALL files belonging to one dataset pool.

    Example:

    load_pool("sample")

    Process:

    config.yaml
        ↓
    find pool "sample"
        ↓
    get its file list
        ↓
    load every file
        ↓
    concatenate them
        ↓
    return one DataFrame

    IMPORTANT:
    Files are kept in the order listed in config.yaml.

    We deliberately do NOT sort or clean the rows here.
    Validation belongs to Step 5.
    """

    # Convert config path into a Path object.
    config_path = Path(config_path)

    # Read the YAML configuration.
    config = load_config(config_path)

    # Get the ordered file list for this pool.
    pool_files = get_pool_files(
        config,
        pool_name
    )

    # Find the directory containing config.yaml.
    #
    # If config_path is:
    # /project/config.yaml
    #
    # then config_directory is:
    # /project/
    config_directory = config_path.parent

    # We will temporarily store each loaded DataFrame here.
    dataframes = []

    # Go through the files in the SAME ORDER as config.yaml.
    for file_path in pool_files:

        # Convert each configured path into a Path object.
        file_path = Path(file_path)

        # Example config entry:
        #
        # data/sample.csv
        #
        # This is a relative path.
        #
        # We interpret it relative to the location of config.yaml.
        if not file_path.is_absolute():
            file_path = config_directory / file_path

        # Load this individual telemetry file.
        df = load_file(file_path)

        # Store it so that we can combine all pool files afterward.
        dataframes.append(df)

    # Stack all loaded files vertically.
    #
    # Example:
    #
    # day1 rows
    # day2 rows
    # day3 rows
    #
    # become one continuous DataFrame.
    #
    # ignore_index=True gives the final table a fresh index:
    # 0, 1, 2, 3, ...
    combined_df = pd.concat(
        dataframes,
        ignore_index=True
    )

    # Return the complete raw dataset pool.
    return combined_df


# This section only runs when we directly execute:
#
# python src/ingestion/loader.py
#
# It does NOT run when another Python file imports this loader.
if __name__ == "__main__":

    try:
        # Load our sample pool from config.yaml.
        df = load_pool("sample")

        # Small sanity checks so we can verify the loader worked.
        print("Pool loaded successfully.")

        # Number of rows loaded.
        print(f"Rows: {len(df)}")

        # Number of columns.
        # Our real 36-head dataset should have 109 columns.
        print(f"Columns: {len(df.columns)}")

        # Confirm timestamp was converted from string to datetime.
        print(f"Timestamp dtype: {df['timestamp'].dtype}")

    except LoaderError as exc:
        # Instead of showing a giant traceback for expected loader problems,
        # display our clear LoaderError message.
        print(f"Loader error: {exc}")

from pathlib import Path

import polars as pl


def scan_parquet_file(file_path):
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Parquet file not found: {file_path}")

    return pl.scan_parquet(file_path)

def scan_parquet_pool(file_paths):
    paths = [Path(file_path) for file_path in file_paths]

    if not paths:
        raise ValueError("Parquet pool cannot be empty.")

    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Parquet file not found: {path}")

    lazy_frames = [
        pl.scan_parquet(path)
        for path in paths
    ]

    return pl.concat(
        lazy_frames,
        how="vertical",
    )