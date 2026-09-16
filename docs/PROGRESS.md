# Project progress

**Project Q3** — Multi-Agent System (MAS) for Industrial IoT Data Refinement and Analytics
**Team** — Person A (data & analytics), Person B (agent & interface)
**Updated** — 2026-09-16
**Deadline** — delivered before or during the **February 2027** exam session

---

## 1. The objective

Build a chatbot that answers questions about AROL capping-machine telemetry in plain
language — *"what is the success rate per head?"*, *"why does head 26 fail more?"* — and
returns a written report with real numbers, plots, and a stated confidence level.

**The design decision everything follows from:**

> The language model chooses *which* analysis functions to call, with which parameters,
> and in which order. It never performs a calculation and never sees a raw telemetry row.

The brief demands "repeatable, explainable outputs". Repeatable means asking the same
question twice returns the same numbers — impossible if a model is doing the counting,
because models are sampled rather than evaluated. So all arithmetic lives in ordinary
tested Python, and the model is confined to routing and prose.

### The five graded objectives

| # | Objective | Owner | State |
|---|---|---|---|
| 1 | Data ingestion & local synchronisation (pull from Cloud, local persistence) | A | **Parquet persistence done**; Cloud sync not started |
| 2 | Agent-based data cleaning (polling rate vs. production cycle mismatch) | A | Not started |
| 3 | Deduplication & logic filtering | A | Not started |
| 4 | Advanced data analytics (KPIs, anomaly detection, trend analysis) | A + B | **B's half complete**; A's statistical tools pending |
| 5 | Scalability & autonomy (vs. monolithic scripts) | B | **Done and measured** |

---

## 2. Status at a glance

| Metric | Value |
|---|---|
| Commits | 12 |
| Engine | **Polars** on both sides |
| Tests | **255 passing**, 94% line coverage |
| Registered analysis tools | 6 |
| Planner | rule-based + **LLM (local Llama 3.2 3B via Ollama), running** |
| Runs on real telemetry | **yes** — Person A's pipeline output, via the adapter |
| Analysis speed | 320 ms over 765,711 real closures |

```bash
python -m src.interface.cli ask "is anything wrong with the machine?"
```

```bash
python -m pytest tests -q
```

Use `D:/ANACONDA/python.exe` — the default Python 3.14 on this machine has no pandas.

---

## 3. What is done

### 3.1 The integration contract

Person A proposed a contract (`contract.pdf`). It was audited, amended, and committed as
`docs/contract.md`, with the reasoning in `docs/audit-of-contract.md`. **Every clause is
enforced by a test.** Nineteen findings (F1–F19) were raised and closed; the load
interface (F1), the tool registry (F3), the frozen parameter vocabulary (F4), plant-local
timestamps (F5) and the bitfield status reading (F11) were the blocking ones.

### 3.2 Code delivered (all Person B)

| Component | What it does | Where |
|---|---|---|
| **Event schema** | 12 columns, one row per closure; validation; bitfield status decoding | `src/common/schema.py` |
| **Envelope** | Every tool returns `{ok, result, error, meta}` with mandatory `meta.n` | `src/common/envelope.py` |
| **Tool registry** | Decorator registration, generated JSON schemas, frozen vocabulary, aliases, **type coercion** | `src/common/registry.py` |
| **Time helpers** | Shared hour/shift/day/week bucketing | `src/common/timeutils.py` |
| **Config** | All paths and thresholds; `config.local.yaml` override | `config.yaml`, `src/common/config.py` |
| **Data source** | `synthetic` / `person_a` / `real` switch | `src/common/datasource.py` |
| **KPI tools (6)** | Success rate, per-head, anomalies, idle, throughput, head detail | `src/analytics/kpi.py` |
| **Person A adapter** | His 8-column frame → the contract's 12, declaring what it cannot recover | `src/ingestion/adapter.py` |
| **Synthetic generator** | Seeded; injects 3 faults at known locations; emits ground truth | `src/testing/synth.py` |
| **Planner** | Rule-based intent routing **and** local LLM function-calling, with fallback | `src/agent/planner.py` |
| **Orchestrator** | Plan → execute → validate → retry → degrade → assemble | `src/agent/orchestrator.py` |
| **Report assembler** | Six mandated sections; confidence computed from `meta.n` | `src/agent/report.py` |
| **Trace log** | Tool sequence, arguments, timings — saved with every report | `src/agent/trace.py` |
| **Plots / export** | Matplotlib figures; HTML and PDF | `src/interface/{plots,export}.py` |
| **Scaling benchmark** | Objective 5, against a monolithic baseline | `src/testing/benchmark.py` |
| **CLI** | `report`, `ask`, `chat`, `tools`, `pools` | `src/interface/cli.py` |
| **Slide deck** | 18 slides + speaker notes + dry-run checklist | `docs/slides.md` |

### 3.3 Four things worth defending in the oral

**The success-rate denominator.** A No Load cycle is not a failed closure — there was no
cap present to close. Success rate divides by cap-present closures only. On the real
2026-02-01 data the difference is **99.9991% vs 55.87% — 44.1 percentage points**,
because the machine is starved 44% of the time. Both figures are always reported, and
every report states in words which denominator it used.

**The anomaly detector was wrong first, and a test caught it.** The initial version used
a robust z-score on per-head reject rates and produced a false positive: with most heads
on 0 or 1 rejects, the median absolute deviation collapses to ~1e-6, so a head with 2
rejects scored as a wild outlier. Root cause — **any spread measure on rates alone
discards sample size.** Replaced with an exact binomial upper-tail test against the fleet
median, Bonferroni-corrected across heads. Precision and recall are both 1.0 against the
injected fault, with a regression test for the false-positive case.

**The bitfield reading survived data nobody had seen.** Three months assumed only
`{0, 2, 65}` existed — that is all one day-file contains. Running the benchmark over four
day-files surfaced two events with status **9** (2026-02-04, 16 s apart, heads H27 and
H17). `9 == 8|1` decoded as **No InTorque, rejected** with no code change. An enum would
have returned `Unknown (9)`. It also justified the tri-state `cap_present`: a No InTorque
event does not say whether a cap was in the head.

**The mocked tests passed; the real model broke four things.** Switching `agent.planner`
to `llm` and pointing it at a live Llama 3.2 3B exposed non-cumulative retry relaxation,
unenforced parameter types, the string `"null"` in optional slots, and a named-head
question answered fleet-wide. All four are fixed and covered. See `docs/architecture.md` §6.

---

## 4. What remains

### 4.1 Person B

| # | Task | State |
|---|---|---|
| 1 | Obtain the CSVs and AROL status-code table | **done** |
| 2 | Migrate to Polars | **done** — golden-output verified |
| 3 | `head_detail`, fixing the silently-widened question | **done** |
| 4 | LLM planner | **done** — local Ollama, running, with fallback |
| 5 | Plots and HTML/PDF export | **done** |
| 6 | Scaling benchmark (objective 5) | **done** |
| 7 | Architecture + decision-flow docs | **done** |
| 8 | Install Ollama + pull `llama3.2:3b` | **done** |
| 9 | Adapter to Person A's pipeline | **done** — verified on his real output |
| 10 | Slide deck | **done** — `docs/slides.md`, needs a joint pass |
| 11 | Dry runs, timed twice | outstanding — needs Person A |

### 4.2 Person A — the critical path

Three of the five graded objectives are his and have no code.

| # | Task | Notes |
|---|---|---|
| 1 | **Confirm the plant timezone with AROL** | **Highest value, lowest effort.** See §5 |
| 2 | Cleaning stage (objective 2) | Polling-rate vs. cycle mismatch. Must be measured, not just present |
| 3 | Deduplication (objective 3) | Counters already have somewhere to land in `pool_meta` |
| 4 | Cloud sync (objective 1) | Parquet persistence exists; the sync step does not |
| 5 | Statistical tools | Torque distributions, drift detection, correlation between heads |
| 6 | Decide on `count_delta > 1` | His detector filters `== 1`, dropping 8 real closures per machine-day |
| 7 | Confirm plant shift boundaries | Currently 06:00/14:00/22:00, provisional |
| 8 | Verify counter behaviour on the **stitched** pools | Count `delta > 1` and `delta < 0` across a whole pool, not per file |

### 4.3 Joint

- Person A signs off the contract amendments marked **[B]** in `docs/contract.md`
- Agree the target exam session and an internal deadline two weeks before it
- Slide 17 of `docs/slides.md` — the objectives State column — filled in together
- End-to-end demo, two timed dry runs, presentation (15–20 min + 20 min Q&A)

---

## 5. Open questions

| Question | Impact | Owner |
|---|---|---|
| **Plant timezone** | Every per-day and per-shift KPI. The real file spans 16:00→16:00; hours 17–21 are ~100% No Load. Under UTC+8 that boundary is local midnight and the idle block is a 01:00–05:00 night break — coherent. Under `Europe/Rome` it is not a plant day at all. `data.timezone` is `null` and reports print "timezone unconfirmed" rather than a guess | A → AROL |
| `delta == 1` filter | Drops 8 real closures per machine-day. Quantified and declared in every report; not silently absorbed | A |
| `status` Int16 vs Int32 | Int16 *wraps* rather than degrades above 32767. The adapter range-checks and raises. A contract change needs both signatures | AB |
| Shift boundaries | 06:00/14:00/22:00 is a guess; wrong boundaries make per-shift KPIs meaningless | A |

---

## 6. Reference

| Document | Contents |
|---|---|
| `README` | Install, run, test; data formats; division of work |
| `docs/contract.md` | The integration contract — schema, load interface, registry, envelope, config |
| `docs/audit-of-contract.md` | Why each amendment was made; written as a message to Person A |
| `docs/architecture.md` | Layers, the two contracts, the agent loop, the A/B seam, reproducibility |
| `docs/benchmark.md` | Objective 5 — method, tables, and what actually scales |
| `docs/slides.md` | The presentation deck, speaker notes, dry-run checklist |
| `docs/PROGRESS.md` | This file |
