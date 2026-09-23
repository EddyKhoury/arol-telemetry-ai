# AROL Telemetry AI — Project Audit & Implementation Notes

**Project:** Agentic AI for Telemetry Analysis on AROL Capping Machines  
**Role covered here:** Person A — data ingestion, validation, event-table preparation, and later deterministic analytics  
**Current implementation status:** Steps 4–9 reference implementation complete (70/70 tests); M2.5 Polars/Parquet performance refactor in progress; Steps 4–9 Polars/Parquet refactor complete; Step 9 final event table and event-Parquet persistence complete; benchmark gate is next  
**Primary source documents:** `docs/contract.md` and `docs/PERSON-A-WORKING-SPEC.md` (both amended after Step 9 for the Polars/Parquet production architecture)

---

# 1. Purpose of this audit

This document is a running technical audit of what has been built, why it was built that way, what each function does, what has been tested, what design decisions were made, and what is still pending.

The goal is to make it possible to come back later and answer:

- What did we build?
- Why does each function exist?
- What assumptions are we making?
- Which audit requirements are already satisfied?
- Which tests prove that each requirement works?
- What should we do next?
- What should **not** be changed accidentally?

This document should be updated after every major step.

---

# CURRENT AUTHORITATIVE STATUS — 2026-09-11

This section supersedes any older “current project status” snapshots later in this
audit. Those older sections are intentionally retained as historical checkpoints.

## Functional reference baseline

The original implementation through Step 9 is complete and remains the behavioral
reference:

```text
Step 4  Loader                 ✅
Step 5  Validation             ✅
Step 6  Closure detection      ✅
Step 7  Event assembly         ✅
Step 8  Capping speed          ✅
Step 9  Final event table      ✅
```

Original regression baseline:

```text
70 / 70 tests passing
```

Milestone M2 (“event table exists”) was completed before the performance refactor
began.

## Architecture amendment after Step 9

Before starting Step 10, the production data path was deliberately amended because
the real AROL dataset is much larger than the small development sample.

The target production architecture is:

```text
Raw AROL CSV
    ↓
one-time / incremental conversion
    ↓
Parquet
    ↓
Polars LazyFrame
    ↓
validation
    ↓
closure reconstruction
    ↓
status decoding / event assembly
    ↓
clean event data
    ↓
event Parquet
    ↓
Polars deterministic analytics
    ↓
JSON-safe tool result
    ↓
Person B agent/orchestration layer
```

The engineering rules for the refactor are:

- Parquet is the canonical persisted working format.
- Polars is the canonical production dataframe engine.
- Lazy execution is preferred for large scans and transformations.
- Pandas is temporarily retained only as the already-tested behavioral reference
  and for later benchmark comparison.
- PyArrow is retained as Parquet infrastructure/compatibility, not as a second
  analytics engine.
- DuckDB, Spark, Dask, and Modin are not added unless a measured requirement later
  justifies them.
- Repeated Polars → pandas → Polars conversions are forbidden.
- The existing 70 tests are the behavioral regression contract.
- No performance improvement will be claimed until it is measured on representative
  AROL data.

## Current M2.5 performance-refactor status

```text
Step 4  Polars/Parquet ingestion refactor   ✅ COMPLETE
Step 5  Polars validation refactor          ✅ COMPLETE
Step 6  Vectorized closure detection        ✅ COMPLETE
Step 7  Vectorized event assembly           ⏳
Step 8  Polars capping-speed path           ⏳
Step 9  Polars final event table            ⏳
Benchmark old vs new                        ⏭ NEXT
Step 10 analytics                           BLOCKED until M2.5 is complete
```

Current full regression result:

```text
102 / 102 tests passing
```

No benchmark result has been recorded yet, so the audit makes no numerical speed
or memory claim at this stage.

---

# 2. Project contract — key facts we are building against

The implementation is based on the agreed interface contract.

## Real telemetry structure

The real telemetry data has:

- one machine per file
- one row per second
- 36 heads in the real files
- 109 columns total:
  - 1 `timestamp`
  - 36 `Count` columns
  - 36 `AppTorque` columns
  - 36 `Status` columns

Per head, the raw columns follow this pattern:

```text
H01 Count
H01 AppTorque
H01 Status

H02 Count
H02 AppTorque
H02 Status

...
H36 Count
H36 AppTorque
H36 Status
```

Important observed behavior:

- counters only hold or increment by exactly `+1`
- no wraps/resets/decreases were observed in the inspected real file
- counters continue across day-files
- day-files in the same pool must be treated as one continuous stream
- torque and status for a closure are stored on the same row as the counter increment
- observed status codes are:
  - `0` = Closure OK
  - `2` = No Load
  - `65` = Bad Closure

The final event table is a later step and will contain one row per closure event.

---

# 3. Repository setup

The repository was created as:

```text
arol-telemetry-ai/
```

The Git repository was initialized locally, then published to GitHub as a private repository.

The initial repository structure follows the contract:

```text
arol-telemetry-ai/
├── config.yaml
├── README.md
├── requirements.txt
├── data/
│   └── sample.csv
├── docs/
│   ├── contract.md
│   └── PERSON-A-WORKING-SPEC.md
├── src/
│   ├── ingestion/
│   │   ├── loader.py
│   │   └── validation.py
│   ├── analytics/
│   ├── agent/
│   └── interface/
└── tests/
    ├── test_loader.py
    └── test_validation.py
```

## Git ignore strategy

The project uses `.gitignore` so that:

- `.venv/` is not committed
- Python cache files are ignored
- pytest cache files are ignored
- large telemetry files are not accidentally committed
- `data/sample.csv` is allowed as the small development/test dataset

Conceptually:

```text
data/*
!data/sample.csv
```

This means:

- ignore all files in `data/`
- except `sample.csv`

That protects the repository from accidentally storing the large real telemetry files.

---

# 4. Python environment

The project uses Homebrew Python on Apple Silicon (`arm64`):

```text
Python 3.12.14
```

The repository uses a project virtual environment:

```text
.venv/
```

activated with:

```bash
source .venv/bin/activate
```

At the current refactor checkpoint, `requirements.txt` is a frozen environment
and includes, among other transitive dependencies:

```text
pandas==3.0.5
pyarrow==25.0.1
polars==1.44.2
polars-runtime-32==1.44.2
pytest==9.1.1
PyYAML==6.0.3
numpy==2.5.2
```

Current dependency roles:

| Package | Current role |
|---|---|
| `polars` | New canonical production dataframe engine and lazy Parquet/CSV processing |
| `pandas` | Temporary reference implementation for regression and later benchmarking |
| `pyarrow` | Parquet infrastructure/compatibility |
| `PyYAML` | Reading `config.yaml` |
| `pytest` | Automated regression testing |
| `numpy` | Existing dependency used by the environment/reference stack |

`polars-runtime-32` is installed automatically as the runtime dependency for the
installed Polars build on this machine.

Pandas must **not** be removed until the Steps 4–9 refactor and the benchmark
comparison are complete.

---

# 5. Configuration

Current configuration structure after the architecture amendment:

```yaml
data:
  pools:
    sample:
      - data/sample.csv

  canonical_format: parquet
  parquet_root: data/parquet
  event_parquet_root: data/events

  n_heads: null

  units:
    AppTorque: Nm

processing:
  engine: polars
  lazy: true
```

The existing `pools.sample` entry is intentionally retained while the refactor is
in progress so the original CSV ingestion path and its tests continue to work.

The new keys document the production direction:

- `canonical_format: parquet` — canonical persisted telemetry format
- `parquet_root` — location for converted telemetry Parquet files
- `event_parquet_root` — location for persisted event-level Parquet data
- `processing.engine: polars` — canonical production dataframe engine
- `processing.lazy: true` — prefer lazy scans/transforms where appropriate

At this checkpoint the new conversion code writes one Parquet file per input CSV
into an output directory. Machine/date partitioning described in the amended
architecture has **not yet been implemented** and remains an explicit migration
item rather than something this audit silently claims is finished.

## Why configuration exists

The loader must not contain hard-coded dataset paths.

Instead of writing:

```python
pd.read_csv("/Users/.../sample.csv")
```

the rest of the system can ask for a named pool:

```python
load_pool("sample")
```

and the loader discovers the file path from `config.yaml`.

This keeps the code portable and allows a different dataset pool to be selected by editing configuration rather than changing Python code.

## `n_heads: null`

This is deliberate.

We do **not** hard-code:

```yaml
n_heads: 36
```

because the contract says head count should preferably be auto-detected later from the source columns.

The real dataset has 36 heads, but future or grading datasets may differ.

## Units metadata

The working spec requires validation of units metadata but does not define where that metadata is stored.

We therefore introduced this project convention:

```yaml
units:
  AppTorque: Nm
```

This is an implementation decision made during Step 5.

It should be documented clearly because it is not explicitly defined in the original source files.

---

# 6. Step 4 — Original reference loader

**Reference status:** COMPLETE  
**Original tests:** 12/12 passed  
**Milestone contribution:** M1 — data loads

This section documents the original pandas-based loader that established the behavioral baseline. It remains temporarily available while the production path is migrated to Polars/Parquet.

The Step 4 loader is responsible only for loading raw telemetry.

It must **not**:

- clean the data
- remove missing values
- sort bad input silently
- decode status codes
- detect closures
- detect heads
- convert Count values into events
- calculate analytics

The principle is:

```text
Step 4 = load
Step 5 = validate
Step 6+ = interpret
```

---

# 7. `LoaderError`

File:

```text
src/ingestion/loader.py
```

Concept:

```python
class LoaderError(Exception):
    ...
```

## Purpose

`LoaderError` gives loader-related problems one clear exception type.

Instead of allowing users to see low-level exceptions such as:

```text
FileNotFoundError
UnicodeDecodeError
ParserError
```

the loader can raise understandable messages such as:

```text
Data file not found: ...
```

or:

```text
Could not read data file: ...
```

## Why this matters

Step 4 requires missing or corrupt files to fail with a clear error.

A custom error keeps this consistent.

---

# 8. `load_config(config_path)`

## Purpose

Read the YAML configuration file and return its contents as a normal Python dictionary.

Conceptual flow:

```text
config.yaml
    ↓
open file
    ↓
yaml.safe_load(...)
    ↓
Python dictionary
```

Example YAML:

```yaml
data:
  pools:
    sample:
      - data/sample.csv
```

becomes approximately:

```python
{
    "data": {
        "pools": {
            "sample": ["data/sample.csv"]
        }
    }
}
```

## Important implementation details

### `Path(config_path)`

The incoming path is converted to a `Path` object.

This makes path handling clearer and more portable.

### Config existence check

Before reading:

```python
if not config_path.exists():
```

The loader reports a clear error if the configuration file is missing.

### `yaml.safe_load`

The configuration is parsed using:

```python
yaml.safe_load(f)
```

`safe_load` is appropriate because our config should contain only ordinary data structures:

- dictionaries
- lists
- strings
- numbers
- booleans
- null values

## Output

Returns the full config dictionary.

---

# 9. `get_pool_files(config, pool_name)`

## Purpose

Look inside the configuration and return the ordered list of files belonging to a named pool.

Example call:

```python
get_pool_files(config, "sample")
```

returns:

```python
["data/sample.csv"]
```

Later a real pool might be:

```yaml
feb:
  - data/feb_01.csv
  - data/feb_02.csv
  - data/feb_03.csv
```

and the function would return the files in exactly that configured order.

## Validation performed here

The function verifies:

- `data -> pools` exists
- the requested pool exists
- the pool is a list
- the pool is not empty

## Why pool order matters

The contract says day-files are one continuous stream and counters continue across file boundaries.

Therefore:

```text
day 1
then day 2
then day 3
```

must remain in that order.

---

# 10. `load_file(file_path)`

## Purpose

Load **one** telemetry file into a pandas DataFrame.

Supported formats:

- CSV
- JSON
- Parquet

## File format selection

The function checks the extension:

```text
.csv
.json
.parquet
```

and chooses:

```python
pd.read_csv(...)
pd.read_json(...)
pd.read_parquet(...)
```

## Why this design matters

The caller does not need to know what format the file uses.

The caller can still use:

```python
load_pool("some_pool")
```

regardless of whether that pool points to CSV, JSON, or Parquet.

This directly satisfies the Step 4 requirement that adding JSON/Parquet support should not require changing the calling code.

## Timestamp handling

After loading, the function checks that:

```text
timestamp
```

exists.

Then:

```python
pd.to_datetime(...)
```

converts it from text into a real pandas datetime type.

Our sample originally loaded `timestamp` as text.

After parsing, the result was:

```text
datetime64[us]
```

This is required by Step 4.

## Important limitation

We **do not assign UTC here**.

The sample timestamps look like:

```text
2026-02-01T02:37:13.000
```

but they do not contain:

```text
Z
```

or a timezone offset.

Therefore, the source file itself does not prove what timezone they use.

The final event schema expects UTC, but timezone localization must not be invented without confirming the source timezone.

## What `load_file` deliberately does not do

It does not:

```python
df.dropna()
```

It does not:

```python
df.sort_values(...)
```

It does not convert status codes.

It does not detect counter increments.

It does not fix Count/Status dtypes.

Those belong to later steps.

---

# 11. `load_pool(pool_name, config_path="config.yaml")`

## Purpose

Load every file belonging to one configured dataset pool and return one combined raw DataFrame.

Example:

```python
df = load_pool("sample")
```

## Internal flow

```text
load_pool("sample")
    ↓
load_config(...)
    ↓
get_pool_files(...)
    ↓
load_file(file 1)
load_file(file 2)
...
    ↓
pd.concat(...)
    ↓
one combined DataFrame
```

## Relative path handling

Configured paths such as:

```text
data/sample.csv
```

are resolved relative to the directory containing `config.yaml`.

This makes the project more portable.

## Multi-file stitching

Each loaded file is stored in a list:

```python
dataframes = []
```

Then combined using:

```python
pd.concat(..., ignore_index=True)
```

This produces one continuous DataFrame.

## Why the loader does NOT sort

No:

```python
sort_values("timestamp")
```

is performed.

Reason:

Step 5 is responsible for detecting whether timestamps are out of order.

If Step 4 silently sorted bad data, Step 5 could never report that the original source was wrong.

This preserves the separation:

```text
load exactly what was supplied
↓
validate whether it is correct
```

---

# 12. Loader manual sample result

Running:

```bash
python src/ingestion/loader.py
```

produced:

```text
Pool loaded successfully.
Rows: 17
Columns: 109
Timestamp dtype: datetime64[us]
```

This confirms the sample matches the expected real-data layout:

```text
1 timestamp
+
36 heads × 3 fields
=
109 columns
```

---

# 13. Step 4 automated tests

File:

```text
tests/test_loader.py
```

Result:

```text
12 passed
```

The 12 tests cover:

1. Config loads
2. Sample pool path is correct
3. CSV loads
4. Column names are preserved
5. Timestamp becomes datetime
6. Pool loads
7. Missing file gives a clear error
8. Missing pool gives a clear error
9. Corrupt file gives a clear error
10. JSON pool works
11. Parquet pool works
12. Multiple files are stitched in configured order

---

# 14. Step 4 audit result

| Requirement | Status |
|---|---|
| Path read from config | PASS |
| CSV loads | PASS |
| Source columns preserved | PASS |
| Timestamp parsed to datetime | PASS |
| JSON supported | PASS |
| Parquet supported | PASS |
| Same calling code across formats | PASS |
| Missing file handled clearly | PASS |
| Corrupt file handled clearly | PASS |
| Multiple files stitched | PASS |
| Configured file order preserved | PASS |
| Raw wide table returned | PASS |

**Step 4: COMPLETE**

---

# 15. Step 5 — Original reference validation

**Status:** implementation complete  
**Tests:** 16/16 passed  
**Git status:** test success confirmed; commit/push should be confirmed after the latest Step 5 changes

Step 5 receives the already-loaded DataFrame from Step 4.

Conceptually:

```text
load_pool(...)
    ↓
raw DataFrame
    ↓
validate_data(...)
    ↓
validation report
```

The validator does not load files itself.

---

# 16. Step 5 design rule

The validator must:

```text
detect
count
report
```

It must **not**:

```text
delete
repair
sort
fill
silently convert
```

Validation should tell us what is wrong while leaving the input untouched.

---

# 17. `check_missing_values(df)`

## Purpose

Count missing values per column.

Uses:

```python
df.isna().sum()
```

## Output

Clean data:

```python
{}
```

Example bad data:

```python
{
    "H01 AppTorque": 2,
    "H05 Status": 1
}
```

## Important behavior

It does not remove or replace missing data. It only reports it.

## Tests

- clean sample returns `{}`
- injected missing value is detected exactly

---

# 18. `check_duplicate_timestamps(df)`

## Purpose

Detect repeated timestamps.

Uses:

```python
df["timestamp"].duplicated(keep="first")
```

## Output

Clean:

```python
{
    "count": 0,
    "timestamps": []
}
```

Problem example:

```python
{
    "count": 1,
    "timestamps": [
        "2026-02-01 02:37:14"
    ]
}
```

`count` represents extra duplicate rows.

---

# 19. `check_out_of_order_timestamps(df)`

## Purpose

Detect whether time ever moves backwards from one row to the next.

Uses:

```python
df["timestamp"].diff()
```

Example differences:

```text
NaT
+1 second
+2 seconds
-1 second
```

A negative difference means out of order.

## Output

```python
{
    "count": 1,
    "rows": [
        {
            "row_index": 3,
            "previous_timestamp": "...",
            "current_timestamp": "..."
        }
    ]
}
```

---

# 20. `check_timestamp_gaps(df)`

## Purpose

Detect intervals larger than the expected one-second sampling interval.

Uses:

```python
df["timestamp"].diff()
```

and checks for differences greater than one second.

## Output example

```python
{
    "count": 1,
    "rows": [
        {
            "row_index": 2,
            "previous_timestamp": "...",
            "current_timestamp": "...",
            "gap_seconds": 5.0
        }
    ]
}
```

`gap_seconds` is the observed time difference between two recorded rows.

---

# 21. `check_dtypes(df)`

## Purpose

Validate the semantic types of:

- timestamp
- Count
- AppTorque
- Status

## Timestamp

Must be pandas datetime.

## Count

Count values must be numeric and integer-like.

Because CSV may load:

```text
104085.0
```

as float, the validator checks whether the fractional part is zero rather than requiring the pandas dtype to literally be `int`.

Examples:

```text
104085.0 → valid
104085.5 → invalid
```

## Status

Uses the same integer-like rule:

```text
0.0  → valid
2.0  → valid
65.0 → valid
2.5  → invalid
```

## AppTorque

Must be numeric.

## Output

Clean:

```python
{
    "issues": []
}
```

Bad example:

```python
{
    "issues": [
        {
            "column": "H01 Count",
            "problem": "contains non-integer Count values"
        }
    ]
}
```

---

# 22. `check_units_metadata(config)`

## Purpose

Validate the project unit convention.

Expected:

```yaml
units:
  AppTorque: Nm
```

## Output

Valid:

```python
{
    "valid": True,
    "issues": []
}
```

Missing/bad metadata returns `valid=False` with issue descriptions.

## Provenance note

The working spec requires a units metadata check but does not define where units metadata must live.

The contract states torque is in Nm.

Storing `AppTorque: Nm` in config is therefore a project convention introduced during Step 5.

---

# 23. `validate_data(df, config)`

## Purpose

Run all Step 5 validation functions and combine them into one report.

Calls:

```text
check_missing_values
check_duplicate_timestamps
check_out_of_order_timestamps
check_timestamp_gaps
check_dtypes
check_units_metadata
```

## Output structure

```python
{
    "valid": True or False,

    "missing_values": {...},

    "timestamps": {
        "duplicates": {...},
        "out_of_order": {...},
        "gaps": {...}
    },

    "dtypes": {
        "issues": [...]
    },

    "units": {
        "valid": ...,
        "issues": [...]
    }
}
```

`valid` is `True` only when all validation checks are clean.

---

# 24. Step 5 automated tests

File:

```text
tests/test_validation.py
```

Latest result:

```text
16 passed in 0.25s
```

Coverage:

- 2 missing-value tests
- 2 duplicate timestamp tests
- 2 out-of-order timestamp tests
- 2 timestamp-gap tests
- 4 dtype tests
- 2 units tests
- 2 combined-report tests

---

# 25. Step 5 audit result

| Requirement | Status |
|---|---|
| Missing values reported | PASS |
| Duplicate timestamps reported | PASS |
| Out-of-order timestamps reported | PASS |
| Timestamp gaps reported | PASS |
| Timestamp dtype checked | PASS |
| Count values checked | PASS |
| Torque values checked | PASS |
| Status values checked | PASS |
| Units metadata checked | PASS |
| Bad data not silently dropped | PASS |
| Validator does not repair data | PASS |
| Multiple issues can be reported together | PASS |
| Clean data returns valid report | PASS |
| Injected errors detected by tests | PASS |

**Step 5 reference implementation and audit tests: COMPLETE**

The validation semantics are locked by these tests. The production implementation has not yet been refactored to Polars at the current checkpoint.

This reaches:

```text
M1 — Data loads & validates
```

---

# 26. Historical project status after Step 5

```text
M0 — Contract locked
    Contract/spec documents present
    Original open contract items should still be treated as governance items
    if Person B has not explicitly signed them off

M1 — Data loads & validates
    Step 4 ✅
    Step 5 ✅

M2 — Event table exists
    Step 6 ❌
    Step 7 ❌
    Step 8 ❌
    Step 9 ❌

M3 — Analytics
    Steps 10–14 ❌

M4 — Agent tools
    Steps 15–17 ❌

M5 — Evaluation/docs
    Steps 18–20 ❌

M6 — Integration
    Steps 21–22 ❌
```

---

# 27. Step 6 — Closure detection

**Status:** COMPLETE  
**Step 6 tests:** 7/7 passed  
**Full project suite after Step 6:** 35/35 passed  
**Current milestone:** M1 complete; M2 in progress  
**Next step:** Step 7 — Event assembly

Step 6 implements the core rule used to infer a closure from the raw telemetry counter stream.

The agreed rule is:

```text
for one head:
    compare the current Count with the previous Count

    if current Count == previous Count + 1:
        exactly one closure occurred
```

The real-data contract established that counters normally hold or increment by exactly +1, and that the torque/status belonging to a closure are stored on the same row as the increment.

Step 6 detects raw closures only. It deliberately does **not** decode status codes into `error_class`, `reject_signal`, or `cap_present`; that belongs to Step 7.

---

# 28. `detect_head_closures(df, head_id)`

File:

```text
src/ingestion/closure_detection.py
```

Purpose:

```python
detect_head_closures(df, "H01")
```

detects closure events for one head.

The function dynamically constructs:

```python
count_col = f"{head_id} Count"
torque_col = f"{head_id} AppTorque"
status_col = f"{head_id} Status"
```

For `H01`, these become:

```text
H01 Count
H01 AppTorque
H01 Status
```

This keeps the function generic across heads instead of hard-coding H01-H36.

The function creates:

```python
closures = []
```

and loops from row position 1:

```python
for i in range(1, len(df)):
```

It deliberately skips the first row because row 0 has no previous Count to compare against.

For each row:

```python
previous_row = df.iloc[i - 1]
current_row = df.iloc[i]

previous_count = previous_row[count_col]
current_count = current_row[count_col]
```

A closure is detected only when:

```python
current_count == previous_count + 1
```

When that condition is true, the raw closure record stores:

```python
{
    "row_index": i,
    "head_id": head_id,
    "torque": current_row[torque_col],
    "status": current_row[status_col],
    "timestamp": current_row["timestamp"],
}
```

The important design decision is that torque, status, and timestamp come from the **current/increment row**.

At the end:

```python
return closures
```

---

# 29. Step 6 edge-case rules

## Counter hold

```text
100 -> 100
```

Result:

```text
no closure
```

A closure is driven by Count, not by changes in Status or AppTorque.

## Normal +1 increment

```text
100 -> 101
```

Result:

```text
exactly one closure
```

The event uses torque/status/timestamp from the `101` row.

## First row

The first row never creates a closure by itself because there is no previous Count available for comparison.

## Status changes while Count holds

Example:

```text
Count:   100 -> 100 -> 100
Status:    0 -> 65  -> 2
```

Result:

```text
0 closures
```

Status alone is not the event trigger.

## Counter jump greater than 1

Example:

```text
100 -> 103
```

Current deliberate policy:

```text
emit no closures for that transition
```

Reason: one sampled row cannot reconstruct the individual timestamps, torque values, or statuses of the missing intermediate increments. We do not invent synthetic closure records.

The inspected real data did not show jumps greater than 1.

## Counter decrease/reset/wrap

Example:

```text
1000 -> 1001 -> 5
```

Behavior:

```text
1000 -> 1001 = one valid closure
1001 -> 5    = no closure
```

A decrease is treated as a reset/wrap/restart-style transition, not a closure.

The inspected real data did not show resets/decreases, but the detector handles them safely.

## Closure across stitched-file boundary

If the final row of one day-file is:

```text
Count = 100
```

and the first row of the next configured day-file is:

```text
Count = 101
```

Step 4 first stitches the files into one DataFrame. Step 6 therefore sees `100 -> 101` and detects one closure.

This preserves the contract rule that a pool is one continuous counter history.

---

# 30. Step 6 tests

File:

```text
tests/test_closure_detection.py
```

Seven tests now pass:

1. `test_steady_count_produces_zero_closures`
   - proves repeated Count values create no events

2. `test_increment_by_one_produces_one_closure`
   - proves +1 creates exactly one event
   - verifies row index, head ID, torque, status, and timestamp

3. `test_first_row_does_not_create_a_closure`
   - proves row 0 is handled safely

4. `test_status_change_without_count_increment_produces_no_closure`
   - proves status changes alone do not define a closure

5. `test_count_jump_greater_than_one_produces_no_closure`
   - proves the documented >1 policy

6. `test_counter_reset_produces_no_spurious_closure`
   - proves a valid increment is retained while the following decrease is ignored

7. `test_closure_across_stitched_file_boundary_is_detected`
   - proves continuity across configured day-files

Step 6 test result:

```text
7 passed in 0.22s
```

---

# 31. Full regression result after Step 6

The complete suite was run:

```bash
.venv/bin/python -m pytest -v
```

Result:

```text
35 passed in 0.46s
```

Breakdown:

```text
Closure detection:  7 / 7
Loader:            12 / 12
Validation:        16 / 16
--------------------------------
Total:             35 / 35 PASS
```

This confirms Step 6 did not regress the loader or validation layers.

---

# 32. Step 6 audit result

| Requirement | Status |
|---|---|
| Tests written before implementation | PASS |
| Steady Count -> zero closures | PASS |
| +1 increment -> one closure | PASS |
| Correct torque/status attached | PASS |
| Correct timestamp attached | PASS |
| First row handled safely | PASS |
| Status flip during hold ignored | PASS |
| Count jump >1 handled deliberately | PASS |
| Reset/decrease creates no spurious closure | PASS |
| Stitched-file boundary increment detected | PASS |

**Step 6: COMPLETE**

---

# 33. Step 7 — Event assembly

**Status:** COMPLETE  
**Step 7 tests:** 18/18 passed  
**Full project suite after Step 7:** 53/53 passed  
**Current milestone:** M2 in progress  
**Next step:** Step 8 — per-closure timestamp and incremental capping speed

Step 7 converts each raw closure detected in Step 6 into one event record and decodes the raw status code into semantic fields.

The working specification requires:

- one detected closure → exactly one event row
- every known status code maps to the correct `error_class`
- odd reject codes set `reject_signal = True`
- even paired codes set `reject_signal = False`
- unknown status codes are explicitly flagged instead of silently mislabeled

---

# 34. `STATUS_MAP`

File:

```text
src/ingestion/event_assembly.py
```

The decoder uses a lookup table rather than a long chain of `if` statements:

```python
STATUS_MAP = {
    0: ("Closure OK", False),
    2: ("No Load", False),
    3: ("No Load", True),
    4: ("No Closure", False),
    5: ("No Closure", True),
    8: ("No InTorque", False),
    9: ("No InTorque", True),
    16: ("No CapTurns", False),
    17: ("No CapTurns", True),
    32: ("Following Error", False),
    33: ("Following Error", True),
    64: ("Bad Closure", False),
    65: ("Bad Closure", True),
}
```

Each dictionary value stores:

```text
(error_class, reject_signal)
```

Example:

```python
STATUS_MAP[33]
```

returns:

```python
("Following Error", True)
```

This makes the complete brief status table explicit and easy to extend.

---

# 35. `CAP_PRESENT_MAP`

The contract explicitly defines `cap_present` for the status codes actually observed in the real pools:

```python
CAP_PRESENT_MAP = {
    0: True,
    2: False,
    65: True,
}
```

Meaning:

```text
0  -> cap applied / present
2  -> No Load, no cap present
65 -> cap present but closure rejected
```

For brief status codes whose cap-presence meaning is not explicitly defined by the current contract, the implementation currently returns `None` rather than inventing a Boolean value.

**Open schema assumption:** before Step 9 freezes the clean event table, the team should decide whether statuses `3, 4, 5, 8, 9, 16, 17, 32, 33, 64` need explicit `cap_present` semantics. Until that is defined, `None` is used to mean "not specified by the current source contract."

---

# 36. `decode_status(status)`

Purpose:

Decode one raw status code.

For a known code, the function retrieves:

```python
error_class, reject_signal = STATUS_MAP[status]
```

and returns:

```python
{
    "error_class": error_class,
    "reject_signal": reject_signal,
    "cap_present": CAP_PRESENT_MAP.get(status),
}
```

For an unknown code such as:

```text
99
```

the function returns:

```python
{
    "error_class": "Unknown (99)",
    "reject_signal": None,
    "cap_present": None,
}
```

This deliberately avoids crashing and avoids silently assigning an incorrect known class.

---

# 37. `assemble_event(closure, machine_id)`

Purpose:

Convert one raw Step 6 closure record into one event-table record.

Step 6 closure example:

```python
{
    "row_index": 2,
    "head_id": "H01",
    "torque": 2.05,
    "status": 65,
    "timestamp": pd.Timestamp("2026-02-01 10:00:02"),
}
```

Step 7 first decodes:

```python
decoded = decode_status(closure["status"])
```

and returns exactly these event fields:

```python
{
    "ts": closure["timestamp"],
    "machine_id": machine_id,
    "head_id": closure["head_id"],
    "torque": closure["torque"],
    "status": closure["status"],
    "error_class": decoded["error_class"],
    "reject_signal": decoded["reject_signal"],
    "cap_present": decoded["cap_present"],
}
```

`row_index` is intentionally not emitted into the contract event schema. It remains an internal Step 6/debugging field.

---

# 38. Step 7 status rules

| status | error_class | reject_signal |
|---:|---|---|
| 0 | Closure OK | False |
| 2 | No Load | False |
| 3 | No Load | True |
| 4 | No Closure | False |
| 5 | No Closure | True |
| 8 | No InTorque | False |
| 9 | No InTorque | True |
| 16 | No CapTurns | False |
| 17 | No CapTurns | True |
| 32 | Following Error | False |
| 33 | Following Error | True |
| 64 | Bad Closure | False |
| 65 | Bad Closure | True |

Explicit odd reject codes proven by tests:

```text
3, 5, 9, 17, 33, 65
```

All evaluate to:

```python
True
```

---

# 39. Step 7 tests

File:

```text
tests/test_event_assembly.py
```

The file currently contains 18 pytest cases when parameterized cases are expanded.

Coverage includes:

## Direct real-data decoding tests

```text
status 0  -> Closure OK / reject False / cap_present True
status 2  -> No Load / reject False / cap_present False
status 65 -> Bad Closure / reject True / cap_present True
```

## Unknown-status test

```text
99 -> Unknown (99)
```

with:

```text
reject_signal = None
cap_present = None
```

## Full parameterized status-table test

All 13 known brief status codes are checked against the correct:

```text
error_class
reject_signal
```

## Event-schema assembly test

One synthetic Step 6 closure is converted into one Step 7 event.

The test verifies the exact output keys:

```text
ts
machine_id
head_id
torque
status
error_class
reject_signal
cap_present
```

It also verifies representative values and types:

```text
ts            -> pandas Timestamp
machine_id    -> str
head_id       -> str
torque        -> float
status        -> int
error_class   -> str
reject_signal -> bool
cap_present   -> bool
```

for the tested status-65 event.

Step 7 focused test result:

```text
18 passed
```

---

# 40. Step 7 audit result

| Requirement | Status |
|---|---|
| Output uses the contract event fields | PASS |
| Known status codes decode correctly | PASS |
| Odd reject codes are `True` | PASS |
| Even paired codes are `False` | PASS |
| One closure produces one event | PASS |
| Unknown status explicitly flagged | PASS |
| Representative event values tested | PASS |
| Representative event types tested | PASS |

**Step 7: COMPLETE**

Important documented caveat:

```text
cap_present is contract-defined for 0, 2, and 65.
Other brief codes currently use None until semantics are agreed.
```

This must be revisited before Step 9 freezes the clean event table.

---

# 41. Full regression result after Step 7

The complete repository suite was run:

```bash
.venv/bin/python -m pytest -v
```

Result:

```text
53 passed in 0.48s
```

Breakdown:

```text
Closure detection:  7 / 7
Event assembly:     18 / 18
Loader:             12 / 12
Validation:         16 / 16
--------------------------------
Total:              53 / 53 PASS
```

This proves the Step 7 changes did not regress Steps 4–6.

---

# 42. Historical project status after Step 7

```text
M0 — Contract
    Steps 1–3 documented; shared governance/sign-off should remain explicit

M1 — Data loads & validates
    Step 4 ✅
    Step 5 ✅

M2 — Event table exists
    Step 6 ✅
    Step 7 ✅
    Step 8 ❌
    Step 9 ❌

M3 — Analytics complete
    Steps 10–14 ❌

M4 — Agent can use tools
    Steps 15–17 ❌

M5 — Proven & documented
    Steps 18–20 ❌

M6 — Integrated
    Steps 21–22 ❌
```

Current position:

```text
Step 7 of 22 complete
Next: Step 8 — per-closure timestamp and incremental capping speed
```

---

# 43. Current pipeline

```text
config.yaml
      │
      ▼
load_config()
      │
      ▼
get_pool_files()
      │
      ▼
load_file()
      │
      ▼
load_pool()
      │
      ▼
RAW WIDE DATAFRAME
      │
      ▼
validate_data()
      │
      ▼
VALIDATION REPORT
      │
      ▼
detect_head_closures(df, head_id)
      │
      ▼
RAW CLOSURE RECORD
      │
      ▼
decode_status(status)
      │
      ▼
assemble_event(closure, machine_id)
      │
      ▼
ONE CONTRACT EVENT RECORD
```

Not yet implemented:

- incremental capping-speed calculation
- final all-head clean event-table emission
- Step 9 final schema stabilization
- torque/statistical analytics
- agent tool interface

---

# 44. Step 8 — Timestamp preservation and incremental capping speed

**Status:** COMPLETE  
**Focused Step 8 tests:** 7/7 passed  
**Event timestamp integration test:** PASS  
**Full project suite:** 61/61 passed  
**Current milestone:** M2 in progress  
**Next step:** Step 9 — final clean all-head event table

Step 8 covers two requirements:

1. preserve the timestamp of the row where the closure counter increments;
2. compute capping speed in pieces/hour with an incremental running average.

---

# 45. `incremental_average(current_mean, new_value, n)`

File:

```text
src/analytics/capping_speed.py
```

Implementation:

```python
def incremental_average(current_mean, new_value, n):
    return current_mean + (new_value - current_mean) / n
```

Hand-calculated verification:

```text
values:        7200, 10800, 3600
running means: 7200, 9000, 7200
```

This confirms the incremental formula matches the ordinary arithmetic mean without recomputing the full history.

---

# 46. `closures_to_pieces_per_hour(closures, interval_seconds)`

Implementation:

```python
def closures_to_pieces_per_hour(closures, interval_seconds):

    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")

    return closures * 3600 / interval_seconds
```

Example:

```text
2 closures in 1 second = 7200 pieces/hour
```

Zero or negative intervals are rejected explicitly.

---

# 47. `running_capping_speed(closures_per_interval, interval_seconds)`

Implementation:

```python
def running_capping_speed(closures_per_interval, interval_seconds):

    running_mean = 0.0
    running_speeds = []

    for n, closures in enumerate(closures_per_interval, start=1):

        speed = closures_to_pieces_per_hour(
            closures=closures,
            interval_seconds=interval_seconds,
        )

        running_mean = incremental_average(
            running_mean,
            speed,
            n,
        )

        running_speeds.append(running_mean)

    return running_speeds
```

Example input:

```python
[2, 3, 1]
```

for one-second intervals produces instantaneous rates:

```text
7200, 10800, 3600 pieces/hour
```

and running means:

```text
7200, 9000, 7200 pieces/hour
```

Empty input returns `[]`.

---

# 48. Throughput interpretation

The current implementation uses:

```text
closures observed in an interval × 3600 / interval_seconds
```

This avoids event-to-event divisions by zero when several heads close at the same sampled timestamp.

This is a documented implementation decision because the project specification requires incremental capping speed but does not fully prescribe the estimator.

---

# 49. Timestamp preservation

A dedicated integration test proves the timestamp survives the full path:

```text
raw increment row
  ↓
detect_head_closures()
  ↓
closure["timestamp"]
  ↓
assemble_event()
  ↓
event["ts"]
```

Synthetic example:

```text
10:00:00 -> Count 100
10:00:01 -> Count 100
10:00:02 -> Count 101   <- closure
10:00:03 -> Count 101
```

Expected:

```text
event["ts"] = 2026-02-01 10:00:02
```

---

# 50. Step 8 tests

`tests/test_capping_speed.py`:

1. `test_incremental_average_matches_hand_calculation`
2. `test_closures_are_converted_to_pieces_per_hour`
3. `test_zero_interval_is_rejected`
4. `test_running_capping_speed_updates_incrementally`
5. `test_running_capping_speed_function`
6. `test_running_capping_speed_with_empty_input`
7. `test_running_capping_speed_rejects_zero_interval`

Additional integration coverage:

```text
tests/test_event_assembly.py::test_event_keeps_timestamp_of_count_increment_row
```

---

# 51. Step 8 audit result

| Requirement | Status |
|---|---|
| Closure keeps increment-row timestamp | PASS |
| Timestamp tested end-to-end | PASS |
| Throughput in pieces/hour | PASS |
| Incremental average implemented | PASS |
| Hand-calculated example matched | PASS |
| Zero interval handled | PASS |
| Empty input handled | PASS |
| Running-speed wrapper tested | PASS |

**Step 8: COMPLETE**

---

# 52. Full regression result after Step 8

```text
Closure detection:   7
Event assembly:      19
Loader:              12
Validation:          16
Capping speed:        7
--------------------------------
Total:               61 / 61 PASS
```

---

# 53. Historical project status after Step 8

```text
M1 — Data loads & validates
    Step 4 ✅
    Step 5 ✅

M2 — Event table exists
    Step 6 ✅
    Step 7 ✅
    Step 8 ✅
    Step 9 ❌
```

Current position:

```text
Step 8 of 22 complete
Next: Step 9 — final clean all-head event table
```

---

# 54. Step 9 — Final clean all-head event table

**Status:** COMPLETE  
**Step 9 tests:** 9/9 passed  
**Full project suite after Step 9:** 70/70 passed  
**Milestone M2:** COMPLETE  
**Next step:** Step 10 — analytics layer

Step 9 combines all detected closures across all available heads into one deterministic, tidy event DataFrame for downstream analytics and agent tools.

---

# 55. `EVENT_COLUMNS`

File:

```text
src/ingestion/event_table.py
```

Final schema:

```python
EVENT_COLUMNS = [
    "ts",
    "machine_id",
    "head_id",
    "torque",
    "status",
    "error_class",
    "reject_signal",
    "cap_present",
]
```

This keeps column order stable for both empty and non-empty outputs.

---

# 56. `detect_head_ids(df)`

Heads are auto-detected from raw columns ending in:

```text
" Count"
```

Example:

```text
H01 Count
H02 Count
H03 Count
```

becomes:

```python
["H01", "H02", "H03"]
```

This avoids assuming exactly 36 heads.

---

# 57. `build_event_table(df, machine_id)`

Core logic:

```text
detect all head IDs
      ↓
for each head:
    detect closures
      ↓
for each closure:
    assemble one event
      ↓
append all events
      ↓
build DataFrame with EVENT_COLUMNS
      ↓
sort by ts, then head_id
      ↓
reset index
```

Exactly one event row is emitted per detected closure.

If there are no closures, the function still returns an empty DataFrame with the full event schema.

---

# 58. Deterministic ordering

The event table is sorted by:

```python
["ts", "head_id"]
```

This guarantees chronological ordering and a deterministic tie-break for closures occurring at the same timestamp.

Example:

```text
10:00:01 H01
10:00:01 H02
10:00:02 H01
```

Repeated runs on the same input produce the same DataFrame.

---

# 59. Same-timestamp closures

Two different heads closing at the same timestamp remain two distinct event rows.

Example:

```text
10:00:01 H01 closes
10:00:01 H02 closes
```

Result:

```text
2 event rows
```

The implementation does not deduplicate by timestamp alone.

---

# 60. Final event-table data types

The tests verify pandas dtypes appropriately:

```text
ts            -> datetime dtype
torque        -> float dtype
status        -> integer dtype
reject_signal -> bool dtype
cap_present   -> bool dtype
```

Text-valued columns are verified to contain strings:

```text
machine_id
head_id
error_class
```

The tests intentionally use pandas dtype checks because scalar values such as status may be represented as NumPy integer types such as `np.int64`.

---

# 61. Step 9 tests

File:

```text
tests/test_event_table.py
```

Nine tests pass:

1. `test_head_ids_are_auto_detected`
2. `test_head_detection_does_not_assume_36_heads`
3. `test_no_closures_returns_empty_event_table_with_schema`
4. `test_one_closure_produces_one_event_row`
5. `test_multiple_heads_produce_multiple_event_rows`
6. `test_event_table_is_sorted_chronologically`
7. `test_same_timestamp_different_heads_are_both_kept`
8. `test_event_table_is_deterministic`
9. `test_event_table_has_expected_types`

---

# 62. Step 9 audit result

| Requirement | Status |
|---|---|
| Auto-detect heads | PASS |
| No fixed 36-head assumption | PASS |
| One row per closure | PASS |
| Multi-head events combined | PASS |
| Empty result preserves schema | PASS |
| Chronological ordering | PASS |
| Same-time events preserved | PASS |
| Deterministic output | PASS |
| Expected DataFrame dtypes | PASS |

**Step 9: COMPLETE**

---

# 63. Full regression result after Step 9

```text
Closure detection:   7
Event assembly:      19
Loader:              12
Validation:          16
Capping speed:        7
Event table:          9
--------------------------------
Total:               70 / 70 PASS
```

---

# 64. Milestone M2 status

```text
M2 — Event table exists
    Step 6 ✅ Closure detection
    Step 7 ✅ Event assembly
    Step 8 ✅ Timestamp + incremental capping speed
    Step 9 ✅ Final clean all-head event table
```

**Milestone M2: COMPLETE**

The pipeline now transforms raw wide telemetry into a stable event-level dataset suitable for analytics.

---

# 65. Reference pipeline completed at Step 9

The original behaviorally validated pipeline is:

```text
config.yaml
      ↓
load_pool()                         [pandas reference]
      ↓
RAW WIDE DATAFRAME
      ↓
validate_data()
      ↓
detect_head_ids()
      ↓
detect_head_closures() per head
      ↓
decode_status()
      ↓
assemble_event()
      ↓
build_event_table()
      ↓
FINAL CLEAN EVENT DATAFRAME
```

This pipeline is retained as the correctness reference during M2.5.

---

# 66. Production pipeline being migrated

The amended production direction is:

```text
raw CSV
   ↓
convert_csv_to_parquet()
   ↓
Parquet files
   ↓
scan_parquet_file() / scan_parquet_pool()
   ↓
Polars LazyFrame
   ↓
Step 5 validation refactor
   ↓
Step 6 vectorized closure reconstruction
   ↓
Step 7 event assembly
   ↓
Step 8 capping-speed calculations
   ↓
Step 9 final Polars event table
   ↓
event Parquet
```

Only the Step 4 portion of this production path is complete at the current
checkpoint.

---

# 67. Architecture amendment — rationale and constraints

The architecture was amended after Step 9 because the real project dataset is much
larger than the small sample used during initial correctness development.

The refactor is intentionally conservative:

1. Preserve behavior first.
2. Change one pipeline layer at a time.
3. Run regression tests after each change.
4. Keep the old reference implementation available until parity is proven.
5. Benchmark only after the complete Steps 4–9 production path exists.
6. Remove pandas only if the final code and integration no longer require it.

The project deliberately avoids stacking multiple dataframe/query engines without
evidence. Polars is the single intended production processing engine.

---

# 68. M2.5 — Step 4 Polars/Parquet ingestion refactor

**Status:** COMPLETE for the currently defined conversion and lazy-loading layer.  
**Regression result at completion:** 78/78 passing.

## 68.1 New file — `src/ingestion/conversion.py`

The conversion layer was added so CSV remains the source format while Parquet
becomes the repeated working format.

### `convert_csv_to_parquet(csv_path, parquet_path)`

Purpose:

- accepts one raw CSV path
- creates the destination directory when necessary
- scans the CSV with Polars
- parses `timestamp` once into a real Polars datetime
- writes the result to Parquet

Production implementation uses the lazy Polars path conceptually:

```python
pl.scan_csv(...)
    .with_columns(...)
    .sink_parquet(...)
```

The timestamp parsing rule currently used by the tested sample is:

```text
%Y-%m-%d %H:%M:%S
```

The timestamp remains timezone-naive. No UTC timezone is invented.

### `convert_csv_pool_to_parquet(csv_paths, output_dir)`

Purpose:

- accepts multiple source CSV files
- converts each file using `convert_csv_to_parquet()`
- preserves one output file per input file
- names each output using the input stem plus `.parquet`
- returns the generated Parquet paths in input order

The small Python loop here is over **files**, not over telemetry rows, and therefore
does not violate the vectorization requirement for large telemetry processing.

The function reuses the single-file converter instead of duplicating parsing logic.

---

# 69. M2.5 — Step 4 lazy Parquet loading

The existing pandas loader remains for behavioral regression, while the new
production-oriented lazy functions were added to `src/ingestion/loader.py`.

## `scan_parquet_file(file_path)`

Behavior:

- normalizes the input with `Path`
- checks that the file exists
- raises a clear `FileNotFoundError` when missing
- returns `pl.scan_parquet(...)`
- therefore returns a `polars.LazyFrame` instead of eagerly materializing all rows

## `scan_parquet_pool(file_paths)`

Behavior:

- accepts multiple Parquet paths
- rejects an empty pool
- validates that every configured path exists
- creates one lazy scan per file
- combines them with vertical Polars concatenation
- preserves the supplied file order
- returns one `polars.LazyFrame`

Configured file order is important because the AROL counters continue across
day-file boundaries. Later closure reconstruction must therefore be able to see:

```text
last row of day N
        ↓
first row of day N+1
```

as one continuous sequence.

`how="vertical"` is intentionally used instead of silently relaxing incompatible
schemas. Daily files are expected to share the same telemetry schema; a schema
change should be visible rather than hidden.

---

# 70. New Step 4 performance-refactor tests

File:

```text
tests/test_conversion.py
```

New conversion tests:

1. `test_csv_is_converted_to_parquet`
   - output Parquet exists
   - row count is preserved
   - column names are preserved

2. `test_parquet_timestamp_is_datetime`
   - converted `timestamp` is stored as `pl.Datetime("us")`

3. `test_parquet_preserves_numeric_column_types`
   - Count remains integer
   - AppTorque remains floating-point
   - Status remains integer

4. `test_multiple_csv_files_are_converted_to_parquet`
   - multiple CSV files convert successfully
   - output paths preserve input order
   - output names use the original file stems

Additional loader tests in:

```text
tests/test_loader.py
```

5. `test_parquet_is_loaded_lazily`
   - one Parquet file returns `pl.LazyFrame`

6. `test_multiple_parquet_files_load_as_one_lazy_pool`
   - multiple files become one lazy dataset
   - row order follows supplied file order

7. `test_empty_parquet_pool_has_clear_error`
   - empty pool fails explicitly

8. `test_missing_parquet_file_has_clear_error`
   - missing file fails explicitly

---

# 71. Regression count after the Step 4 performance refactor

Original Step 9 baseline:

```text
70 tests
```

New Step 4 refactor tests:

```text
Conversion:        4
Lazy loader:       4
--------------------
New tests:         8
```

Current complete suite:

```text
78 / 78 PASS
```

This is important because the performance work has so far been additive and has
not broken the original behavioral reference.

---

# 72. Current configuration and storage status

Implemented now:

```text
CSV source                                    ✅
Parquet conversion                            ✅
Timestamp parsed during conversion            ✅
Numeric telemetry dtypes preserved            ✅
Multiple CSV → multiple Parquet conversion    ✅
Single-file lazy Parquet scan                  ✅
Multi-file lazy Parquet pool                   ✅
Explicit missing/empty pool errors             ✅
Polars configured as target engine             ✅
```

Not yet implemented:

```text
Polars Step 5 validation                       ✅
Vectorized Step 6 closure detection            ⏳
Polars Step 7 event assembly                   ⏳
Polars Step 8 capping-speed path               ⏳
Polars Step 9 final event table                ⏳
Event-table Parquet persistence                ⏳
Machine/date Parquet partitioning              ⏳
Representative real-data benchmark             ⏳
Measured runtime comparison                     ⏳
Measured memory comparison                      ⏳
Removal of temporary pandas dependency          ⏳
```

---

# 73. Performance claims policy

At this checkpoint:

- Polars/Parquet has been introduced for architectural scalability.
- The new code is lazy where tested.
- No project-specific speedup percentage has been measured.
- No project-specific memory reduction has been measured.

Therefore the project must **not** currently claim:

```text
“X times faster”
“Y% less memory”
“handles the full dataset in Z seconds”
```

Those claims become valid only after the benchmark gate is completed on
representative AROL data.

The future comparison must include, at minimum:

```text
reference pandas + CSV
Polars + CSV
Polars + Parquet
```

and should record input size, relevant phase times, total runtime, and peak memory
when practical.

---

# 74. Current milestone status

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B re-confirmation of changed shared
    dataframe/tool boundary                           ⏳

M1 — Data loads & validates
    Original Step 4 loader                            ✅
    Original Step 5 validation                        ✅

M2 — Event table exists
    Original Steps 6–9                                ✅

M2.5 — Production performance refactor
    Step 4 conversion + lazy loading                  ✅
    Step 5 validation                                 ✅
    Step 6 closure detection                          ✅
    Step 7 event assembly                             ✅
    Step 8 capping speed                              ✅
    Step 9 final event table                          ✅
    Parity verification                               ⏳
    Real-data benchmark                               ⏳

M3 — Analytics
    Steps 10–14                                       BLOCKED until M2.5

M4 — Agent tools
    Steps 15–17                                       ⏳

M5 — Evaluation/docs
    Steps 18–20                                       ⏳

M6 — Integration
    Steps 21–22                                       ⏳
```

---

# 75. Current audit snapshot

**Date:** 2026-09-11  
**Python:** 3.12.14  
**Polars:** 1.44.2  
**Reference dataframe engine:** pandas 3.0.5  
**Canonical target engine:** Polars  
**Canonical target working format:** Parquet  
**Original Steps 4–9:** COMPLETE  
**Original behavioral baseline:** 70/70  
**M2:** COMPLETE  
**M2.5 Step 4:** COMPLETE  
**M2.5 Step 5:** COMPLETE  
**M2.5 Step 6:** COMPLETE  
**Current full suite:** all tests passing after Step 9 (expected total from prior count + 12 new Step 9 tests: 146; use the actual pytest-reported total if different)  
**Benchmark:** NOT YET RUN  
**Next implementation task:** Step 7 — refactor status decoding and event assembly to Polars while preserving the established event/status semantics.

---

# 76. M2.5 — Step 5 Polars validation refactor

**Status:** COMPLETE  
**Polars validation tests:** 16/16 passing  
**Full project regression:** 94/94 passing

The original pandas validation implementation remains untouched as the behavioral
reference. A separate production-oriented module was added:

```text
src/ingestion/validation_polars.py
```

with its own parity-oriented test file:

```text
tests/test_validation_polars.py
```

This separation preserves the known-good reference semantics while allowing the
production path to migrate to Polars incrementally.

## 76.1 Input contract

Every Polars validator accepts either:

```text
pl.DataFrame
pl.LazyFrame
```

A small internal helper normalizes supported input to a LazyFrame.

The production pipeline therefore remains compatible with the lazy Parquet loader
introduced in Step 4.

## 76.2 Missing-value validation

Implemented:

```python
check_missing_values(df)
```

Behavior preserved from the pandas reference:

- returns `{}` when there are no missing values
- returns `{column_name: count}` only for affected columns
- null values are treated as missing
- floating-point NaN values are also treated as missing to preserve pandas
  `isna()` behavior

Performance behavior:

- missing counts are expressed as Polars aggregations
- only the aggregated one-row result is collected
- the full telemetry table is not materialized simply to count missing cells

Tests:

```text
clean data has no missing values            ✅
missing value is detected                   ✅
```

## 76.3 Duplicate-timestamp validation

Implemented:

```python
check_duplicate_timestamps(df)
```

Reference semantics preserved:

- first occurrence of a timestamp is valid
- later repetitions are duplicates
- the report contains duplicate count plus duplicate timestamps
- missing timestamp column produces the same explicit error semantics

The Polars implementation uses distinctness logic equivalent to pandas
`duplicated(keep="first")`.

Tests:

```text
clean data has no duplicate timestamps      ✅
duplicate timestamp is detected             ✅
```

## 76.4 Out-of-order timestamp validation

Implemented:

```python
check_out_of_order_timestamps(df)
```

Rule preserved:

```text
current timestamp < previous timestamp
    => out-of-order row
```

The implementation:

- verifies the timestamp column exists
- verifies it is a Polars Datetime column
- adds an original row index before filtering
- uses `shift(1)` to access the previous timestamp
- collects only detected problem rows

Report structure remains:

```text
count
rows:
  row_index
  previous_timestamp
  current_timestamp
```

Tests:

```text
clean data is in timestamp order            ✅
out-of-order timestamp is detected          ✅
```

## 76.5 Timestamp-gap validation

Implemented:

```python
check_timestamp_gaps(df)
```

Rule preserved exactly:

```text
expected sampling interval = 1 second
gap exists only when interval > 1 second
```

The implementation uses Polars datetime-duration expressions and only collects
rows that violate the expected interval.

Report structure remains:

```text
count
rows:
  row_index
  previous_timestamp
  current_timestamp
  gap_seconds
```

Tests:

```text
clean data has no timestamp gaps            ✅
five-second gap is detected                 ✅
```

## 76.6 Dtype/value-type validation

Implemented:

```python
check_dtypes(df)
```

Reference rules preserved:

```text
timestamp
    must be Datetime

* Count
    must be numeric
    must contain integer-like values

* Status
    must be numeric
    must contain integer-like values

* AppTorque
    must be numeric
```

Examples:

```text
104085      valid Count
104085.0    valid Count
104085.5    invalid Count

2           valid Status
2.0         valid Status
2.5         invalid Status
```

Missing values are not treated as dtype issues because they are already handled by
the dedicated missing-value validator.

For Count and Status columns, integer-like checks are accumulated and evaluated
together rather than forcing one complete dataset scan per telemetry column.

Tests:

```text
clean dtypes are valid                       ✅
bad Count value is detected                  ✅
bad Status value is detected                 ✅
bad AppTorque dtype is detected              ✅
```

One test-data-specific adjustment was required because Polars constructs a strict
typed Series. To test a non-integer numeric Count such as `100.5`, the test first
constructs the Count column as floating-point numeric values, then injects the
non-integer value. This is a test-fixture correction, not a validation semantic
change.

## 76.7 Units metadata validation

Implemented:

```python
check_units_metadata(config)
```

This logic is dataframe-engine independent and preserves the existing project
convention:

```text
AppTorque -> Nm
```

Tests:

```text
valid units metadata                         ✅
missing units metadata is detected           ✅
```

## 76.8 Complete validation report

Implemented:

```python
validate_data(df, config)
```

The report shape remains compatible with the original implementation:

```text
valid
missing_values
timestamps:
  duplicates
  out_of_order
  gaps
dtypes:
  issues
units:
  valid
  issues
```

`valid` becomes false when any validation category reports an issue or a required
timestamp validation precondition fails.

The validator does not repair, sort, drop, or otherwise mutate telemetry data.

Tests:

```text
clean full validation report                 ✅
multiple simultaneous problems reported      ✅
```

---

# 77. Step 5 regression result

Before the Step 5 Polars parity suite:

```text
78 tests passing
```

New Step 5 Polars tests:

```text
16
```

Current full project suite:

```text
94 / 94 PASS
```

The original pandas validation tests still pass, and the new Polars validation
suite passes independently.

---

# 78. Current production-pipeline status

```text
Raw CSV
   ↓
CSV → Parquet conversion                    ✅
   ↓
Lazy Parquet loading                        ✅
   ↓
Polars validation                           ✅
   ↓
Vectorized closure reconstruction           ✅
   ↓
Polars status/event assembly                ⏳
   ↓
Polars capping-speed calculations           ✅
   ↓
Final Polars event table                    ✅
   ↓
Event Parquet                               ⏳
   ↓
Benchmark old vs new                        ⏭ NEXT
   ↓
Step 10 analytics                           BLOCKED until M2.5 complete
```

---

# 79. Current milestone status

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B re-confirmation of changed shared
    dataframe/tool boundary                           ⏳

M1 — Data loads & validates
    Original Step 4 loader                            ✅
    Original Step 5 validation                        ✅

M2 — Event table exists
    Original Steps 6–9                                ✅

M2.5 — Production performance refactor
    Step 4 conversion + lazy loading                  ✅
    Step 5 validation                                 ✅
    Step 6 closure detection                          ✅
    Step 7 event assembly                             ✅
    Step 8 capping speed                              ✅
    Step 9 final event table                          ✅
    Parity verification                               ⏳
    Real-data benchmark                               ⏳

M3 — Analytics
    Steps 10–14                                       BLOCKED until M2.5

M4 — Agent tools
    Steps 15–17                                       ⏳

M5 — Evaluation/docs
    Steps 18–20                                       ⏳

M6 — Integration
    Steps 21–22                                       ⏳
```

---

# 80. Current audit snapshot

**Date:** 2026-09-11  
**Python:** 3.12.14  
**Polars:** 1.44.2  
**Reference dataframe engine:** pandas 3.0.5  
**Canonical production dataframe engine:** Polars  
**Canonical target working format:** Parquet  
**Original Steps 4–9:** COMPLETE  
**Original behavioral baseline:** 70/70  
**M2:** COMPLETE  
**M2.5 Step 4:** COMPLETE  
**M2.5 Step 5:** COMPLETE  
**Current full suite:** all tests passing after Step 9 (expected total from prior count + 12 new Step 9 tests: 146; use the actual pytest-reported total if different)  
**Benchmark:** NOT YET RUN  
**Next implementation task:** Step 6 — vectorized closure detection in Polars.

---

# 81. M2.5 — Step 6 vectorized closure detection

**Status:** COMPLETE  
**New Polars closure tests:** 8/8 passing  
**Original pandas closure tests:** 7/7 passing  
**Full project regression:** 102/102 passing

The original pandas implementation remains untouched as the behavioral reference:

```text
src/ingestion/closure_detection.py
tests/test_closure_detection.py
```

The optimized production implementation was added separately:

```text
src/ingestion/closure_detection_polars.py
tests/test_closure_detection_polars.py
```

This preserves the known-good semantics while removing the Python row-by-row
telemetry loop from the production path.

## 81.1 Closure semantic rule

The exact previously agreed rule remains unchanged:

```text
closure ⇔ current Count == previous Count + 1
```

Equivalent delta rule:

```text
current Count - previous Count == 1
```

Examples:

```text
100  -> 100     no closure
100  -> 101     one closure
100  -> 103     no closure
1001 -> 5       reset/decrease; no closure
```

The first telemetry row cannot create a closure because there is no previous Count.

## 81.2 Current-row event semantics

When a closure is detected, the event attributes come from the **current row**,
i.e. the row on which the exact +1 counter increment appears:

```text
row_index
head_id
torque      <- current row
status      <- current row
timestamp   <- current row
```

This is identical to the original reference behavior.

## 81.3 Production function — lazy closure frame

Implemented:

```python
detect_head_closures_frame(df, head_id)
```

Input:

```text
pl.DataFrame or pl.LazyFrame
```

Output:

```text
pl.LazyFrame
```

The function:

1. normalizes input to LazyFrame;
2. preserves original row position with a row index;
3. computes the Count delta using `shift(1)`;
4. filters for `delta == 1`;
5. projects only event-relevant columns.

Conceptually:

```text
Count
  ↓
Count.shift(1)
  ↓
current - previous
  ↓
filter delta == 1
  ↓
closure rows only
```

No Python iteration occurs over raw telemetry rows.

## 81.4 Compatibility wrapper

Implemented:

```python
detect_head_closures(df, head_id)
```

This wrapper:

- calls the lazy production function;
- collects only the already-filtered closure rows;
- converts those closure rows into the same list-of-dictionaries shape used by
  the original pandas implementation.

Therefore the large raw dataset is processed inside Polars; Python only formats
the much smaller set of detected closure events.

## 81.5 Ordering decision

The closure detector does **not** sort telemetry.

This is intentional:

- validation already reports out-of-order timestamps;
- closure reconstruction must follow the supplied/stitched telemetry sequence;
- silently sorting would mutate semantics and could hide upstream data-quality
  problems.

## 81.6 Stitched-file continuity

Counters are continuous across daily files, so a closure can occur at a file
boundary.

Example:

```text
last row day 1    Count = 100
first row day 2   Count = 101
```

The first row of day 2 must be detected as a closure.

The Polars test suite explicitly verifies this behavior after vertically stitching
two telemetry fragments into one continuous LazyFrame.

---

# 82. Step 6 Polars tests

New tests in:

```text
tests/test_closure_detection_polars.py
```

1. `test_polars_closure_detection_stays_lazy`
   - production frame function returns `pl.LazyFrame`

2. `test_polars_steady_count_produces_zero_closures`
   - unchanged Count produces no event

3. `test_polars_increment_by_one_produces_one_closure`
   - exact +1 produces one closure
   - row index is correct
   - head ID is correct
   - current-row torque/status/timestamp are preserved

4. `test_polars_first_row_does_not_create_a_closure`
   - no previous Count means no event

5. `test_polars_status_change_without_count_increment_produces_no_closure`
   - status alone cannot create a closure

6. `test_polars_count_jump_greater_than_one_produces_no_closure`
   - jump > 1 is deliberately not reconstructed as a closure

7. `test_polars_counter_reset_produces_no_spurious_closure`
   - reset/decrease creates no false closure
   - a preceding exact +1 event is still retained

8. `test_polars_closure_across_stitched_file_boundary_is_detected`
   - exact +1 across file boundary is retained
   - event data comes from first row of the second file

Result:

```text
8 / 8 PASS
```

Original pandas closure suite remains:

```text
7 / 7 PASS
```

---

# 83. Regression count after Step 6

Before Step 6:

```text
94 tests passing
```

New Step 6 Polars tests:

```text
8
```

Current complete project suite:

```text
102 / 102 PASS
```

The performance refactor therefore continues to preserve the established
behavioral contract.

---

# 84. Current production-pipeline status

```text
Raw CSV
   ↓
CSV → Parquet conversion                    ✅
   ↓
Lazy Parquet loading                        ✅
   ↓
Polars validation                           ✅
   ↓
Vectorized Polars closure reconstruction    ✅
   ↓
Polars status/event assembly                ✅
   ↓
Polars capping-speed calculations           ✅
   ↓
Final Polars event table                    ✅
   ↓
Event Parquet                               ⏳
   ↓
Benchmark old vs new                        ⏭ NEXT
   ↓
Step 10 analytics                           BLOCKED until M2.5 complete
```

---

# 85. Current milestone status

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B re-confirmation of changed shared
    dataframe/tool boundary                           ⏳

M1 — Data loads & validates
    Original Step 4 loader                            ✅
    Original Step 5 validation                        ✅

M2 — Event table exists
    Original Steps 6–9                                ✅

M2.5 — Production performance refactor
    Step 4 conversion + lazy loading                  ✅
    Step 5 validation                                 ✅
    Step 6 closure detection                          ✅
    Step 7 event assembly                             ✅
    Step 8 capping speed                              ✅
    Step 9 final event table                          ✅
    Parity verification                               ⏳
    Real-data benchmark                               ⏳

M3 — Analytics
    Steps 10–14                                       BLOCKED until M2.5

M4 — Agent tools
    Steps 15–17                                       ⏳

M5 — Evaluation/docs
    Steps 18–20                                       ⏳

M6 — Integration
    Steps 21–22                                       ⏳
```

---

# 86. Current audit snapshot

**Date:** 2026-09-11  
**Python:** 3.12.14  
**Polars:** 1.44.2  
**Reference dataframe engine:** pandas 3.0.5  
**Canonical production dataframe engine:** Polars  
**Canonical target working format:** Parquet  
**Original Steps 4–9:** COMPLETE  
**Original behavioral baseline:** 70/70  
**M2:** COMPLETE  
**M2.5 Step 4:** COMPLETE  
**M2.5 Step 5:** COMPLETE  
**M2.5 Step 6:** COMPLETE  
**Current full suite:** all tests passing after Step 9 (expected total from prior count + 12 new Step 9 tests: 146; use the actual pytest-reported total if different)  
**Benchmark:** NOT YET RUN  
**Next implementation task:** Step 7 — Polars status decoding and event assembly.

---

# 87. M2.5 — Step 7 Polars status decoding and event assembly

**Status:** COMPLETE  
**New Polars event-assembly tests:** 22/22 passing  
**Original pandas event-assembly tests:** 19/19 passing  
**Full project regression:** 124/124 passing

The original reference implementation remains untouched:

```text
src/ingestion/event_assembly.py
tests/test_event_assembly.py
```

The production-oriented Polars implementation was added separately:

```text
src/ingestion/event_assembly_polars.py
tests/test_event_assembly_polars.py
```

This preserves the known-good scalar/reference behavior while allowing the
production pipeline to stay inside Polars.

## 87.1 Status-code contract

The complete known status map is preserved:

```text
0   -> Closure OK       reject False
2   -> No Load          reject False
3   -> No Load          reject True
4   -> No Closure       reject False
5   -> No Closure       reject True
8   -> No InTorque      reject False
9   -> No InTorque      reject True
16  -> No CapTurns      reject False
17  -> No CapTurns      reject True
32  -> Following Error  reject False
33  -> Following Error  reject True
64  -> Bad Closure      reject False
65  -> Bad Closure      reject True
```

Known cap-presence semantics remain intentionally limited to:

```text
0   -> True
2   -> False
65  -> True
```

For other known codes, `cap_present` remains null because the current project
contract does not establish that information.

Unknown status codes preserve the reference behavior:

```text
error_class    -> "Unknown (<code>)"
reject_signal  -> null
cap_present    -> null
```

No additional status meaning is inferred.

## 87.2 Scalar compatibility functions

The Polars module retains scalar helpers equivalent to the reference behavior:

```python
decode_status(status)
assemble_event(closure, machine_id)
```

These are useful for parity tests and compatibility, but they are not the preferred
large-scale production path.

## 87.3 Vectorized production event assembly

Implemented:

```python
assemble_events_frame(closures, machine_id)
```

Input:

```text
pl.DataFrame or pl.LazyFrame
```

Output:

```text
pl.LazyFrame
```

Expected closure input fields:

```text
row_index
head_id
torque
status
timestamp
```

Output event schema:

```text
ts
machine_id
head_id
torque
status
error_class
reject_signal
cap_present
```

The production implementation:

1. normalizes input to LazyFrame;
2. normalizes event-relevant dtypes;
3. joins closure rows against a tiny 13-row status lookup table;
4. generates `Unknown (<code>)` only for unmatched status values;
5. preserves nullable reject/cap semantics;
6. selects exactly the agreed event schema;
7. remains lazy until explicitly collected.

## 87.4 Status lookup design

The status map is represented as a small Polars lookup table.

Conceptually:

```text
closure rows
     ↓
left join with 13-row status lookup
     ↓
known codes decoded in one vectorized operation
     ↓
unknown codes retain null flags
     ↓
unknown error_class generated as "Unknown (<code>)"
```

This avoids Python decoding of every event row while keeping the implementation
simple and auditable.

No additional processing engine or database is introduced.

## 87.5 Event timestamp semantics

The Step 6 contract remains intact:

- a closure belongs to the row where Count increments by exactly +1;
- torque comes from that current row;
- status comes from that current row;
- timestamp comes from that current row.

The Step 7 integration test verifies that the final event `ts` is still the timestamp
of the Count-increment row after vectorized closure detection and event assembly.

## 87.6 Event schema and dtypes

The Polars production event table uses exactly:

```text
ts              Datetime
machine_id      String
head_id         String
torque          Float64
status          Int64
error_class     String
reject_signal   Boolean (nullable)
cap_present     Boolean (nullable)
```

This matches the amended contract for the event-level representation.

---

# 88. Step 7 Polars tests

New tests in:

```text
tests/test_event_assembly_polars.py
```

Coverage includes:

1. production event assembly stays lazy;
2. status `0` decoding;
3. status `2` decoding;
4. status `65` decoding;
5. unknown-status behavior;
6. all 13 known status mappings through parametrized cases;
7. scalar event-schema compatibility;
8. vectorized event-schema column order and dtypes;
9. Step 6 → Step 7 timestamp integration;
10. vectorized handling of known and unknown codes;
11. completeness of the known status-map key set.

Because the all-known-status test is parametrized across 13 codes, pytest reports:

```text
22 / 22 PASS
```

Original reference event-assembly suite:

```text
19 / 19 PASS
```

---

# 89. Regression count after Step 7

Before Step 7:

```text
102 tests passing
```

New Step 7 Polars tests:

```text
22
```

Current complete project suite:

```text
124 / 124 PASS
```

The M2.5 migration continues to preserve the original reference behavior.

---

# 90. Current production-pipeline status

```text
Raw CSV
   ↓
CSV → Parquet conversion                    ✅
   ↓
Lazy Parquet loading                        ✅
   ↓
Polars validation                           ✅
   ↓
Vectorized Polars closure reconstruction    ✅
   ↓
Polars status/event assembly                ✅
   ↓
Polars capping-speed calculations           ✅
   ↓
Final Polars event table                    ✅
   ↓
Event Parquet                               ⏳
   ↓
Benchmark old vs new                        ⏭ NEXT
   ↓
Step 10 analytics                           BLOCKED until M2.5 complete
```

---

# 91. Current milestone status

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B re-confirmation of changed shared
    dataframe/tool boundary                           ⏳

M1 — Data loads & validates
    Original Step 4 loader                            ✅
    Original Step 5 validation                        ✅

M2 — Event table exists
    Original Steps 6–9                                ✅

M2.5 — Production performance refactor
    Step 4 conversion + lazy loading                  ✅
    Step 5 validation                                 ✅
    Step 6 closure detection                          ✅
    Step 7 event assembly                             ✅
    Step 8 capping speed                              ✅
    Step 9 final event table                          ✅
    Parity verification                               ⏳
    Real-data benchmark                               ⏳

M3 — Analytics
    Steps 10–14                                       BLOCKED until M2.5

M4 — Agent tools
    Steps 15–17                                       ⏳

M5 — Evaluation/docs
    Steps 18–20                                       ⏳

M6 — Integration
    Steps 21–22                                       ⏳
```

---

# 92. Current audit snapshot

**Date:** 2026-09-11  
**Python:** 3.12.14  
**Polars:** 1.44.2  
**Reference dataframe engine:** pandas 3.0.5  
**Canonical production dataframe engine:** Polars  
**Canonical target working format:** Parquet  
**Original Steps 4–9:** COMPLETE  
**Original behavioral baseline:** 70/70  
**M2:** COMPLETE  
**M2.5 Step 4:** COMPLETE  
**M2.5 Step 5:** COMPLETE  
**M2.5 Step 6:** COMPLETE  
**M2.5 Step 7:** COMPLETE  
**Current full suite:** all tests passing after Step 9 (expected total from prior count + 12 new Step 9 tests: 146; use the actual pytest-reported total if different)  
**Benchmark:** NOT YET RUN  
**Next implementation task:** Step 8 — Polars capping-speed calculations.

---

# 93. M2.5 — Step 8 Polars capping-speed calculations

**Status:** COMPLETE  
**New Polars capping-speed tests:** 9/9 passing  
**Original reference capping-speed tests:** passing  
**Full project regression:** 134/134 passing

The original reference implementation remains untouched:

```text
src/analytics/capping_speed.py
tests/test_capping_speed.py
```

The production-oriented Polars implementation was added separately:

```text
src/analytics/capping_speed_polars.py
tests/test_capping_speed_polars.py
```

## 93.1 Preserved numerical contract

The reference conversion formula remains unchanged:

```text
pieces_per_hour = closures * 3600 / interval_seconds
```

The running capping-speed result remains the running arithmetic mean of the
per-interval speeds.

Reference example:

```text
closures per interval:  [2, 3, 1]
interval_seconds:       1

pieces/hour:            [7200, 10800, 3600]
running mean:           [7200, 9000, 7200]
```

Non-positive interval lengths remain invalid.

Empty input still returns an empty result.

## 93.2 Scalar compatibility functions

The Polars module preserves:

```python
incremental_average(current_mean, new_value, n)
closures_to_pieces_per_hour(closures, interval_seconds)
```

These match the original scalar semantics and remain useful for parity and small
calculations.

## 93.3 Lazy production calculation

Implemented:

```python
running_capping_speed_frame(
    df,
    interval_seconds,
    closures_col="closures",
)
```

Input:

```text
pl.DataFrame or pl.LazyFrame
```

Output:

```text
pl.LazyFrame
```

The production path:

1. validates `interval_seconds > 0`;
2. verifies the closures column exists;
3. creates a 1-based interval index;
4. computes pieces/hour with a Polars expression;
5. computes the running arithmetic mean as cumulative sum divided by interval
   number;
6. returns only closures, pieces/hour, and running mean.

Conceptually:

```text
closures
   ↓
× 3600 / interval_seconds
   ↓
pieces_per_hour
   ↓
cumulative sum
   ↓
÷ interval number
   ↓
running_mean
```

No Python loop is used for the production DataFrame/LazyFrame calculation.

## 93.4 Compatibility wrapper

Implemented:

```python
running_capping_speed(
    closures_per_interval,
    interval_seconds,
)
```

The wrapper preserves the original list-based API while delegating the main
calculation to the Polars production path.

## 93.5 Scope decision

Step 8 does **not** introduce new event-time interval grouping.

The original Step 8 contract accepts closure counts per interval. Adding a new
grouping definition here would change semantics rather than refactor the existing
behavior.

Any future interval construction from event timestamps must therefore be treated
as a separate explicitly specified behavior.

## 93.6 Performance interpretation

Step 8 is now consistent with the Polars production architecture, but no claim is
made that this step alone provides a major speedup.

The largest known pre-refactor bottleneck was the raw telemetry row loop in closure
detection. Performance claims remain blocked until the full real-data benchmark.

---

# 94. Step 8 Polars tests

New tests cover:

```text
incremental-average parity                    ✅
closures → pieces/hour                        ✅
zero interval rejected                        ✅
negative interval rejected                    ✅
production frame remains lazy                 ✅
vectorized instantaneous speeds               ✅
vectorized running means                      ✅
list-wrapper parity                           ✅
empty input / invalid interval behavior       ✅
```

New Polars Step 8 suite:

```text
9 / 9 PASS
```

The final full-suite count observed after Step 8 is:

```text
134 / 134 PASS
```

The initially estimated total was 133, but the repository actually collected 134
tests. The observed pytest collection/result is authoritative; no failure is
present and no test was removed to force the estimate.

---

# 95. Current production-pipeline status

```text
Raw CSV
   ↓
CSV → Parquet conversion                    ✅
   ↓
Lazy Parquet loading                        ✅
   ↓
Polars validation                           ✅
   ↓
Vectorized Polars closure reconstruction    ✅
   ↓
Polars status/event assembly                ✅
   ↓
Polars capping-speed calculations           ✅
   ↓
Final Polars event table                    ✅
   ↓
Event Parquet                               ✅
   ↓
Benchmark old vs new                        ⏭ NEXT
   ↓
Step 10 analytics                           BLOCKED until M2.5 complete
```

---

# 96. Current milestone status

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B re-confirmation of changed shared
    dataframe/tool boundary                           ⏳

M1 — Data loads & validates
    Original Step 4 loader                            ✅
    Original Step 5 validation                        ✅

M2 — Event table exists
    Original Steps 6–9                                ✅

M2.5 — Production performance refactor
    Step 4 conversion + lazy loading                  ✅
    Step 5 validation                                 ✅
    Step 6 closure detection                          ✅
    Step 7 event assembly                             ✅
    Step 8 capping speed                              ✅
    Step 9 final event table                          ✅
    Event Parquet persistence                         ✅
    Parity verification                               ⏳
    Real-data benchmark                               ⏳

M3 — Analytics
    Steps 10–14                                       BLOCKED until M2.5

M4 — Agent tools
    Steps 15–17                                       ⏳

M5 — Evaluation/docs
    Steps 18–20                                       ⏳

M6 — Integration
    Steps 21–22                                       ⏳
```

---

# 97. Current audit snapshot

**Date:** 2026-09-11  
**Python:** 3.12.14  
**Polars:** 1.44.2  
**Reference dataframe engine:** pandas 3.0.5  
**Canonical production dataframe engine:** Polars  
**Canonical target working format:** Parquet  
**Original Steps 4–9:** COMPLETE  
**Original behavioral baseline:** 70/70  
**M2:** COMPLETE  
**M2.5 Step 4:** COMPLETE  
**M2.5 Step 5:** COMPLETE  
**M2.5 Step 6:** COMPLETE  
**M2.5 Step 7:** COMPLETE  
**M2.5 Step 8:** COMPLETE  
**Current full suite:** all tests passing after Step 9 (expected total from prior count + 12 new Step 9 tests: 146; use the actual pytest-reported total if different)  
**Benchmark:** NOT YET RUN  
**Next implementation task:** Step 9 — final Polars event table and event-Parquet persistence.

---

# 98. M2.5 — Step 9 final Polars event table and event Parquet

**Status:** COMPLETE  
**New Step 9 Polars tests:** 12/12 passing  
**Original reference event-table tests:** passing  
**Full project regression:** all tests passing after Step 9

The original pandas reference remains untouched:

```text
src/ingestion/event_table.py
tests/test_event_table.py
```

The production implementation was added separately:

```text
src/ingestion/event_table_polars.py
tests/test_event_table_polars.py
```

## 98.1 Final event-table contract

The final event schema is fixed as:

```text
ts              Datetime
machine_id      String
head_id         String
torque          Float64
status          Int64
error_class     String
reject_signal   Boolean (nullable)
cap_present     Boolean (nullable)
```

Column order:

```text
ts
machine_id
head_id
torque
status
error_class
reject_signal
cap_present
```

## 98.2 Automatic head detection

Implemented:

```python
detect_head_ids(df)
```

Behavior preserved from the reference implementation:

- head IDs are inferred from columns ending in `" Count"`;
- no fixed 36-head assumption is used;
- returned IDs are sorted deterministically.

The implementation inspects LazyFrame schema metadata rather than materializing
telemetry rows.

## 98.3 Lazy final event-table construction

Implemented:

```python
build_event_table_frame(df, machine_id)
```

Input:

```text
pl.DataFrame or pl.LazyFrame
```

Output:

```text
pl.LazyFrame
```

Production flow:

```text
telemetry LazyFrame
      ↓
detect head IDs
      ↓
Step 6 closure detection for each head
      ↓
concatenate closure LazyFrames
      ↓
Step 7 vectorized status/event assembly
      ↓
enforce exact event schema
      ↓
sort by ts, then head_id
      ↓
final event LazyFrame
```

The only Python loop is over the small number of detected heads. There is no
Python loop over raw telemetry rows.

## 98.4 Deterministic ordering

Reference ordering is preserved:

```text
primary key:   ts
secondary key: head_id
```

Events from different heads with the same timestamp are retained as distinct rows.

Stable/deterministic ordering is maintained for otherwise tied rows.

## 98.5 Empty event-table behavior

When no closure events exist, the production implementation returns an empty event
table with the complete event schema rather than an untyped/columnless result.

This preserves downstream compatibility for analytics and Parquet persistence.

## 98.6 Materialized compatibility wrapper

Implemented:

```python
build_event_table(df, machine_id)
```

This collects the final LazyFrame only when a materialized Polars DataFrame is
explicitly requested.

## 98.7 Event-Parquet persistence

Implemented:

```python
write_event_table_parquet(events, parquet_path)
```

Behavior:

- accepts Polars DataFrame or LazyFrame;
- creates parent directories when required;
- enforces the final event schema before writing;
- writes using the Polars lazy Parquet sink;
- returns the output Path.

Both non-empty and empty event tables preserve schema through a Parquet
round-trip.

---

# 99. Step 9 Polars tests

New tests cover:

```text
automatic head detection                              ✅
no hard-coded 36-head assumption                      ✅
production event table remains lazy                   ✅
empty event table keeps exact schema                   ✅
one closure -> one event                              ✅
multiple heads -> multiple events                     ✅
chronological ordering                                ✅
same timestamp / different heads retained             ✅
deterministic repeated construction                   ✅
final event dtypes                                    ✅
non-empty event Parquet round-trip                    ✅
empty event Parquet schema round-trip                 ✅
```

New Step 9 suite:

```text
12 / 12 PASS
```

The previously reported full-suite count before Step 9 was:

```text
134
```

Therefore the expected arithmetic total after adding 12 new tests is:

```text
146
```

The actual pytest-reported collection/result is authoritative if it differs.

---

# 100. M2.5 implementation status

The Polars/Parquet production refactor for Steps 4–9 is now functionally complete:

```text
Step 4  CSV -> Parquet + lazy loading          ✅
Step 5  Polars validation                      ✅
Step 6  vectorized closure detection           ✅
Step 7  vectorized event assembly              ✅
Step 8  Polars capping-speed calculations      ✅
Step 9  final event table                      ✅
        event-Parquet persistence              ✅
```

The old pandas/reference implementation is still retained intentionally because
the mandatory benchmark and final parity gate have not yet been completed.

---

# 101. Production pipeline after Step 9

```text
Raw AROL CSV
    ↓
one-time / incremental conversion
    ↓
Parquet
    ↓
Polars LazyFrame
    ↓
validation
    ↓
vectorized exact +1 closure reconstruction
    ↓
vectorized status decoding / event assembly
    ↓
deterministically sorted final event table
    ↓
event Parquet
    ↓
future analytics tools
```

Step 10 must not begin yet.

---

# 102. Mandatory benchmark gate

Before Step 10, the project must measure the new architecture on representative
AROL data.

Required comparison:

```text
A. pandas + CSV reference
B. Polars + CSV
C. Polars + Parquet
```

At minimum record:

```text
input files
input rows
input size
conversion time where applicable
load/scan time
closure/event reconstruction time
total pipeline time
peak memory when practical
output event count
```

Correctness must be checked alongside performance. The benchmark must verify that
reference and Polars paths produce equivalent event semantics.

No speedup or memory-reduction claim is permitted until this measurement exists.

---

# 103. Current milestone status

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B re-confirmation of changed shared
    dataframe/tool boundary                           ⏳

M1 — Data loads & validates
    Original Step 4 loader                            ✅
    Original Step 5 validation                        ✅

M2 — Event table exists
    Original Steps 6–9                                ✅

M2.5 — Production performance refactor
    Step 4 conversion + lazy loading                  ✅
    Step 5 validation                                 ✅
    Step 6 closure detection                          ✅
    Step 7 event assembly                             ✅
    Step 8 capping speed                              ✅
    Step 9 final event table                          ✅
    Event Parquet persistence                         ✅
    Parity verification                               ⏳
    Real-data benchmark                               ⏭ NEXT

M3 — Analytics
    Steps 10–14                                       BLOCKED until benchmark gate

M4 — Agent tools
    Steps 15–17                                       ⏳

M5 — Evaluation/docs
    Steps 18–20                                       ⏳

M6 — Integration
    Steps 21–22                                       ⏳
```

---

# 104. Current audit snapshot

**Date:** 2026-09-11  
**Python:** 3.12.14  
**Polars:** 1.44.2  
**Reference dataframe engine:** pandas 3.0.5  
**Canonical production dataframe engine:** Polars  
**Canonical working/event format:** Parquet  
**Original Steps 4–9:** COMPLETE  
**Original behavioral baseline:** 70/70  
**M2:** COMPLETE  
**M2.5 Steps 4–9:** COMPLETE  
**Event-Parquet persistence:** COMPLETE  
**Full regression:** ALL TESTS PASSING  
**Expected total from previous count + Step 9 tests:** 146  
**Benchmark:** NOT YET RUN  
**Step 10:** BLOCKED until benchmark/parity gate is complete

---

# 105. Immediate next-step rule — benchmark gate

1. Do not delete pandas/reference modules yet.
2. Commit the completed Step 9 production implementation.
3. Preserve/tag this pre-benchmark state.
4. Benchmark representative real AROL data, not only the tiny sample.
5. Compare pandas + CSV, Polars + CSV, and Polars + Parquet.
6. Verify event-count/schema/semantic parity during the benchmark.
7. Record measured runtime and memory evidence.
8. Only after the benchmark/parity gate should pandas removal be reconsidered.
9. Only after the benchmark/parity gate should Step 10 analytics begin.
10. Update this audit with the measured benchmark results.


---

# 106. M2.5 benchmark/parity gate — COMPLETE

**Date:** 2026-09-12

The mandatory real-data benchmark and parity gate required before Step 10 has now
been completed successfully.

The production path was evaluated against the original pandas reference using
real AROL telemetry from machine `MCC777`.

The benchmark compared:

```text
A. pandas + CSV reference
B. Polars + CSV
C. Polars + Parquet
```

Correctness and performance were checked together.

---

# 107. Real dataset used

## One-day dataset

```text
file:
data/telemetry_MCC777eda3db57348ef8a3113a642ae74db_2026-02-01.csv

files:          1
input rows:     86,399
CSV bytes:      57,176,271
Parquet bytes:   1,719,462
events:         765,703
```

## Three-day stitched dataset

Consecutive files:

```text
2026-02-01
2026-02-02
2026-02-03
```

Measured input:

```text
files:           3
input rows:      259,198
CSV bytes:       173,627,678
Parquet bytes:     5,242,408
events:          2,290,224
```

The three-day benchmark exercises real stitched-file boundaries from the same
machine.

---

# 108. CSV → Parquet conversion evidence

## One day

```text
input bytes:          57,176,271
output bytes:          1,719,462
conversion seconds:       0.0365
compression ratio:       ~33.3x smaller
size reduction:          ~97.0%
```

## Three days

```text
input bytes:         173,627,678
output bytes:          5,242,408
conversion seconds:       0.1108
compression ratio:       ~33.1x smaller
size reduction:          ~97.0%
```

Parquet is therefore retained as the canonical persisted working/event format.

---

# 109. One-day performance benchmark

The pandas reference measurement used the real one-day file and produced:

```text
mode:                 pandas + CSV
rows:                 86,399
events:               765,703
validation_valid:     false
total seconds:        210.2241
event-build seconds:  209.9511
peak RSS:             801,128,448 bytes
peak RSS:             ~764.0 MiB
```

Three optimized measurements were collected for each production mode. The median
is used below.

## Polars + CSV median

```text
total seconds:        0.1851
event-build seconds:  0.0620
peak RSS:             677,003,264 bytes
peak RSS:             ~645.6 MiB
```

Measured speedup versus the pandas reference on this dataset:

```text
~1,136x
```

Measured peak-RSS reduction:

```text
~15.5%
```

## Polars + Parquet median

```text
total seconds:        0.1094
event-build seconds:  0.0604
peak RSS:             523,993,088 bytes
peak RSS:             ~499.7 MiB
```

Measured speedup versus the pandas reference on this dataset:

```text
~1,921x
```

Measured peak-RSS reduction:

```text
~34.6%
```

These speedups are measurements on the tested AROL dataset and are not asserted
as universal Polars speedups.

---

# 110. Three-day stitched performance benchmark

All three implementations produced exactly:

```text
input rows:         259,198
event count:      2,290,224
validation_valid: false
```

Measured results:

```text
pandas + CSV
    total seconds:        634.4165
    event-build seconds:  633.6476
    peak RSS:             2,309,390,336 bytes
    peak RSS:             ~2,202.4 MiB

Polars + CSV
    total seconds:        0.3392
    event-build seconds:  0.1544
    peak RSS:             1,527,234,560 bytes
    peak RSS:             ~1,456.5 MiB

Polars + Parquet
    total seconds:        0.2148
    event-build seconds:  0.1414
    peak RSS:             1,125,515,264 bytes
    peak RSS:             ~1,073.4 MiB
```

Measured speedups versus pandas + CSV:

```text
Polars + CSV:      ~1,870x
Polars + Parquet:  ~2,953x
```

Measured peak-RSS reduction versus pandas + CSV:

```text
Polars + CSV:      ~33.9%
Polars + Parquet:  ~51.3%
```

Again, these are dataset-specific measured results.

---

# 111. Exact event parity evidence

The one-day real-data event table was reconstructed independently by the pandas
reference and the Polars production implementation.

Both produced:

```text
765,703 events
```

The complete normalized event tables were compared row-by-row with:

```text
check_dtypes=True
check_row_order=True
check_column_order=True
```

Result:

```text
PARITY PASSED
All 765,703 event rows match exactly.
```

This verifies that the optimized implementation preserves event content, order,
schema, and semantics on the tested real file.

---

# 112. Validation parity evidence

The three-day real dataset returned `valid=False` in both the pandas reference
and Polars production validators.

The complete validation reports matched exactly.

Both implementations reported:

```text
missing values:    none
duplicate ts:      0
out-of-order ts:   0
dtype issues:      none
units:             valid
timestamp gaps:    2
```

Exact gaps:

```text
row 3600
previous: 2026-01-31 16:59:59
current:  2026-01-31 17:00:01
gap:      2.0 seconds

row 89999
previous: 2026-02-01 16:59:59
current:  2026-02-01 17:00:01
gap:      2.0 seconds
```

Therefore `validation_valid=False` is a property of the source telemetry and not
a Polars regression.

---

# 113. Benchmark gate decision

The mandatory pre-Step-10 gate is now considered **PASSED**.

Evidence completed:

```text
existing regression/unit tests                  ✅
Polars conversion tests                         ✅
stitched-boundary regression tests              ✅
one-day row-count parity                        ✅
one-day event-count parity                      ✅
one-day complete event-table equality           ✅
three-day row-count parity                      ✅
three-day event-count parity                    ✅
three-day validation-state parity               ✅
three-day detailed validation-report parity     ✅
runtime benchmark                               ✅
peak-memory benchmark                           ✅
CSV → Parquet conversion benchmark              ✅
```

The pandas implementation remains in the repository as a behavioral reference
until deliberate cleanup/removal is approved.

---

# 114. Updated milestone status

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B re-confirmation of changed shared
    dataframe/tool boundary                           ⏳

M1 — Data loads & validates
    Original Step 4 loader                            ✅
    Original Step 5 validation                        ✅

M2 — Event table exists
    Original Steps 6–9                                ✅

M2.5 — Production performance refactor
    Step 4 conversion + lazy loading                  ✅
    Step 5 validation                                 ✅
    Step 6 closure detection                          ✅
    Step 7 event assembly                             ✅
    Step 8 capping speed                              ✅
    Step 9 final event table                          ✅
    Event Parquet persistence                         ✅
    Exact real-data event parity                      ✅
    Detailed validation parity                        ✅
    Real-data runtime benchmark                       ✅
    Peak-memory benchmark                             ✅
    M2.5 benchmark/parity gate                        ✅ COMPLETE

M3 — Analytics
    Step 10 torque statistics                         ⏭ NEXT
    Steps 11–14                                       ⏳

M4 — Agent tools
    Steps 15–17                                       ⏳

M5 — Evaluation/docs
    Steps 18–20                                       ⏳

M6 — Integration
    Steps 21–22                                       ⏳
```

---

# 115. Current audit snapshot

**Date:** 2026-09-12  
**Python:** 3.12.14  
**Polars:** 1.44.2  
**Reference dataframe engine:** pandas 3.0.5  
**Canonical production dataframe engine:** Polars  
**Canonical persisted working/event format:** Parquet  
**Original Steps 4–9:** COMPLETE  
**M2:** COMPLETE  
**M2.5:** COMPLETE  
**Event-Parquet persistence:** COMPLETE  
**Real-data exact event parity:** PASSED  
**Detailed validation parity:** PASSED  
**Real-data benchmark:** COMPLETE  
**Peak-memory benchmark:** COMPLETE  
**Step 10:** UNBLOCKED — NEXT

---

# 116. Immediate next implementation task

Begin **Step 10 — Torque statistics**.

Production analytics must:

1. consume the clean Polars event table / event Parquet;
2. never read raw wide telemetry directly;
3. use deterministic Polars operations;
4. return JSON-safe plain Python values;
5. support optional status filtering;
6. return mean, minimum, maximum, standard deviation, and sample size;
7. include focused unit tests with hand-computed expected values.



---

# 117. Step 10 — Torque statistics

**Status:** COMPLETE  
**Full project regression after Step 10:** 155 / 155 PASS  
**Milestone:** M3 analytics in progress  
**Next step:** Step 11 — Torque distribution

Production implementation:

```text
src/analytics/torque_stats.py
```

The implementation consumes only the clean Polars event table / event Parquet
boundary. It does not access raw wide telemetry.

The function supports:

```python
torque_stats(events, status_filter=None)
```

and returns deterministic, JSON-safe values for:

```text
mean
min
max
std
sample_size
```

Status filtering supports:

```text
None          -> all events
"successful"  -> status == 0
integer code  -> exact raw AROL status
```

Null and non-finite torque observations are excluded from the statistical sample.
Standard deviation uses the sample definition (`ddof=1`).

Focused tests cover:

```text
hand-computed mean/min/max/std
successful-only filtering
numeric status filtering
LazyFrame input
empty filtered result
JSON serialization
required-column validation
invalid filter handling
```

The complete repository regression suite passed:

```text
155 passed
```

Therefore Step 10 is accepted as complete.

---

# 118. Updated milestone status after Step 10

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B shared-boundary confirmation              ⏳

M1 — Data loads & validates
    Steps 4–5                                         ✅

M2 — Event table exists
    Steps 6–9                                         ✅

M2.5 — Performance refactor verified
    Polars/Parquet refactor                           ✅
    exact event parity                                ✅
    validation parity                                 ✅
    runtime/memory benchmark                          ✅ COMPLETE

M3 — Analytics
    Step 10 torque statistics                         ✅
    Step 11 torque distribution                       ⏭ NEXT
    Step 12 trend analysis                            ⏳
    Step 13 anomaly detection                         ⏳
    Step 14 head correlation                          ⏳

M4 — Agent tools
    Steps 15–17                                       ⏳

M5 — Evaluation/docs
    Steps 18–20                                       ⏳

M6 — Integration
    Steps 21–22                                       ⏳
```

---

# 119. Immediate next implementation task

Begin **Step 11 — Torque distribution**.

Required behavior from the working specification:

```text
- consume the clean Polars event table / event Parquet
- return histogram bin edges and counts as data, not a plot
- support configurable bins
- counts must sum to the number of events considered
- output must be JSON-safe
```



---

# 120. Step 11 — Torque distribution

**Status:** COMPLETE  
**Full project regression after Step 11:** 171 / 171 PASS  
**Milestone:** M3 analytics in progress  
**Next step:** Step 12 — Trend analysis

Production implementation:

```text
src/analytics/torque_distribution.py
```

The function consumes the clean Polars event table / event Parquet boundary and
returns histogram data rather than rendering a plot.

Supported output:

```text
bin_edges
counts
sample_size
```

Behavior verified by tests:

```text
configurable number of bins
hand-computed two-bin example
counts sum to sample size
successful-only status filtering
numeric status filtering
LazyFrame input
empty filtered result
constant-torque input
non-finite torque exclusion
JSON-safe plain Python output
invalid bin validation
```

The complete repository regression suite passed:

```text
171 passed
```

Therefore Step 11 is accepted as complete.

---

# 121. Updated milestone status after Step 11

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B shared-boundary confirmation              ⏳

M1 — Data loads & validates
    Steps 4–5                                         ✅

M2 — Event table exists
    Steps 6–9                                         ✅

M2.5 — Performance refactor verified
    Polars/Parquet refactor                           ✅
    exact event parity                                ✅
    validation parity                                 ✅
    runtime/memory benchmark                          ✅ COMPLETE

M3 — Analytics
    Step 10 torque statistics                         ✅
    Step 11 torque distribution                       ✅
    Step 12 trend analysis                            ⏭ NEXT
    Step 13 anomaly detection                         ⏳
    Step 14 head correlation                          ⏳

M4 — Agent tools
    Steps 15–17                                       ⏳

M5 — Evaluation/docs
    Steps 18–20                                       ⏳

M6 — Integration
    Steps 21–22                                       ⏳
```

---

# 122. Immediate next implementation task

Begin **Step 12 — Trend analysis**.

Working-spec requirements:

```text
- torque_trend(events, window=...) -> dict
- moving average over event time
- deterministic drift signal
- event timestamps drive the time window
- window size comes from config
- synthetic upward drift must fire
- flat synthetic data must not fire
- JSON-safe output
```

The shared configuration already defines:

```yaml
analytics:
  drift_window_seconds: 3600
```



---

# 123. Step 12 — Trend analysis

**Status:** COMPLETE  
**Full project regression after Step 12:** 189 / 189 PASS  
**Milestone:** M3 analytics in progress  
**Next step:** Step 13 — Anomaly detection

Production implementation:

```text
src/analytics/trend_analysis.py
```

Step 12 adds deterministic event-time trend analysis over the clean Polars event
boundary. The configured trailing window is read from:

```yaml
analytics:
  drift_window_seconds: 3600
```

The implementation provides:

```text
- timestamp-driven trailing moving average
- deterministic drift slope
- upward / downward / stable / insufficient-data classification
- optional event-status filtering
- LazyFrame support
- JSON-safe timestamps and numerical output
```

Focused tests verify:

```text
window is read from config
moving average is time-based rather than row-count based
synthetic upward drift fires
flat synthetic data remains stable
synthetic downward drift is identified
LazyFrame input
status filtering
empty and single-event behavior
non-finite torque exclusion
JSON serialization
invalid/missing window configuration
```

The complete repository regression suite passed:

```text
189 passed
```

Therefore Step 12 is accepted as complete.

---

# 124. Updated milestone status after Step 12

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B shared-boundary confirmation              ⏳

M1 — Data loads & validates
    Steps 4–5                                         ✅

M2 — Event table exists
    Steps 6–9                                         ✅

M2.5 — Performance refactor verified
    Polars/Parquet refactor                           ✅
    exact event parity                                ✅
    validation parity                                 ✅
    runtime/memory benchmark                          ✅ COMPLETE

M3 — Analytics
    Step 10 torque statistics                         ✅
    Step 11 torque distribution                       ✅
    Step 12 trend analysis                            ✅
    Step 13 anomaly detection                         ⏭ NEXT
    Step 14 head correlation                          ⏳

M4 — Agent tools
    Steps 15–17                                       ⏳

M5 — Evaluation/docs
    Steps 18–20                                       ⏳

M6 — Integration
    Steps 21–22                                       ⏳
```

---

# 125. Immediate next implementation task

Begin **Step 13 — Anomaly detection**.

Working-spec requirements:

```text
- threshold + statistical-deviation detection
- reason attached to each anomaly
- thresholds from config
- planted anomalies detected
- false-positive rate measured
- deterministic Polars implementation
- JSON-safe output
```

Relevant shared configuration:

```yaml
analytics:
  torque_expected_min: 1.5
  torque_expected_max: 2.5
  anomaly_sigma: 3.0
```



---

# 126. Step 13 — Anomaly detection

**Status:** COMPLETE  
**Regression status after Step 13:** full repository suite PASS  
**Milestone:** M3 analytics in progress  
**Next step:** Step 14 — Head correlation

Production implementation:

```text
src/analytics/anomaly_detection.py
```

Step 13 implements deterministic torque-anomaly detection over the clean Polars
event table.

Detection combines:

```text
1. configured engineering thresholds
2. statistical deviation from the observed torque distribution
```

Configuration is read from:

```yaml
analytics:
  torque_expected_min: 1.5
  torque_expected_max: 2.5
  anomaly_sigma: 3.0
```

Each flagged event carries one or more explicit reasons, including:

```text
below_expected_min
above_expected_max
statistical_deviation
```

The implementation also returns:

```text
sample_size
anomaly_count
anomaly_rate
mean
std
expected_min
expected_max
sigma
anomalies
```

Focused tests verify:

```text
below-threshold detection
above-threshold detection
boundary values are not falsely flagged
thresholds come from config
statistical-deviation detection
reason attached to every anomaly
multiple simultaneous reasons
planted anomaly detection
synthetic clean-data false-positive measurement
zero-variance behavior
status filtering
LazyFrame input
non-finite torque exclusion
empty input
JSON serialization
invalid configuration
missing event columns
```

The user confirmed the focused tests and the full repository regression suite
both passed.

Therefore Step 13 is accepted as complete.

---

# 127. Updated milestone status after Step 13

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B shared-boundary confirmation              ⏳

M1 — Data loads & validates
    Steps 4–5                                         ✅

M2 — Event table exists
    Steps 6–9                                         ✅

M2.5 — Performance refactor verified
    Polars/Parquet refactor                           ✅
    exact event parity                                ✅
    validation parity                                 ✅
    runtime/memory benchmark                          ✅ COMPLETE

M3 — Analytics
    Step 10 torque statistics                         ✅
    Step 11 torque distribution                       ✅
    Step 12 trend analysis                            ✅
    Step 13 anomaly detection                         ✅
    Step 14 head correlation                          ⏭ NEXT

M4 — Agent tools
    Steps 15–17                                       ⏳

M5 — Evaluation/docs
    Steps 18–20                                       ⏳

M6 — Integration
    Steps 21–22                                       ⏳
```

---

# 128. Immediate next implementation task

Begin **Step 14 — Head correlation**.

Working-spec requirement:

```text
head_correlation(events, head_a, head_b) -> dict
```

The comparison must include interpretable head-to-head behavior such as torque
correlation and success-rate difference, handle different event counts
gracefully, and be verified on deliberately similar and deliberately dissimilar
synthetic heads.



---

# 129. Step 14 — Head correlation

**Status:** COMPLETE  
**Full project regression after Step 14:** 225 / 225 PASS  
**Milestone:** M3 analytics COMPLETE  
**Next milestone:** M4 — Agent tools  
**Next step:** Step 15 — Tool schemas

Production implementation:

```text
src/analytics/head_correlation.py
```

Step 14 adds deterministic head-to-head comparison over the clean Polars event
table.

The comparison includes:

```text
- independent event counts
- independent torque sample counts
- independent mean torque
- success rate per head
- success-rate difference
- success-rate difference in percentage points
- Pearson torque correlation on shared timestamps
- deterministic interpretation of the correlation
```

The implementation handles unequal event counts without row-position pairing.
Torque correlation is computed only over timestamps shared by the two requested
heads.

No Load events are excluded from the success-rate denominator.

Focused tests verify:

```text
deliberately similar heads -> strong positive correlation
deliberately dissimilar heads -> strong negative correlation
unequal event counts
success-rate difference
No Load exclusion
no shared timestamps
constant-torque correlation edge case
missing head behavior
LazyFrame input
JSON serialization
invalid head IDs
missing required columns
```

The complete repository regression suite passed:

```text
225 passed
```

Therefore Step 14 is accepted as complete.

---

# 130. Milestone M3 — Analytics COMPLETE

Steps completed:

```text
Step 10 — Torque statistics       ✅
Step 11 — Torque distribution     ✅
Step 12 — Trend analysis          ✅
Step 13 — Anomaly detection       ✅
Step 14 — Head correlation        ✅
```

The deterministic analytics layer now operates entirely on the clean event-table
boundary and is independent of agent orchestration.

The current callable analytics are:

```text
torque_stats(...)
torque_distribution(...)
torque_trend(...)
detect_torque_anomalies(...)
head_correlation(...)
```

All return JSON-safe plain Python structures suitable for exposure through an
agent tool interface.

---

# 131. Updated milestone status

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B shared-boundary confirmation              ⏳

M1 — Data loads & validates
    Steps 4–5                                         ✅

M2 — Event table exists
    Steps 6–9                                         ✅

M2.5 — Performance refactor verified
    Polars/Parquet refactor                           ✅
    exact event parity                                ✅
    validation parity                                 ✅
    runtime/memory benchmark                          ✅ COMPLETE

M3 — Analytics
    Steps 10–14                                       ✅ COMPLETE

M4 — Agent tools
    Step 15 tool schemas                              ⏭ NEXT
    Step 16 deterministic tool execution              ⏳
    Step 17 tool-interface integration tests           ⏳

M5 — Evaluation/docs
    Steps 18–20                                       ⏳

M6 — Integration
    Steps 21–22                                       ⏳
```

---

# 132. Immediate next implementation task

Begin **Step 15 — Tool schemas**.

Goal:

```text
Expose the deterministic analytics capabilities as stable, provider-neutral
tool definitions without coupling Person A's code to any specific LLM SDK.
```

Step 15 should define tool names, descriptions, argument schemas, and a central
registry for the analytics functions that will be executed in Step 16.



---

# 133. Step 15 — Tool schemas

**Status:** COMPLETE  
**Full project regression after Step 15:** 245 / 245 PASS  
**Milestone:** M4 agent tools in progress  
**Next step:** Step 16 — Deterministic tool execution

Production implementation:

```text
src/agent/tool_schemas.py
```

Step 15 defines a provider-neutral tool interface for the deterministic analytics
layer.

Registered tools:

```text
torque_stats
torque_distribution
torque_trend
detect_torque_anomalies
head_correlation
```

The schemas expose only user/model-controlled analytical arguments. Runtime
internals such as the event table, LazyFrame, config object, CSV paths, Parquet
paths, and configured drift window are intentionally not exposed to the model.

The tool registry provides:

```text
TOOL_INTERFACE_VERSION
TOOL_SCHEMAS
TOOL_SCHEMA_BY_NAME
list_tool_schemas()
get_tool_schema()
```

Focused tests verify:

```text
exact registered tool set
unique names
basic schema structure
JSON serialization
no runtime-internal arguments
status-filter schemas
positive histogram bins
required head-correlation arguments
unknown-tool rejection
invalid tool-name types
defensive copies
```

The complete repository regression suite passed:

```text
245 passed
```

Therefore Step 15 is accepted as complete.

---

# 134. Updated milestone status after Step 15

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B shared-boundary confirmation              ⏳

M1 — Data loads & validates
    Steps 4–5                                         ✅

M2 — Event table exists
    Steps 6–9                                         ✅

M2.5 — Performance refactor verified
    Polars/Parquet refactor                           ✅ COMPLETE

M3 — Analytics
    Steps 10–14                                       ✅ COMPLETE

M4 — Agent tools
    Step 15 tool schemas                              ✅
    Step 16 deterministic tool execution              ⏭ NEXT
    Step 17 tool-interface integration tests           ⏳

M5 — Evaluation/docs
    Steps 18–20                                       ⏳

M6 — Integration
    Steps 21–22                                       ⏳
```

---

# 135. Immediate next implementation task

Begin **Step 16 — Deterministic tool execution**.

Goal:

```text
Create a single controlled dispatcher that binds model-visible tool arguments
to the already-tested analytics functions while injecting runtime-only context
(events and config) internally.

No eval, exec, arbitrary imports, or arbitrary function execution.
```



---

# 136. Step 16 — Deterministic tool execution

**Status:** COMPLETE  
**Full project regression after Step 16:** 267 / 267 PASS  
**Milestone:** M4 agent tools in progress  
**Next step:** Step 17 — Tool-interface integration tests

Production implementation:

```text
src/agent/tool_executor.py
```

Step 16 adds the controlled execution boundary between the model-visible tool
interface and the trusted deterministic analytics layer.

The dispatcher:

```text
execute_tool(tool_name, arguments, events, config)
```

uses a fixed executor registry and internally injects runtime-only context.

Supported tools:

```text
torque_stats
torque_distribution
torque_trend
detect_torque_anomalies
head_correlation
```

Security and architecture properties verified:

```text
- fixed tool-name -> executor mapping
- no eval()
- no exec()
- no dynamic imports
- no arbitrary function execution
- model cannot supply or replace events
- model cannot supply or replace config
- unexpected arguments rejected
- required arguments enforced
- analytics validation errors propagate
- DataFrame and LazyFrame inputs supported
- returned results remain JSON serializable
- repeated execution is deterministic
```

The executor registry was also verified to match the Step 15 schema registry.

The complete repository regression suite passed:

```text
267 passed
```

Therefore Step 16 is accepted as complete.

---

# 137. Updated milestone status after Step 16

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B shared-boundary confirmation              ⏳

M1 — Data loads & validates
    Steps 4–5                                         ✅

M2 — Event table exists
    Steps 6–9                                         ✅

M2.5 — Performance refactor verified
    Polars/Parquet refactor                           ✅ COMPLETE

M3 — Analytics
    Steps 10–14                                       ✅ COMPLETE

M4 — Agent tools
    Step 15 tool schemas                              ✅
    Step 16 deterministic tool execution              ✅
    Step 17 tool-interface integration tests           ⏭ NEXT

M5 — Evaluation/docs
    Steps 18–20                                       ⏳

M6 — Integration
    Steps 21–22                                       ⏳
```

---

# 138. Immediate next implementation task

Begin **Step 17 — Tool-interface integration tests**.

Goal:

```text
Prove the complete Person-A tool boundary works end-to-end:

tool schema -> model-style tool call -> controlled executor ->
deterministic analytics -> JSON-safe result
```

Step 17 should not add an LLM SDK dependency. It verifies the provider-neutral
contract that Person B can call from the orchestration layer.



---

# 139. Tool-interface integration dry run

**Status:** PASS  
**Full project regression:** 281 / 281 PASS

The provider-neutral integration suite now verifies the complete local boundary:

```text
tool schema
    ↓
model-style tool call
    ↓
controlled executor
    ↓
deterministic analytics
    ↓
JSON-safe result
```

Verified locally:

```text
all published tools execute end-to-end
schema/executor argument contracts agree
runtime config is injected internally
runtime event table is injected internally
model attempts to override config/events are rejected
unknown tools are rejected
required tool arguments are enforced
LazyFrame event boundary works
tool results survive JSON round-trip
repeated identical calls are deterministic
```

The full repository regression suite passed:

```text
281 passed
```

---

# 140. Important alignment with the original Person-A working spec

The local executor and integration tests are valuable extra infrastructure, but
they do not by themselves satisfy every original M4 acceptance criterion.

The original Step 16 is:

```text
Diagnostic prompts
```

and requires diagnostic query families such as:

```text
"which head behaves differently"
"why is head 4 failing more"
"compare head 1 and head 2"
```

with sensible tool sequences, tool-grounded explanations, and robustness to
rephrasing.

The original Step 17 is:

```text
Verify tool selection
```

and is tagged:

```text
[CONSUMES B]
```

because it requires Person B's real agent loop.

Its audit requires approximately 10 real questions to be run through the agent,
checking that:

```text
the right tool(s) are selected
wrong selections are corrected through tool descriptions
the agent does not fabricate numbers that should come from tools
```

Therefore:

```text
local tool-interface integration tests   ✅ PASS
original Step 16 diagnostic prompts      ⏳ PENDING
original Step 17 real agent selection    ⏳ PENDING PERSON B
M4 — Agent can use my tools              ⏳ NOT FORMALLY CLOSED YET
```

The previously added controlled executor remains retained as an additional safety
and integration layer; it does not replace the original prompt/tool-selection
evaluation requirements.

---

# 141. Corrected milestone status

```text
M0 — Contract / shared interface
    Original contract written                         ✅
    Polars/Parquet architecture amendment written     ✅
    Person B shared-boundary confirmation              ⏳

M1 — Data loads & validates
    Steps 4–5                                         ✅

M2 — Event table exists
    Steps 6–9                                         ✅

M2.5 — Performance refactor verified
    Polars/Parquet refactor                           ✅ COMPLETE

M3 — Analytics
    Steps 10–14                                       ✅ COMPLETE

M4 — Agent can use my tools
    Step 15 tool schemas                              ✅
    Extra controlled executor                         ✅
    Extra local integration dry run                   ✅
    Original Step 16 diagnostic prompts               ⏭ NEXT
    Original Step 17 real agent tool-selection test   ⏳ PERSON B REQUIRED

M5 — Proven & documented
    Step 18 anomaly ground-truth evaluation           ⏳
    Step 19 data schema & methods documentation        ⏳
    Step 20 confidence & limits language               ⏳

M6 — Integrated
    Steps 21–22                                       ⏳
```

---

# 142. Immediate next task

Complete the original **Step 16 — Diagnostic prompts** locally.

After that:

```text
if Person B's agent loop is ready:
    run original Step 17 and close M4

if Person B's agent loop is not ready:
    keep Step 17 explicitly pending and build the Step 18 evaluation harness
    using a labelled stand-in dataset until Person B's planted-fault data arrives
```



## Integration checkpoint — verified separate baselines

Branch: `integration/person-a-person-b`

### Verified results
- Person A: 287 passed in 0.57 seconds after installing B's dependencies.
- Person B: 254 passed, 3 skipped in 2.30 seconds.
- Person A working tree was clean before this documentation update.
- B's dependencies were installed with A's requirements as constraints.
- Installing llama3.2:3b resolved B's live model-availability test.
- Model availability does not establish correct natural-language tool selection.

### Skipped tests
- Two adapter tests expect a sibling folder named person-a.
  Our actual Person A folder is named arol-telemetry-ai.
- One benchmark test expects the real telemetry archive.
- Real-data A-to-B integration is therefore still unverified.

### Integration progress
- Phase 0: source inspection complete for both current ZIPs.
- Phase 1: separate baselines and integration branch established.
- Phase 2: adapter contract verification is next.
- Phases 3–18: pending.

### Open contract issues
- Adapter re-decoding can change Person A's decoded status fields.
- Counter increments greater than one need an agreed policy.
- A's head comparison and B's KPIs use different success denominators
  for some statuses beyond the common 0, 2 and 65.
- Tool arguments, trusted configuration and report handling need integration.

Next action: verify A's actual event output through B's adapter with a
small controlled fixture, recording row preservation and semantic differences.
No analytics or event semantics have been changed.


## Integration checkpoint — adapter characterization verified

### Implementation
Added tests/test_person_b_adapter_contract.py.

The fixture builds 16 events using Person A's actual event builder:
two heads, eight status codes, and exact +1 counter increments.

run_person_b_adapter executes Person B's actual adapter in a separate
Python process and exchanges temporary Parquet files. This avoids the
two repositories' conflicting src package names.

### Verified results
- Focused adapter tests: 4 passed in 0.46 seconds; no skips.
- Full Person A suite: 291 passed in 0.92 seconds.
- redecode=False preserves all eight Person A columns and their types.
- The default adapter changes cap_present for statuses 3 and 64,
  and reject_signal for unknown status 999, while reporting disagreements.
- Duplicate event rows are preserved.
- Empty input produces a conforming empty twelve-column table.

### Status and limitations
Phase 2 characterization is complete for the controlled fixture.
Semantic acceptance remains pending; these tests describe existing behaviour.
No production analytics, adapter logic or event semantics were changed.
This is not a real-telemetry or agent-tool-selection evaluation.
These tests require Person B's repository; they skip if it is unavailable.

Next: document the counter-jump policy and quantify jumps on real telemetry.
Status decoding and success-rate denominator differences remain open.

## Integration checkpoint — full counter audit measured

Completed the full CSV counter diagnostic. Whole-number values were validated before integer conversion. Comparisons included file boundaries.

```json
{
  "machine_id": "MCC777eda3db57348ef8a3113a642ae74db",
  "files": 89,
  "heads": 36,
  "input_rows": 7623968,
  "ts_min": "2026-01-31T16:00:00",
  "ts_max": "2026-04-30T16:59:59",
  "exact_plus_one": 54722936,
  "holds": 219329712,
  "jump_rows": 408076,
  "counter_units_in_jumps": 156189350,
  "extra_units_beyond_one_per_jump": 155781274,
  "decreases": 2088,
  "positive_delta_rows": 55131012,
  "positive_counter_units": 210912286,
  "timestamp_gaps_over_1s": 87,
  "boundary_exact_plus_one": 667,
  "boundary_jump_rows": 0,
  "boundary_counter_units_in_jumps": 0,
  "boundary_decreases": 0
}
```

Interpretation and limits:
- Production event detection remains exactly +1.
- Jump rows and counter units within jumps are distinct measurements.
- Positive counter units are not verified individual closure events.
- Causes of counter decreases remain undetermined.
- The fixed eight-per-machine-day warning does not describe this dataset.
- Independent per-file processing omits the 667 exact +1 transitions measured across file boundaries.
- Timestamps come from CSV contents; no timezone conversion was made.
- No production code or event semantics changed.
- Detailed results: data/counter_jump_audit.json.

Status: measurement complete; interpretation and integration policy pending.

Next action: inspect large jumps and decreases before deciding how to represent and report counter discontinuities.

## Integration decision — preserve exact +1 event semantics

Evidence:
- The full 89-file counter audit completed successfully.
- Inspection of H17 on the file dated 2026-03-23 showed decreases
  from large counter values to zero.
- One observed decrease was 68928 to 0.
- The largest inspected positive jump was 0 to 71271 in one second.
- These observations are consistent with counter-reading discontinuities.
  Their underlying cause has not been established.
- Findings from this selected head/day do not classify every jump
  in the full dataset.

Policy for the first integration:
- Person A's exact +1 rule remains authoritative for observed events.
- Preserve existing event timestamps, torque, status and decoded fields.
- Do not interpolate, forward-fill zeros, or reconstruct individual
  closures from jumps.
- Keep jump/decrease diagnostics separate from event-based analytics.
- Report event counts as observed exact +1 closures, not guaranteed
  total physical production.
- Consume Person A events through the adapter with redecode=False.
- Adapter count_delta=1 and inferred=False describe these input events;
  they do not establish completeness of the underlying telemetry.
- Do not use Person B's raw positive-delta weighted throughput path
  for the first integration without correcting discontinuity handling.

Remaining implementation work:
- Apply this policy explicitly in the integration path.
- Replace the unconditional eight-per-machine-day warning.
- Resolve KPI denominator and decoding differences explicitly.
- Retain file-boundary comparisons when building events from multiple files.
- Integrate and test the first torque_stats tool through a thin wrapper.

Status:
Counter audit and initial integration policy documented.
Production integration changes remain pending.

## Integration checkpoint — registered torque_stats verified

Implemented:
- Added Person B's shared envelope and registry infrastructure.
- Extended the registry vocabulary with status_filter:
  null, "successful", or an integer status code.
- Added src/analytics/registered_torque.py.
- The wrapper delegates calculations to Person A's existing torque_stats.
- Results retain the original statistics dictionary inside B's envelope.
- Metadata includes finite sample size, units, applied filters,
  contributing observation timestamps, and execution timing.

Verified locally:
- Focused wrapper tests: 17 passed in 0.10s.
- Full project regression: 308 passed in 1.18s.
- Tests cover calculation parity, finite values, sample standard deviation,
  status selection, empty input, metadata, invalid arguments,
  missing columns, JSON serialization, and unchanged input data.

Scope:
- Existing analytics and ingestion code remain unchanged.
- This verifies registry dispatch directly.
- Planner routing, orchestrator wiring, report rendering, and real-data
  end-to-end execution remain pending.
- The four adapter characterization tests still require the sibling
  Person B checkout.

Next action:
Connect torque_stats to deterministic planner routing and report output,
then verify the complete request-to-result path.

## Integration checkpoint — torque routing and reports verified

Implemented:
- Imported Person B's planner, report, trace and time utilities.
- Added deterministic routing for aggregate torque statistics,
  optionally restricted to successful closures or an integer status code.
- Unsupported torque requests, including head/date filters, request
  clarification rather than silently broadening the analysis.
- Added a torque report template using registered tool results.
- Reports handle empty samples and undefined single-observation standard
  deviation explicitly.
- Small-sample notices remain visible alongside tool notes.
- Torque-only reports omit unrelated rate-denominator statements.
- Torque summaries do not claim machine stability or engineering compliance.

Verification:
- Added 15 planner tests and 7 report integration tests.
- Combined torque checks: 39 passed in 0.09s.
- Full project regression: 330 passed in 1.19s.
- Controlled-data tests cover question -> plan -> registry dispatch ->
  existing analytics -> report assembly, plus tool-call tracing.

Scope and limitations:
- Tests compose the components directly.
- Production orchestrator and data-source integration remain pending.
- No live LLM routing or real-data report was verified in this checkpoint.
- Existing analytics calculations and ingestion semantics remain unchanged.
- Non-torque planner routes are preserved, but their tools are not yet
  integrated into this branch.

Next action:
Connect the production orchestration path to Person A's event data,
preserve requested scope, and verify a torque report end to end.

## Integration checkpoint — event source and orchestrator verified

Implemented:
- Added PersonASource for eight-column event Parquet produced by A's pipeline.
- Validates input columns and dtypes before adaptation.
- Resolves relative event paths from the repository root.
- Preserves A's decoded fields through explicit redecode=False.
- Changed the integrated adapter's default to preserve decoding.
- Replaced the fixed eight-per-machine-day warning with an explicit
  statement that production completeness is not measured here.
- Connected Person B's orchestrator to the registered torque tool.
- Removed retries that discard requested filters.
- Requires explicit pool selection when multiple pools are configured.
- Supports Markdown report and JSON trace delivery.
- Updated report failure guidance to preserve requested scope.

Verification:
- Added 9 event-source tests and 8 orchestrator tests.
- Focused checks: 17 passed in 0.14s.
- Full project regression: 347 passed in 1.01s.
- Tests use A's actual event builder and Parquet writer with controlled
  telemetry containing exact +1 increments, larger jumps, and decreases.
- Verified decoding preservation, duplicate preservation, empty input,
  missing files, invalid input schema, pool selection, report delivery,
  and failures without filter relaxation.

Scope and limitations:
- Actual orchestration is verified on controlled telemetry.
- Real telemetry execution and live LLM routing remain unverified.
- Filter preservation is verified for deterministic routing and dispatch;
  the imported LLM planner still needs separate review.
- Only torque_stats is currently connected as an analytics tool.
- Raw ingestion and existing analytics calculations remain unchanged.

Next action:
Run one real telemetry file through A's event builder, event Parquet,
PersonASource, deterministic planner, orchestrator, report and trace.
Compare the wrapped statistics against a direct torque_stats calculation.

## Integration checkpoint — first real-data torque report verified

Completed the first deterministic real-data vertical slice:

CSV -> Person A event builder -> event Parquet -> PersonASource ->
RulePlanner -> registry -> torque_stats -> report and trace.

Evidence:
- Input: telemetry_MCC777eda3db57348ef8a3113a642ae74db_2026-02-01.csv
- Input SHA-256: 679622a73fd54a051fc0507ed5faff75cc1575fb0b5261f517d9314840a1911e
- Tested code commit: ec766753c06d7c4291af7a9a96e25c284d49cd75
- Raw rows: 86,399
- Raw timestamp range: 2026-01-31T16:00:00 to 2026-02-01T15:59:59
- Observed exact +1 events: 765,703
- Event count agrees with the independent counter audit.
- All eight original event fields were preserved.
- Query: Average torque for successful closures
- Planner: rules; tool calls: 1; outcome: ok.
- Finite successful-closure torque observations: 427,772
- Mean torque: 1.996996423328315 Nm.
- Minimum / maximum: 0.0 / 2.317 Nm.
- Sample standard deviation: 0.035846607419704545 Nm.
- Direct and reported statistics matched exactly in this run.
- Verification permits floating-point relative/absolute tolerance of 1e-12.

Artifacts:
- Portable verification evidence: benchmarks/integration/torque_stats_real_2026-02-01.json
- Report and trace remain local under data/integration_smoke.
- Last full regression: 347 passed in 1.01s.

Limits:
- Verified one supplied CSV file, not the complete 89-file pool.
- First observation is a counter baseline; no preceding-file boundary tested.
- Filename date is not assumed to be a calendar-day window.
- Source timezone remains unconfirmed; no timezone conversion was applied.
- Zero torque was retained by the existing finite-value calculation.
  Its physical interpretation requires separate investigation.
- Live LLM routing and the other analytics tools remain pending.

Status:
First deterministic torque_stats vertical slice verified on real telemetry.

Next action:
Extend the tool's supported head, machine and time filters with explicit
scope-preservation tests, then expand routing and the remaining tools.

## Integration checkpoint — scoped torque queries verified

Implemented:
- Added shared event filtering for head_id, machine_id, start and end.
- Registered torque_stats accepts these filters alongside status_filter.
- Start is inclusive; end is exclusive.
- Tool-level head filtering accepts one head or a list of heads.
- Metadata describes the finite observations used after all filters.
- Blank, null-like and incorrectly typed scope arguments return errors
  instead of silently becoming omitted filters.
- Valid filters with no matching events return empty statistics.
- Timezone-aware bounds and invalid time ranges are rejected.

Deterministic routing:
- Supports a single named head, an exact machine identifier,
  successful closures or a numeric status, and explicit dates/ranges.
- Head 5 maps to H05; machine identifier case is preserved.
- Calendar dates select midnight to the following midnight using
  timestamps as stored, without timezone conversion.
- Explicit ranges use "from ... until ..." with an exclusive end.
- Conflicting filters, unsupported qualifiers and relative dates
  request clarification without executing tools.

Verification:
- Added 21 scope tests and 16 scoped-planner tests.
- Updated earlier tests whose head/date requests are now supported.
- Full regression: 384 passed in 1.04s.
- End-to-end fixtures verify exclusion of other heads, machines,
  dates and statuses, including exact time boundaries.
- Unknown heads return empty results rather than broader statistics.
- Existing analytics calculations remain unchanged.

Limits:
- Scoped routing is verified on controlled data.
- The earlier real-data verification covered successful closures
  across the supplied file, without head or time restrictions.
- Live LLM routing, multi-head natural-language routing, relative dates
  and the remaining analytics tools are still pending.

Next action:
Verify a scoped head query against the saved real event Parquet,
comparing its result with an explicitly filtered direct calculation.

## Integration checkpoint — scoped real-data torque verified

- Verified clean commit: b4ddff87c360e5e25b0533168aebbf53fd09ad97.
- Query: Average torque for head 5 for machine MCC777eda3db57348ef8a3113a642ae74db from 2026-02-01T00:00:00 until 2026-02-01T12:00:00 for successful closures
- Source events: 765,703.
- Selected successful events / finite torque samples: 7,575 / 7,575.
- Mean torque: 1.9957486468646866 Nm.
- Minimum / maximum torque: 0.0 / 2.173 Nm.
- Sample standard deviation: 0.03983402226443763 Nm.
- Direct and reported results agree within relative/absolute tolerance 1e-12.
  The last floating-point digits of standard deviation differ; equality is not claimed.
- All five requested parameters reached the tool unchanged.
- One deterministic tool call; no live LLM routing tested.
- Evidence, including source-code hashes: benchmarks/integration/torque_stats_scoped_real_2026-02-01.json.
- Reports and trace remain under data/integration_smoke.
- Last completed regression before the new batch: 384 passed in 1.04s.

## Integration batch — four analytics tools added; tests pending

Prepared wrappers for torque_distribution, torque_trend,
detect_torque_anomalies and head_correlation, using the existing A functions.
Added deterministic report templates and application-owned configuration
dispatch. Config, thresholds and rolling windows are not model parameters.
Unknown arguments are rejected before placeholder coercion can remove them.
Correlation requires one machine and rejects duplicate head/timestamp
pairings; it does not deduplicate or change A's underlying calculation.
A's non-No-Load success denominator is retained and explicitly distinguished
from B's cap-present KPI denominator; final denominator alignment is pending.
Trend direction remains A's numerical-epsilon classification, not a statement
of engineering or statistical significance. Selected trend/anomaly data are
pooled, and no pre-window history is added to a scoped trend calculation.

New tests cover parity with all four existing functions, scope, empty input,
configuration isolation, invalid arguments, ambiguous correlations, reports,
and trusted configuration passing through the orchestrator.

Status: implementation installed; run pytest before marking this batch verified.
Natural-language routing for these four tools is the next task. The existing
scoped torque_stats route remains active. No merge or live LLM validation done.

## Integration checkpoint — all five analytics wrappers verified

This checkpoint supersedes the preceding batch's verification-pending status.

Verified:
- Registered wrappers for torque_distribution, torque_trend,
  detect_torque_anomalies and head_correlation.
- All five analytics tools now have wrappers and report templates.
- Existing Person A analytics functions remain unchanged.
- Configuration is supplied by trusted runtime dispatch and isolated
  between calls; tool arguments cannot override runtime settings.
- Unknown arguments are rejected before placeholder coercion.
- Head correlation rejects cross-machine and duplicate-timestamp pairings.
- A's success denominator is preserved and explicitly distinguished
  from B's cap-present KPI denominator.
- Reports describe results without asserting machine health or causation.

Tests:
- Added 35 tests covering calculation parity, scope, empty data,
  configuration isolation, invalid arguments, correlation safeguards,
  report output and orchestrator configuration passing.
- Full regression: 419 passed in 1.12s.

Real-data evidence:
- The preceding scoped torque_stats verification is now recorded in
  benchmarks/integration/torque_stats_scoped_real_2026-02-01.json.

Remaining:
- Natural-language routing for the four newly registered tools.
- Real-data verification of those tools.
- Live LLM routing and broader diagnostic evaluation.
- Final agreement on KPI denominators and other shared assumptions.

Next action:
Add deterministic question routes for distributions, trends, anomalies
and head comparisons while preserving requested scope.

## Integration batch — deterministic routing for five analytics tools

Implemented complete-query routing for torque statistics, distribution,
trend, anomalies, and two-head comparison. Scope is preserved; unsupported
clauses, conflicting filters, timezone-aware bounds, relative dates and
configuration overrides request clarification before any tool call.
Comparison accepts only machine/time scope; status or extra-head scope is
not silently discarded. Histogram bins must be positive integers.

Added controlled tests for question routing and the actual event-Parquet ->
source -> RulePlanner -> orchestrator -> existing analytics -> report path,
with independently selected event scopes and direct calculation parity.
Old negative cases whose analyses are now supported retain negative-scope
coverage through an explicit unsupported exclusion. Migrated cases:
[
  {
    "file": "tests/test_torque_planner.py",
    "old": "Is torque drifting?",
    "new": "Is torque drifting excluding head 3"
  },
  {
    "file": "tests/test_torque_planner.py",
    "old": "Compare torque between H01 and H02",
    "new": "Compare torque between H01 and H02 excluding head 3"
  },
  {
    "file": "tests/test_torque_planner.py",
    "old": "Show torque distribution",
    "new": "Show torque distribution excluding head 3"
  }
]

Previous verified regression: 419 passed in 1.12s.
This routing batch: installed, pytest results pending. No live LLM or new
real-data execution is claimed. Core analytics, event semantics, and other
domain routes are unchanged. KPI denominator alignment remains pending.

## Integration checkpoint — five-tool question routing verified

- Full project test suite: 472 passed in 1.13s.
- Command: .venv/bin/python -m pytest tests -q
- Added 53 routing and orchestration tests.
- Deterministic questions now reach all five analytics tools.
- Tests verify scope preservation, direct-calculation parity,
  report delivery, and clarification without tool calls.
- Core analytics and exact +1 event semantics remain unchanged.
- Running pytest without an explicit tests directory collected installer
  backups and caused a module-name collision. Use pytest tests -q.
- Live LLM routing and real-data execution of the four new routes
  remain unverified.

Next action:
Verify the four new routes against real event data and save comparison
evidence, reports, and traces.

## Integration checkpoint — four additional real-data routes verified

- Verified source commit: 7e5a42a82e27e49f55da607ae3d4f6a26df01edd.
- Deterministic planner; all four routes passed complete nested-result parity checks.
- Float tolerance: relative/absolute 1e-12; counts and labels compared exactly.
- Original event fields preserved; requested parameters preserved; one call per route.
- torque_distribution: n=7,575; result parity verified.
- torque_trend: n=7,575; result parity verified.
- detect_torque_anomalies: n=7,575; result parity verified.
- head_correlation: n=12,178; result parity verified.
- Portable evidence: benchmarks/integration/analytics_routes_real_2026-02-01.json.
- Detailed comparisons, reports and traces: data/integration_smoke/analytics-20260923-184831-981277.
- Last full project regression: 472 passed in 1.13s (before this evidence run).

Scope and limits:
One previously built event file; H05 successful events for three tools; H05/H06 all statuses for comparison; specified machine; start inclusive/end exclusive; timestamps as stored.
- No live LLM routing tested.
- No preceding-file boundary tested.
- Only observed exact +1 events; total production completeness is not measured.
- Configured limits and numeric trend direction do not establish machine health or root cause.
- Head comparison retains Person A's non-No-Load success denominator; KPI alignment remains pending.

Next action:
Review live LLM scope preservation and unsupported-argument handling before enabling model routing.

## Integration batch — strict LLM proposal validation

Previous verified regression: 472 passed in 1.13s. All five deterministic
analytics routes have real-data parity evidence (torque_stats earlier;
four additional routes at commit 7e5a42a82e27e49f55da607ae3d4f6a26df01edd).

LLM proposals now require one registered tool, canonical argument names,
valid types, and an exact match to the independently parsed requested
analysis and scope. No argument or bound is dropped, no head-detail call
is prepended, and invalid proposals stop before data loading or dispatch.
Free-form model prose cannot supply report goals or findings.
Transport/response-decoding failure can use the complete verified rules
plan, with the existing fallback label in report/trace; disabling fallback
preserves exceptions. Invalid structured proposals do not trigger fallback.
Model availability requires the configured tag, not a matching name prefix.

Deliberate scope boundary:
- LLM planning is gated by the current deterministic torque grammar.
- This does not demonstrate broader natural-language understanding.
- Unverified phrasing and other KPI domains request clarification before
  contacting the model. RulePlanner's other-domain behavior is unchanged.
- No core analytics, configured limits, event semantics, or live LLM default
  settings were changed. Runtime configuration stays application-owned.

Mocked tests cover all five tools, omitted/changed/extra scope, malformed
replies and JSON, duplicate JSON keys, exact model tags, configuration
arguments, trace labels, and accepted/rejected actual orchestration.
Status: installed; full regression pending. No live Ollama routing tested.
Next action: run pytest tests -q, then evaluate live model proposals with
fallback disabled and explicit accepted/rejected results.

## Integration checkpoint — LLM scope validation verified

- Full regression: 537 passed in 1.17s.
- Command: .venv/bin/python -m pytest tests -q
- Added 65 mocked LLM validation and orchestration tests.
- Accepted proposals preserve the verified analysis and complete scope.
- Invalid proposals request clarification without data loading or dispatch.
- Transport fallback preserves scope and is labelled in the trace.
- Model prose cannot supply report findings.
- LLM acceptance remains bounded by the deterministic torque grammar.
- Live model routing accuracy and latency remain unverified.

Next action:
Evaluate live Ollama proposals with fallback disabled, recording accepted,
rejected and failed requests separately.

## Integration measurement — live LLM routing 20260923-170337-075169

- Source commit: fd58df79670490e5ae6479e3423074deb2a643c5.
- Model: llama3.2:3b; fallback disabled; temperature 0; seed 42.
- Completed all planned cases: True.
- Supported questions attempted: 10 / 10.
- Exact accepted: 1; rejected proposals: 9; request errors: 0.
- Invariant failures across all cases: 0.
- Exact acceptance / attempted supported cases: 0.1.
- Separate pre-inference scope-gate outcomes: {'gate_blocked': 4}.
- Latency (seconds, including load/errors): {'median': 0.85145, 'maximum': 1.9573}.
- Evidence: benchmarks/integration/live_llm_routing_20260923-170337-075169.json.
- Full replies and offered schemas: data/integration_smoke/live-llm-20260923-170337-075169.
- Last full regression: 537 passed in 1.17s; this measurement does not change source.

Limits:
- Small hand-authored integration sample, not a held-out language benchmark.
- One attempt per question; repeatability and statistical confidence are not measured.
- Model acceptance is limited to the verified deterministic grammar.
- Scope-gate blocks happen before inference and are excluded from model acceptance rate.
- Requests that error or are rejected remain in the supported-case denominator.
- Planning only: no analytics execution, report delivery, or real-data LLM end-to-end claim.

Next action:
Review rejected/error cases before deciding whether to adjust the prompt/model or proceed to a live orchestration smoke test. Keep scope validation unchanged.

## Integration measurement — live LLM routing 20260923-170639-310633

- Source commit: 0c283b432e5cc7bb685666c3cf49684196aa9948.
- Model: qwen2.5-coder:14b; fallback disabled; temperature 0; seed 42.
- Completed all planned cases: True.
- Supported questions attempted: 10 / 10.
- Exact accepted: 0; rejected proposals: 10; request errors: 0.
- Invariant failures across all cases: 0.
- Exact acceptance / attempted supported cases: 0.0.
- Separate pre-inference scope-gate outcomes: {'gate_blocked': 4}.
- Latency (seconds, including load/errors): {'median': 4.3464, 'maximum': 7.9462}.
- Evidence: benchmarks/integration/live_llm_routing_20260923-170639-310633.json.
- Full replies and offered schemas: data/integration_smoke/live-llm-20260923-170639-310633.
- Last full regression: 537 passed in 1.17s; this measurement does not change source.

Limits:
- Small hand-authored integration sample, not a held-out language benchmark.
- One attempt per question; repeatability and statistical confidence are not measured.
- Model acceptance is limited to the verified deterministic grammar.
- Scope-gate blocks happen before inference and are excluded from model acceptance rate.
- Requests that error or are rejected remain in the supported-case denominator.
- Planning only: no analytics execution, report delivery, or real-data LLM end-to-end claim.

Next action:
Review rejected/error cases before deciding whether to adjust the prompt/model or proceed to a live orchestration smoke test. Keep scope validation unchanged.
