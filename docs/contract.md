# Project Contract - Shared Interfaces

**Project:** Agentic AI for Telemetry Analysis on AROL Capping Machines (Project Q3)

**Status:** v1.0 - Person A's proposal, amended by Person B after audit and
**implemented in code**. Every clause below is enforced by a test in `tests/`.
Awaiting Person A's review of the amendments marked **[B]**.

This file defines what our two halves must agree on so they fit together at
integration: the **event-table schema**, the **load interface**, the **tool
registry and calling convention**, and the **config layout**.

Person A's original document is the basis; `docs/audit-of-contract.md` explains
why each amendment was made and what it is protecting against.

---

## 0. Agent architecture (the MAS framing) **[B]**

Project Q3 asks for a *Multi-Agent System* with a *decentralized architecture in
which autonomous agents collaborate*, and lists *agent communication protocols
and coordination models* under required background. Person A's mechanism -
one planner over deterministic tools - is kept exactly as designed, because the
determinism argument is correct and is our strongest design decision. What
changes is that the components are named and given declared contracts:

| Agent | Owner | Responsibility | Talks to |
|---|---|---|---|
| **Ingestion** | A | Load pools, validate, stitch counter streams, detect closures | emits the event table |
| **Cleaning** | A | Polling/cycle mismatch filtering, dedup, integrity of timestamps | emits the event table + cleaning stats |
| **Analytics** | A | Torque stats, distributions, drift, correlation, torque anomalies | returns envelopes |
| **KPI** | B | Success rates, per-head aggregation, bucketing, idle, throughput | returns envelopes |
| **Orchestrator** | B | Intent, planning, dispatch, validation, retry, report assembly | calls all of the above |

The message contract between them is exactly two things: the **event table**
(section 2) and the **envelope** (section 4). Nothing else crosses an agent
boundary. Agent ownership is declared in code via `@tool(agent=...)` and appears
in every trace log entry.

---

## 1. What the real data looks like

One file = one machine (`MCC777...`), one day, 86,400 rows (1 Hz), ~57 MB.
36 heads, 3 columns each (`H## Count`, `H## AppTorque`, `H## Status`) plus one
`timestamp` = 109 columns.

- Counters hold or increment by +1; a closure's torque and status sit on the
  same row as the increment.
- Counters continue across day-files. **A pool is processed in timestamp order
  as one continuous stream.**
- Only three status codes appear: `0`, `2`, `65`.

**[B] These are observations, not guarantees.** They describe Person A's pools;
the grading dataset may differ. Sections 2 and 3 therefore specify behaviour for
cases we have not observed, rather than assuming they cannot occur.

---

## 2. Event-table schema

One row = one closure event. Defined in code at `src/common/schema.py`;
`EVENT_COLUMNS` is the single source of truth and `validate_events()` enforces it.

| column | type | source | notes |
|---|---|---|---|
| `ts` | datetime64[ns] | timestamp of the increment row | **[B] plant-local, naive** - see below |
| `pool_id` | string | the pool being processed | **[B] added** - needed to compare pools |
| `machine_id` | string | parsed from the filename | pools may mix machines later |
| `head_id` | string | the head's column prefix | keep the `H01`..`H36` form |
| `head_index` | int16 | parsed from `head_id` | **[B] added** - numeric sort order |
| `torque` | float64 | `H## AppTorque` on the increment row | Nm |
| `status` | int16 | `H## Status` on the increment row | raw code, unmodified |
| `error_class` | string | decoded from status | see section 3 |
| `reject_signal` | bool | derived from status | status bit 0 |
| `cap_present` | bool | derived from status | false only for No Load |
| `count_delta` | int32 | the counter increment | **[B] added** - see F6 below |
| `inferred` | bool | `count_delta > 1` | **[B] added** - closure not directly observed |

`SCHEMA_VERSION = "1.0"`. Both the real loader and the synthetic generator stamp
it; a test asserts they agree.

**[B] Timezone.** Timestamps stay in plant-local wall-clock time with no tzinfo.
Converting to UTC would shift closures across midnight and every "per day" and
"per shift" KPI would stop matching what the operator saw on the line. The
originating timezone is reported in `pool_meta()["timezone"]`, never applied to
the values. All bucketing goes through `src/common/timeutils.py` so both sides
bucket identically.

**[B] Counter rules (F6).** "+1 only" is an observation. The loader must define:
- `delta > 1` - a dropped poll. Emit the closure with `count_delta = delta` and
  `inferred = True`. Throughput counts `count_delta`, not rows.
- `delta < 0` - a counter reset or wrap. Log a warning, treat as a new baseline,
  never emit negative counts.

---

## 3. Status decoding

**[B] Decoded as a bitfield, not an enum.** The codes in the brief pair as
*n* / *n+1* (`2/3`, `4/5`, `8/9`, `16/17`, `32/33`, `64/65`), which is what a
bitfield looks like: **bit 0 is the reject flag, the high bits are the error
category**. It reproduces all three observed codes exactly and explains why
`reject_signal` exists as a separate column.

| status | category | error_class | reject_signal | cap_present |
|---|---|---|---|---|
| 0 | 0 | Closure OK | false | true |
| 2 | 2 | No Load | false | false |
| 65 | 64 | Bad Closure | true | true |

Unknown categories decode to `Unknown (<code>)` with `confirmed = False` rather
than crashing. **Confirmed for categories 0, 2 and 64 only** - the names of
categories 4, 8, 16 and 32 are unknown to us.

> **Open, for Person A:** you have the AROL code table we do not. Confirm the
> bitfield reading and fill in `CATEGORY_NAMES` in `src/common/schema.py`. If
> the codes are a flat enum after all, say so and we revert to a lookup - the
> function signature does not change either way.

### The success-rate denominator (A's OPEN item 1 - **resolved, agreed**)

```
success_rate = closures with status 0  /  closures where a cap was present
```

A No Load cycle is not a failed closure - no cap was there to close. Person A's
proposal is adopted. **[B] Two additions:** every report states the denominator
in words, and `no_load_rate` is reported as a KPI in its own right, because
sustained No Load means bottles are not arriving, which is a real operational
signal. Both denominators are always returned (`success_rate` and
`success_rate_all_cycles`), so a report can never be ambiguous.

On our synthetic pool the difference is 99.86% vs 91.05% - an 8.8 point swing.
Person A was right to flag it.

---

## 4. Load interface **[B] - this section is new**

Person A's document specified the shape of the event table but not the function
that produces it. Every tool takes `events` as its first argument, so without
this, Person B cannot write agent code at all. Stubbed at
`src/ingestion/api.py`; Person A implements.

```python
SCHEMA_VERSION: str
EVENT_COLUMNS: dict[str, str]

def list_pools(cfg) -> list[str]
def load_pool(cfg, pool: str, *, use_cache: bool = True) -> pd.DataFrame
def pool_meta(cfg, pool: str) -> dict
```

`pool_meta` is part of the interface, not a convenience: the report's "data
used" section and the orchestrator's ambiguity handling both read it. Expected
keys:

```
pool, n_files, n_events, ts_min, ts_max, machines, heads, timezone,
rows_read, rows_after_cleaning, duplicates_removed, schema_version, warnings
```

`rows_read` / `rows_after_cleaning` / `duplicates_removed` exist because
**Q3 grades cleaning and deduplication explicitly** (objectives 2 and 3). Those
numbers appear in every report, which is how we show the cleaning stage did
something even when the input pool was already clean.

The orchestrator never imports a loader directly - it asks
`src/common/datasource.py` for a source. `data.source: synthetic | real` in
config.yaml is the only change needed to swap between them.

---

## 5. Tool registry and calling convention

### Signature

```python
def tool_name(events: pd.DataFrame, *, **params) -> dict
```

### **[B] Registration is mandatory**

A bare signature gives the planner nothing to build a tool list from, and a
hand-maintained schema list drifts. Every tool registers itself, and the
planner's tool definitions are generated from the same declaration the function
is called with, so the two cannot disagree.

```python
@tool(name="success_rate",
      description="Overall capping KPIs ...",
      params=["start", "end", "head_id", "machine_id", "bucket", "min_n"],
      agent="kpi", owner="B")
def success_rate(events, *, start=None, ...): ...
```

`registry.get_tool_specs()` returns JSON-schema tool definitions;
`registry.call_tool(name, events, **params)` dispatches, times, catches and
guarantees a valid envelope.

### **[B] Frozen parameter vocabulary**

Every tool uses the same names, or registration fails at import:

`start`, `end` (ISO-8601), `head_id` (str or list), `machine_id`, `pool`,
`bucket` (`hour|shift|day|week`), `cap_present_only`, `min_n`, `sigma`,
`window_seconds`.

Common near-misses (`head`, `from`, `since`, `granularity`, ...) are normalised
by an alias table and the substitution is recorded in the trace.

### The envelope

```python
{
  "ok": bool,
  "result": {...} | None,
  "error": str | None,
  "meta": {
      "tool": str, "agent": str, "n": int, "params": {...},
      "filters_applied": [...], "data_window": {"ts_min":..., "ts_max":...},
      "units": {...}, "elapsed_ms": float, "notes": str,
  }
}
```

- **[B] All four top-level keys are always present** so the dispatcher never
  branches on `"error" in result`.
- `meta.n` is mandatory - the confidence/limits section of every report is
  computed from it, never written as prose.
- **[B] `meta` carries what the trace log needs** (tool, agent, params,
  elapsed_ms, data_window), so the trace is free rather than bolted on.
- JSON-serialisable only. `envelope()` casts numpy types for you.
- A tool that cannot produce a result **returns** a failure envelope; it does
  not raise. An exception mid-plan kills a whole report.

---

## 6. Configuration

One `config.yaml` at the repo root; `config.local.yaml` overrides it locally and
is gitignored. **[B] Ownership is per key, not per section** - `analytics.idle_window_seconds`
feeds Person B's idle tool even though the section is nominally A's.

Key additions: `data.source`, `data.timezone`, `data.cache_dir` (Parquet event
cache - Q3 objective 1 requires a local persistence layer, and re-parsing 57 MB
per chat question would make the demo unusable), `agent.planner`.

---

## 7. Cross-cutting agreements

1. **Pool = ordered, stitched stream.** Files are processed in timestamp order
   as one continuous counter history. Closures straddling a day boundary must
   still be caught. Both sides assume this.
2. **The placeholder handshake.** Person B builds against
   `src/testing/synth.py`, which emits exactly this schema and injects faults at
   known locations. **[B] The generator also emits ground truth**, which is what
   Person A's Phase-4 precision/recall evaluation runs against - real telemetry
   has no labels.
3. **Schema changes are a two-person decision**, made by editing this file. A
   silent schema change is the most common way a parallel two-person build breaks.
4. **Repo layout** - see README. **[B] `src/common/` added** for what belongs to
   neither side: schema, envelope, registry, config, time helpers.

---

## 8. Still open

**For Person A:**
- Confirm the status bitfield against the AROL code table (section 3).
- Confirm the plant shift boundaries in `src/common/timeutils.py` (currently
  06:00 / 14:00 / 22:00, provisional) - wrong boundaries make per-shift KPIs
  meaningless.
- Implement `src/ingestion/api.py` (section 4), including the cleaning counters.
- Verify the counter rules in section 2 against the full stitched pools, not
  per file: count `delta > 1` and `delta < 0` occurrences.

**For both:**
- Who owns the Cloud-sync stub and the Parquet cache (Q3 objective 1)? Proposed:
  the Ingestion agent, i.e. Person A.
- Who owns the scaling benchmark (Q3 objective 5)? Proposed: Person B, alongside
  the orchestrator.
- Target exam session, and the internal deadline two weeks before it.

---

## Sign-off

- [ ] Person A has read and agrees to the amendments marked **[B]**
- [x] Person B has read and agrees
- [x] OPEN item 1 (success-rate denominator) resolved - section 3
- [x] OPEN item 2 (extra event fields) resolved - `pool_id`, `count_delta`, `head_index`
- [x] OPEN item 3 (envelope shape) resolved - section 5
- [x] Committed to `docs/contract.md`
