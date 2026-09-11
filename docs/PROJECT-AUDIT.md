# AROL Telemetry AI — Project Audit & Implementation Notes

**Project:** Agentic AI for Telemetry Analysis on AROL Capping Machines  
**Role covered here:** Person A — data ingestion, validation, event-table preparation, and later deterministic analytics  
**Current implementation status:** Step 4 complete; Step 5 implementation and tests complete; Step 6 not started  
**Primary source documents:** `docs/contract.md` and `docs/PERSON-A-WORKING-SPEC.md`

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

The original macOS Python was:

```text
Python 3.9.6
/usr/bin/python3
```

We deliberately did **not** build the project on that system Python.

Homebrew was installed on Apple Silicon (`arm64`), and Python 3.12 was installed.

The project now uses:

```text
Python 3.12.14
```

A virtual environment was created:

```text
.venv/
```

and activated with:

```bash
source .venv/bin/activate
```

Installed packages:

- `pandas`
- `pyyaml`
- `pytest`
- `pyarrow`

Their purpose:

| Package | Purpose |
|---|---|
| `pandas` | DataFrames and CSV/JSON/Parquet loading |
| `pyyaml` | Reading `config.yaml` |
| `pytest` | Automated tests |
| `pyarrow` | Parquet support |

The environment dependencies are recorded in:

```text
requirements.txt
```

---

# 5. Configuration

Current configuration structure:

```yaml
data:
  pools:
    sample:
      - data/sample.csv

  n_heads: null

  units:
    AppTorque: Nm
```

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

# 6. Step 4 — Loader

**Status:** COMPLETE  
**Tests:** 12/12 passed  
**Milestone contribution:** M1 — data loads

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

# 15. Step 5 — Validation

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

**Step 5 implementation and audit tests: COMPLETE**

This reaches:

```text
M1 — Data loads & validates
```

---

# 26. Current project status

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

# 42. Updated project status

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

# 53. Current project status

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

# 65. Current data pipeline

```text
config.yaml
      ↓
load_pool()
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

---

# 66. Current project status

```text
M1 — Data loads & validates
    Step 4 ✅
    Step 5 ✅

M2 — Event table exists
    Step 6 ✅
    Step 7 ✅
    Step 8 ✅
    Step 9 ✅

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
Step 9 of 22 complete
Next: Step 10
```

---

# 67. Git checkpoint after Step 9

```bash
git status
git add .
git commit -m "Build final clean event table"
git push
```

Then verify:

```bash
git status
```

Expected:

```text
nothing to commit, working tree clean
```

---

# 68. Audit snapshot after Step 9

**Python:** 3.12.14  
**Loader:** complete  
**Validation:** complete  
**Closure detection:** complete  
**Event assembly:** complete  
**Capping speed:** complete  
**Final event table:** complete  
**Loader tests:** 12/12 pass  
**Validation tests:** 16/16 pass  
**Closure tests:** 7/7 pass  
**Event-assembly tests:** 19/19 pass  
**Capping-speed tests:** 7/7 pass  
**Event-table tests:** 9/9 pass  
**Total confirmed tests:** 70/70 pass  
**Milestone M2:** COMPLETE  
**Next step:** Step 10 — analytics layer
