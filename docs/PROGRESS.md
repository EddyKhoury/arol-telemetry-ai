# Project progress

**Project Q3** — Multi-Agent System (MAS) for Industrial IoT Data Refinement and Analytics
**Team** — Person A (data & analytics), Person B (agent & interface)
**Updated** — 2026-09-15
**Deadline** — delivered before or during the **February 2027** exam session

---

## 1. The objective

Build a chatbot that answers questions about AROL capping-machine telemetry in plain
language — *"what is the success rate per head?"*, *"why does head 4 fail more?"* — and
returns a written report with real numbers, plots, and a stated confidence level.

**The design decision everything follows from:**

> The language model chooses *which* analysis functions to call, with which parameters,
> and in which order. It never performs a calculation and never sees a raw telemetry row.

The brief demands "repeatable, explainable outputs". Repeatable means asking the same
question twice returns the same numbers — impossible if a model is doing the counting,
because models are sampled rather than evaluated. So all arithmetic lives in ordinary
tested Python, and the model is confined to routing and prose.

### The five graded objectives

These are from the Q3 brief and are what the project is marked against.

| # | Objective | Owner | State |
|---|---|---|---|
| 1 | Data ingestion & local synchronisation (pull from Cloud, local persistence layer) | A | Not started |
| 2 | Agent-based data cleaning (polling rate vs. production cycle mismatch) | A | Not started |
| 3 | Deduplication & logic filtering | A | Not started |
| 4 | Advanced data analytics (KPIs, anomaly detection, trend analysis) | A + B | **B's half done**, A's pending |
| 5 | Scalability & autonomy (vs. monolithic scripts) | B | Not started |

---

## 2. Status at a glance

| Metric | Value |
|---|---|
| Commits | 7 |
| Engine | **Polars** (migrated from pandas, verified against golden outputs) |
| Tests | **107 passing** |
| Registered analysis tools | 6 |
| Planner | rule-based + **LLM (local Llama 3.2 3B via Ollama)** |
| Working tree | Clean |
| Analysis speed | 180 ms over 518,400 events |

Run it:

```
python -m src.interface.cli ask "is anything wrong with the machine?"
python -m pytest tests -q
```

Use `D:/ANACONDA/python.exe` — the default Python 3.14 on this machine has no pandas.

---

## 3. What has been done

### 3.1 The integration contract — the foundation

Person A proposed a contract (`contract.pdf`). It was audited, amended, and committed as
`docs/contract.md`, with the reasoning in `docs/audit-of-contract.md`. **Every clause is
now enforced by a test.** The gaps found and closed:

| ID | Gap in the original proposal | Resolution |
|---|---|---|
| F1 | **No load interface.** Every tool takes an event table as input, but nothing specified the function that produces one — Person B could not write any agent code. | Added `list_pools` / `load_pool` / `pool_meta`, stubbed at `src/ingestion/api.py` |
| F2 | Contract framed Person B as a pure consumer, contradicting the plan, which gives B the WP2 KPI half | Ownership restated per key, not per section |
| F3 | **No tool registry.** No way to generate the model's function-calling schemas. | `src/common/registry.py` — one declaration produces both dispatch and JSON schema |
| F4 | No shared parameter vocabulary — a model would emit `head`, `from`, `since`, and dispatch would fail | Vocabulary frozen; registration fails at import if a tool invents a name |
| F5 | Timestamps declared UTC; plant telemetry is local time, which would shift closures across midnight and break every per-day KPI | Plant-local naive timestamps, all bucketing through one shared helper |
| F6 | "Counters only ever +1" was an observation, not a rule — nothing specified dropped polls or counter resets | `count_delta` and `inferred` columns; rules written down |
| F7 | Cleaning and dedup declared unnecessary — but they are **two of the five graded objectives** | Cleaning counters added to `pool_meta`; every report prints them |
| F8 | No local persistence layer (objective 1), and re-parsing 57 MB per question would make the demo unusable | Parquet cache in config |
| F9 | No scalability evidence (objective 5), and nobody owned it | Assigned to Person B |
| F10 | Q3 is titled *Multi-Agent System*; the design was one planner over tools | Mechanism kept; components named Orchestrator / Ingestion / Cleaning / Analytics / KPI |
| F11 | Status treated as an enum | Decoded as a **bitfield** — the brief's codes pair as *n*/*n+1*, so bit 0 is the reject flag and `65 = 64\|1` |
| F12–F19 | `pool_id` missing, envelope not invariant, `meta` too thin for tracing, no shared module, no `.gitignore` for 57 MB CSVs, contract existed only as a PDF | All resolved |

### 3.2 Code delivered (all Person B)

| Component | What it does | Where |
|---|---|---|
| **Event schema** | 12 columns, one row per closure; validation; bitfield status decoding | `src/common/schema.py` |
| **Envelope** | Every tool returns `{ok, result, error, meta}` with mandatory `meta.n` | `src/common/envelope.py` |
| **Tool registry** | Decorator registration, generated JSON schemas, frozen vocabulary, alias handling | `src/common/registry.py` |
| **Time helpers** | Shared hour/shift/day/week bucketing so both halves bucket identically | `src/common/timeutils.py` |
| **Config** | All paths and thresholds; `config.local.yaml` override | `config.yaml`, `src/common/config.py` |
| **Data source** | `synthetic` / `real` switch — the one-key Phase-5 swap | `src/common/datasource.py` |
| **KPI tools (5)** | Success rate, per-head breakdown, anomaly detection, idle periods, throughput | `src/analytics/kpi.py` |
| **Synthetic generator** | Seeded; injects 3 faults at known locations; emits ground truth | `src/testing/synth.py` |
| **Planner** | Rule-based intent routing and filter extraction | `src/agent/planner.py` |
| **Orchestrator** | Plan → execute → validate → retry → degrade → assemble | `src/agent/orchestrator.py` |
| **Report assembler** | Six mandated sections; confidence computed from `meta.n` | `src/agent/report.py` |
| **Trace log** | Tool sequence, arguments, timings — saved with every report | `src/agent/trace.py` |
| **CLI** | `report`, `ask`, `chat`, `tools`, `pools` | `src/interface/cli.py` |
| **Tests** | Contract, KPIs, failure paths, determinism, precision/recall | `tests/` (61) |

### 3.3 Two decisions worth defending in the oral

**The success-rate denominator.** A No Load cycle is not a failed closure — there was no
cap present to close. Success rate divides by cap-present closures only. On our data the
difference is **99.86% vs 91.05%** — an 8.8-point swing. Both figures are always
reported, and every report states in words which denominator it used.

**The anomaly detector was wrong first, and a test caught it.** The initial version used
a robust z-score on per-head reject rates and produced a false positive: with most heads
on 0 or 1 rejects, the median absolute deviation collapses to ~1e-6, so a head with 2
rejects scored as a wild outlier. Root cause — **any spread measure on rates alone
discards sample size.** Replaced with an exact binomial upper-tail test against the fleet
median, Bonferroni-corrected across heads. Precision and recall are now both 1.0 against
the injected fault, with a regression test for the false-positive case.

---

## 4. What remains

### 4.1 Person B — in order

| # | Task | State |
|---|---|---|
| 1 | Obtain the CSVs and AROL status-code table | **done** — archive present, bitfield confirmed |
| 2 | Migrate to Polars | **done** — 16x faster, 5x less memory, golden-verified |
| 3 | `head_detail`, fixing the silently-widened question | **done** |
| 4 | LLM planner | **done** — local Ollama, automatic fallback to rules |
| 5 | Plots and HTML/PDF export | **done** |
| 6 | Scaling benchmark (objective 5) | **done** — 20.6x, growing with volume |
| 7 | Architecture doc | **done** — `docs/architecture.md` |
| 8 | Agent decision-flow doc | **done** — architecture.md section 5 |
| 9 | **Install Ollama + `ollama pull llama3.2:3b`** | **outstanding — yours** |
| 10 | **The adapter: `src/ingestion/api.py` to Person A's pipeline** | **outstanding — blocked on decisions below** |
| 11 | Slide deck | outstanding |

### 4.1b Superseded


| # | Task | Notes |
|---|---|---|
| 1 | **Obtain the CSVs and AROL status-code table** from Person A | Blocking. Settles F11 and lets the conformance test run against real output |
| 2 | Write `no_load_rate_per_head` | Small; teaches the registry by using it |
| 3 | Fix the dropped head filter | `"is anything wrong with head 26?"` extracts `head_id` then silently discards it, because the fleet-comparison tools take no single head. The report should say it widened the question |
| 4 | Implement `LLMPlanner` | Interface and tool schemas already exist. Keep the rule planner as demo fallback and determinism baseline |
| 5 | Plots and export | Matplotlib figures; HTML and PDF alongside the working Markdown |
| 6 | Scaling benchmark | Objective 5. 1/2/4/8 day-files, wall time and peak memory, vs. a naive monolithic script |
| 7 | Graceful-failure demo | Paths already work and are tested; package them so they are visible live |
| 8 | Architecture doc, agent decision-flow doc, slide deck | Person A's two diagrams drop straight in |

### 4.2 Person A — nothing started yet

This is the critical path. Three of the five graded objectives are his and have no code.

| # | Task | Notes |
|---|---|---|
| 1 | Implement `src/ingestion/api.py` | Signature already agreed and stubbed. Must pass `validate_events()` |
| 2 | Cleaning stage (objective 2) | Polling-rate vs. cycle mismatch. Must be measured, not just present |
| 3 | Deduplication (objective 3) | Counters already have somewhere to land in `pool_meta` |
| 4 | Persistence layer + Cloud sync (objective 1) | Parquet cache. Also fixes chat latency |
| 5 | Statistical tools | Torque distributions, drift detection, correlation between heads |
| 6 | Confirm the status bitfield against AROL's code table | Fills `CATEGORY_NAMES` in `schema.py` |
| 7 | Confirm plant shift boundaries | Currently 06:00 / 14:00 / 22:00, provisional. Wrong boundaries make per-shift KPIs meaningless |
| 8 | Verify counter behaviour on the **stitched** pools | Count `delta > 1` and `delta < 0` across the whole pool, not per file |

### 4.3 Joint

- Person A signs off the contract amendments marked **[B]** in `docs/contract.md`
- Agree the target exam session, and an internal deadline two weeks before it
- Weekly cross-review
- End-to-end demo, dry runs, and the presentation (15–20 min + 20 min Q&A)

---

## 5. Blockers

| Blocker | Impact | Action |
|---|---|---|
| Telemetry CSVs not available to Person B | Cannot run the conformance test against real data; everything runs on synthetic | Ask Person A |
| AROL status-code table not available | The bitfield reading (F11) stays a hypothesis | Ask Person A |
| Person A has not started | Three graded objectives at zero; integration untested | Raise this week |

---

## 6. Reference

| Document | Contents |
|---|---|
| `README` | How to install, run, and test; data formats; division of work |
| `docs/contract.md` | The integration contract — schema, load interface, registry, envelope, config |
| `docs/audit-of-contract.md` | Why each amendment was made; written as a message to Person A |
| `docs/PROGRESS.md` | This file |
