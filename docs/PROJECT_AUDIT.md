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

**Status:** NOT STARTED

This is the next step.

The working spec explicitly identifies Step 6 as the core reasoning problem and says it should be written by Person A rather than generated wholesale by an assistant.

The closure rule is:

```text
For one head:

compare current Count with previous Count

if current Count increased:
    a closure occurred
```

Based on the real-data contract:

- Count normally holds or increases by exactly +1
- torque/status for the closure are on the increment row
- files must already be treated as one continuous stream across day boundaries

---

# 28. Step 6 tests that must be written before implementation

Before writing closure-detection logic:

## Counter hold

```text
100
100
100
100
```

Expected: zero closures.

## +1 increment

```text
100
100
101
101
```

Expected: exactly one closure.

Torque/status must come from the `101` row.

## Counter jump > 1

```text
100
103
```

Not observed in inspected real data, but the implementation must have a deliberate documented policy.

## Counter reset/wrap

```text
1000
1001
5
6
```

The decrease must not become a spurious closure.

## First row

Has no previous row and must not cause an error or closure automatically.

## Torque/status attachment

On a transition:

```text
Count: 100 -> 101
AppTorque: 2.02
Status: 65
```

the detected closure must carry `2.02` and `65` from the increment row.

---

# 29. Important design boundaries

## Loader

Loads data only.

## Validator

Reports data-quality problems only.

## Closure detector

Detects closure occurrences only.

## Event assembly

Later Step 7 converts detected closures into the agreed event-table fields and performs status decoding.

Keeping these stages separate makes testing and debugging easier.

---

# 30. Current function map

```text
src/ingestion/loader.py

LoaderError
load_config(config_path)
get_pool_files(config, pool_name)
load_file(file_path)
load_pool(pool_name, config_path)
```

```text
src/ingestion/validation.py

check_missing_values(df)
check_duplicate_timestamps(df)
check_out_of_order_timestamps(df)
check_timestamp_gaps(df)
check_dtypes(df)
check_units_metadata(config)
validate_data(df, config)
```

---

# 31. Current pipeline

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
17 × 109 for sample.csv
      │
      ▼
validate_data()
      │
      ├── missing values
      ├── duplicate timestamps
      ├── timestamp ordering
      ├── timestamp gaps
      ├── dtypes
      └── units
      │
      ▼
VALIDATION REPORT
```

Not yet implemented:

- closure detection
- event assembly
- status decoding
- `cap_present`
- `reject_signal`
- machine/head event fields
- capping speed
- analytics
- agent tools

---

# 32. Testing status

```text
Loader tests:      12 / 12 PASS
Validation tests:  16 / 16 PASS
--------------------------------
Confirmed total:   28 PASS
```

---

# 33. Git checkpoint status

Confirmed:

- Git repository created
- GitHub remote connected
- initial project commit created
- Step 4 committed and pushed
- working tree was clean after Step 4

After the latest Step 5 changes:

- all Step 5 tests pass
- Step 5 should be committed/pushed if not already done after the final 16-test run

Recommended:

```bash
git add .
git commit -m "Implement telemetry validation checks"
git push
```

Then:

```bash
git status
```

Expected:

```text
nothing to commit, working tree clean
```

---

# 34. Recommended workflow from now on

For each step:

1. Read the Build block.
2. List required behavior.
3. Write tests first where required.
4. Implement only that step's responsibility.
5. Run targeted tests.
6. Run the full test suite.
7. Update this audit document.
8. Commit to Git.
9. Move on only after the audit is clean.

For Step 6 specifically:

```text
tests first
↓
closure-detection implementation
↓
edge-case review
↓
document assumptions
↓
commit
```

---

# 35. Immediate next action

Before Step 6:

```bash
git status
```

If Step 5 is not committed:

```bash
git add .
git commit -m "Implement telemetry validation checks"
git push
```

Then begin Step 6 with tests before implementation.

---

# 36. Audit snapshot

**Repository:** created and synchronized  
**Python:** 3.12.14  
**Virtual environment:** working  
**Config:** working  
**Sample input:** 17 rows × 109 columns  
**Loader:** complete  
**Loader tests:** 12/12 pass  
**Validation:** complete  
**Validation tests:** 16/16 pass  
**Total confirmed tests:** 28  
**Current milestone:** M1 complete  
**Next step:** Step 6 — closure detection, tests first
