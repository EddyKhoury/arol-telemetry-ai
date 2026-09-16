# Architecture

Project Q3 — Multi-Agent System for Industrial IoT Data Refinement and Analytics.
This document covers Person B's half and the seam to Person A's.

---

## 1. The design decision everything follows from

The brief requires **"repeatable, explainable outputs."**

Repeatable means asking the same question twice returns the same numbers. A
language model is *sampled*, not evaluated, so the moment a model computes a
figure, repeatability is gone. That single requirement eliminates the obvious
design — feed the data to an LLM and ask — and forces this one:

> **The model chooses which functions to call. Deterministic Python does every
> calculation. The model never sees a telemetry row.**

Every structural choice below exists to make that separation enforceable rather
than merely intended.

---

## 2. Layers

Nothing in a layer imports from a layer below it; the dependency graph is
acyclic, verified by static analysis.

```
        RAW TELEMETRY          86,400 rows x 109 cols/day, ~57 MB
             |                 counters, torque, status, 1 Hz
    +--------v---------+
    |  INGESTION       |       Person A
    |  + CLEANING      |       load, validate, clean, dedup, detect closures
    +--------v---------+
             |
     ========v========   CONTRACT 1 - THE EVENT TABLE
                         one row per closure, 12 columns
             |
    +--------v---------+
    |  ANALYSIS TOOLS  |       A: torque, drift, correlation
    |  pure functions  |       B: KPIs, idle, throughput, per-head
    +--------v---------+
             |
     ========v========   CONTRACT 2 - THE ENVELOPE
                         {ok, result, error, meta}
             |
    +--------v---------+
    |  ORCHESTRATOR    |       Person B
    |  plan/execute/   |  <--- the ONLY model call: which tools, which args
    |  validate/retry  |
    +--------v---------+
    |  REPORT + CLI    |       templates -> prose, plots, trace log
    +------------------+
```

**Only two interfaces cross the A/B boundary.** That is why the two halves were
built in parallel, without a shared repository, and still fit.

### Evidence the layering is real

A dependency-graph analysis of the codebase (330 nodes, 489 edges) reports
**no import cycles**, and finds `envelope()` the most connected node in the
project — fan-in 12, fan-out 2, instability ≈ 0.14. Dependencies point toward
the stable contract, which is the Stable Dependencies Principle satisfied by
measurement rather than intention.

---

## 3. The two contracts

### The event table — `src/common/schema.py`

One row per closure: `ts, pool_id, machine_id, head_id, head_index, torque,
status, error_class, reject_signal, cap_present, count_delta, inferred`.

`EVENT_COLUMNS` is the single source of truth; `validate_events()` enforces
names, types and order. Both the real loader and the synthetic generator must
pass it, which is what makes them interchangeable.

**Status is decoded as a bitfield, not an enum.** Bit 0 is the reject flag;
the high bits are the error category. Confirmed against AROL's code table:
every category appears as a pair *n* / *n+1* — `2/3` No Load, `4/5` No Closure,
`8/9` No InTorque, `16/17` No CapTurns, `32/33` Following Error, `64/65` Bad
Closure. So `65 == 64 | 1`. Unknown codes degrade to `Unknown (<code>)` rather
than crashing.

**The success-rate denominator.** A No Load cycle had no cap to close, so it is
not a failed closure:

```
success_rate = closures with status 0  /  closures where a cap was present
```

On real telemetry (2026-02-01) this is worth **44.1 percentage points** —
99.9991% over cap-present closures against 55.87% over all cycles, because the
machine is starved 44% of the time. Both figures are always returned and every
report states which denominator it used.

### The envelope — `src/common/envelope.py`

Every tool returns `{ok, result, error, meta}`. All four keys always present,
so the dispatcher never branches on key existence. `meta.n` is mandatory and is
what the report's confidence section is computed from — never prose.

A tool that cannot produce a result **returns** a failure envelope; it does not
raise. An exception mid-plan would kill an entire report.

---

## 4. The tool registry — `src/common/registry.py`

The planner needs a machine-readable catalogue of what it may call. A bare
Python signature provides nothing to generate that from, and a hand-maintained
parallel list drifts from the code.

```python
@tool(name="success_rate", description="...",
      params=["start", "end", "head_id", "bucket", "min_n"],
      agent="kpi", owner="B")
def success_rate(events, *, start=None, ...): ...
```

One declaration produces **both** the Python dispatch and the JSON schema handed
to the model, so the two cannot disagree.

**The parameter vocabulary is frozen.** Every tool spells a window
`start`/`end` and a head `head_id`; registration *fails at import* if a tool
invents a name. An alias table absorbs what a model actually emits (`head`,
`from`, `since`, `granularity`).

`call_tool()` never raises. A missing tool, a bad parameter, or a bug inside a
tool all return a failure envelope carrying a message the model can read and
retry against.

---

## 5. Agent decision flow — `src/agent/orchestrator.py`

```
   user query
       |
       v  parse intent ......... planner: scope, filters, time window
       |
       +--> ambiguous? --------> ask the user, stop
       |
       v  plan tool sequence ... chosen from the registry
       v  load pool ............ ingestion agent (or synthetic)
       |
       +--> load failed? ------> degraded report, stop
       |
       v  execute tools ........ structured results only
       |
       +--> empty / error? ----> retry, relaxing filters CUMULATIVELY
       |                          (start, then +end, then +machine_id,
       |                           then +head_id - each keeps the
       |                           previous ones dropped)
       v  validate ............. ok / partial / degraded
       v  assemble report ...... six mandated sections
       v  deliver .............. markdown, figures, HTML/PDF, trace log
```

Every edge is exercised by a test, including the ones that only appear when
something goes wrong.

---

## 6. Where the model sits

```python
def get_planner(cfg):
    if cfg["agent"]["planner"] == "rules": return RulePlanner()
    if cfg["agent"]["planner"] == "llm":   return LLMPlanner(cfg)
```

| | RulePlanner | LLMPlanner |
|---|---|---|
| Method | keyword intent matching | Llama 3.2 3B via local Ollama |
| Handles | ~5 intents, known phrasings | anything the tools can answer |
| Determinism | total | fixed seed; reproducible locally |
| Needs | nothing | a local model, no network |

**The model runs locally, not against a hosted API.** Three reasons: a hosted
endpoint is not deterministic even at temperature 0 because of server-side
batching, whereas a local model with a fixed seed is; the demo cannot fail on
network; and plant OT networks are typically air-gapped, so on-premises is what
an industrial deployment would actually require.

**The LLM planner falls back to the rule planner** on any failure, and the
report header names the planner that *actually answered* —
`llm->rules (fallback)` — because claiming the model produced an answer the
keyword rules produced would be exactly the misrepresentation the report
structure exists to prevent.

### What the model can and cannot break

It names tools and arguments. It never computes. So a misrouted question yields
the **wrong analysis**, never a **wrong number**. A small local model's typical
failures are absorbed before dispatch:

Every row below was observed from llama3.2:3b on the first six live
questions, not imagined:

| the model does | the system does |
|---|---|---|
| invents a tool name | dropped before dispatch |
| invents a parameter | dropped |
| says `head` not `head_id` | alias table normalises it |
| sends `min_n="10"` as a string | coerced to `10` against the declared schema type |
| sends `bucket="daily"` | mapped onto the enum value `day` |
| fills optional slots with the string `"null"` | treated as not supplied |
| sets `start` and `end` to `"now"` | dropped: unresolvable against a February pool |
| names `MCC777` when the machine is `MCC777-01` | filter relaxed on retry, disclosed in the report |
| answers "is head 26 bad?" fleet-wide | `head_detail` prepended for H26 |
| server unreachable | keyword fallback, declared in the report |

**The planner drops what it cannot use; `call_tool` rejects it.** The split is
deliberate: a bad argument from a 3B model is noise to absorb so the answer
still lands, while the same argument arriving from Person A's code or a test is
a bug that should be loud. Both paths record what happened.

A declared type that is never enforced is a comment. The registry advertised
JSON-Schema types to the model for weeks and checked none of them coming
back — which surfaced the moment a real model, rather than a mock, answered.

---

## 6b. The A/B seam in practice — `src/ingestion/adapter.py`

The contract said 12 columns. Person A's working pipeline emits 8, and types
`status` as Int64 rather than Int16. Three options existed: make him change a
working pipeline, bend the contract to whatever his code emits, or convert.

**Converting is the only one that costs nobody anything**, so the adapter
translates and — more importantly — declares what it *cannot* translate.

| gap | adapter's answer |
|---|---|
| `pool_id` missing | the caller asked for a pool, so it knows |
| `head_index` missing | parsed from `head_id`, for numeric not lexical sort |
| `status` Int64 vs Int16 | cast, **range-checked first** |
| `count_delta` / `inferred` missing | set to 1 / False, **and the loss declared** |

Two of those deserve the emphasis.

**The cast is checked, not assumed.** Polars wraps on a narrowing cast, so a
status of 40000 would silently become negative and decode as a nonsense
category. The adapter raises instead. Silent corruption is the one outcome it
must never produce.

**The dropped closures cannot be recovered, so they are reported.** His closure
detector filters `__count_delta == 1` before the event table exists, so counter
jumps never reach us. `count_delta = 1` is true of every row the adapter is
given — but the rows that are missing are missing upstream. That loss goes into
`pool_meta["warnings"]`, and therefore into every report's "data used" section.
A number this module cannot see is a number it must not invent.

The adapter also **re-decodes `status` with the contract's own decoder** rather
than trusting his three decoded columns, and reports disagreements rather than
silently preferring one side. His decoder and ours were written independently
from the same AROL table, so a mismatch would be a real finding about the
integration.

### Verified on his actual code, on real telemetry

| | |
|---|---|
| His pipeline | 765,703 events |
| Our independent reshape of the same day | 765,711 events |
| Difference | **exactly 8** — precisely the counter jumps his filter drops |
| Status decoding disagreements | **0** across 765,703 events |
| Torque / status on shared closures | identical |

Both repos name their top-level package `src`, so his modules cannot be
imported into this process at all. `tests/person_a_bridge.py` runs his pipeline
in a subprocess with `cwd` set to his repo and hands back Parquet — which is
also the honest shape of the integration, since he already ships
`write_event_table_parquet`. Nothing writes to his repo.

`data.source: person_a` makes this the live path, so the CLI answers questions
about real telemetry today rather than only in a test.

### Still open, and it is his to close

The real February file spans `2026-01-31T16:00:06` to `2026-02-01T15:59:59`,
and hours 17–21 in file time are ~100% No Load while 09–15 are the busiest.
Under UTC+8 the 16:00 boundary *is* local midnight and the idle block falls at
01:00–05:00 local — a night break, which is coherent. Under `Europe/Rome` the
file would span 17:00–17:00 local, which is not a plant day boundary at all.

The evidence points to roughly UTC+8. It is not proof, so `data.timezone` is
`null` and every report prints "timezone unconfirmed" rather than a guess —
the string is printed as fact, so it had better be one. Every per-day and
per-shift KPI depends on Person A confirming this with AROL.

---

## 7. The MAS framing

Q3 asks for a multi-agent system. The mechanism is one orchestrator over
deterministic tools — the determinism argument requires that — but the
components are named and given declared contracts:

| Agent | Owner | Responsibility |
|---|---|---|
| **Ingestion** | A | load pools, validate, stitch counter streams, detect closures |
| **Cleaning** | A | polling/cycle mismatch filtering, dedup, timestamp integrity |
| **Analytics** | A | torque statistics, distributions, drift, correlation |
| **KPI** | B | success rates, per-head, bucketing, idle, throughput |
| **Orchestrator** | B | intent, planning, dispatch, validation, retry, assembly |

Agent ownership is declared in code via `@tool(agent=...)` and appears in every
trace entry. Exactly two message types cross an agent boundary: the event table
and the envelope.

---

## 8. Reproducibility

| Claim | How it is established |
|---|---|
| Same question, same numbers | Tools are deterministic Python; a test runs a query twice and compares |
| Ordering is stable | Every sort key is *total* — a partial key once let tied idle periods swap order |
| Synthetic data is fixed | Seeded generator; same seed, same table |
| Detection actually works | Faults injected at known locations; precision and recall measured, not asserted |
| Any report can be reproduced | The trace log records every tool, its arguments, its `n` and its timing |

The trace log is what makes an LLM-planned report auditable: routing may vary,
but what actually ran is written down.

---

## 9. Measured

| | |
|---|---|
| pandas → Polars migration | 9.56 s → 0.60 s, 178 MB → 33 MB per machine-day |
| Analysis over 765,711 real closures | ~320 ms |
| Test suite | 255 tests, 94% line coverage |

**Scaling figures are not repeated here.** They live in `docs/benchmark.md`,
which is generated from `docs/benchmark.json` by the harness itself. They were
hand-copied into this file and into the slide deck twice, and went stale both
times — once in each direction.

The shape of the result, which does not change between runs:

- **On a single question the advantage is modest and noisy** — 1.3x to 2.2x
  over 1, 2 and 4 day-files, with no reliable direction over that range and
  run-to-run spread that overlaps between sizes. Building the whole event
  table costs roughly what answering one question from it saves. Worth saying
  out loud rather than hiding: a pipeline is not a dramatically faster way to
  compute one number.
- **The decisive result is the second question.** A monolith costs *exactly*
  5.00× for five questions, at every size, because nothing is reused. The
  agent costs a fraction of that: one reshape, then milliseconds of columnar
  aggregation per question. An interactive agent is asked many questions of
  one dataset, which is exactly the regime where a monolithic script degrades
  fastest.

### How this was got wrong, twice

The first harness measured wall time **while tracemalloc was attached**.
tracemalloc traces every allocation, so it costs the monolith — a Python loop
allocating per closure — about **31×**, and the agent path — Polars, allocating
in Rust where tracemalloc cannot reach — about **1.2×**. The reported 25×
speedup was mostly the profiler's bias against Python loops. The real figure
was about 2×.

The second problem was sample size: with honest timing, the four-file agent
measurement varied between **1.56 s and 3.61 s** across three runs, which is
wider than the effect being measured. Each timing is now the median of three
runs, the spread is published beside it, and time and memory are measured in
separate passes.

The memory column carries its own caveat, for the same class of reason:
tracemalloc counts Python allocations only, so Polars' Rust-side frames are
invisible to it. The agent's memory figure is a floor, not a total, and the
two columns are not measuring the same thing.

Full method and tables: `docs/benchmark.md`.
