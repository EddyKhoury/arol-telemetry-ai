# Presentation deck

Project Q3 — **Multi-Agent System for Industrial IoT Data Refinement and Analytics**
AROL capping machines · Politecnico di Torino · Prof. Stefano Quer

Target: **15–20 minutes** + 20 minutes Q&A. One slide ≈ 45 seconds.
Speaker notes are the indented lines; they are what to *say*, not what to show.

Slides marked **[A]** are Person A's to present, **[B]** Person B's, **[AB]** joint.

---

## 1 — Title [AB]

> **Ask a capping machine a question.**
> A multi-agent system for AROL telemetry.
>
> Person A — ingestion, cleaning, statistics
> Person B — agent, analytics KPIs, interface

    Say who did what in one sentence and move on. The panel wants the system,
    not the org chart.

---

## 2 — The problem [AB]

A capping machine has **36 heads**. Each is polled at **1 Hz** and reports a
counter, an applied torque, and a status code.

| | |
|---|---|
| One day-file | 86,400 rows × 109 columns, ~57 MB |
| One day of closures | **765,711** |
| Bad closures in that day (status 65) | **4** |
| Cycles with no cap present at all | **337,927** (44%) |

> An engineer wants to ask: *"is anything wrong?"*, *"which head is worst?"*,
> *"why does head 26 fail?"* — and get an answer with real numbers.

    4 in 765,711. That ratio is the whole problem: nobody finds that by
    scrolling a spreadsheet, and there are nowhere near enough failures to
    train a classifier on. State it now - it pre-empts "why no ML?" before
    they ask. The 44% no-load figure sets up slide 8.

---

## 3 — What it does [B]

```
$ python -m src.interface.cli ask "is anything wrong with head 26?"
```

```
## 4. Findings
- H26: success rate 96.73% over 13,140 cap-present closures
- That is the WORST of 36 heads.
- Fleet median is 99.95%, so this head sits 3.23 points below it.
- Method: exact binomial upper-tail test against the fleet median reject
  rate, Bonferroni-corrected across 36 heads.
```

    Show the real terminal, not this slide, if the room allows. The point to
    land: it names the method in the output. A number without its method is
    not an answer an engineer can act on.

---

## 4 — The one decision everything follows from [B]

The brief requires **"repeatable, explainable outputs."**

Repeatable means asking twice gives the same numbers. A language model is
**sampled**, not evaluated — so the moment a model computes a figure,
repeatability is gone.

> ### The model chooses *which* functions to call.
> ### Deterministic Python does every calculation.
> ### The model never sees a telemetry row.

    This is the slide to spend time on. Everything else in the deck is a
    consequence. If they only remember one thing, it is this.

---

## 5 — Architecture [AB]

```
   RAW TELEMETRY      86,400 x 109 per day
        |
   INGESTION + CLEANING            [A]
        |
   ===== EVENT TABLE =====         CONTRACT 1 - 12 columns, 1 row per closure
        |
   ANALYSIS TOOLS        [A] torque, drift   [B] KPIs, idle, throughput
        |
   ===== ENVELOPE =====            CONTRACT 2 - {ok, result, error, meta}
        |
   ORCHESTRATOR                    [B]  <-- the only model call
        |
   REPORT + PLOTS + TRACE          [B]
```

**Exactly two interfaces cross the A/B boundary.** That is why two people built
this in two repositories, in parallel, and it fits.

    Dependency analysis: 330 nodes, 489 edges, no import cycles. envelope() is
    the most connected node, instability 0.14 - dependencies point at the
    stable contract. Measured, not asserted.

---

## 6 — Contract 1: the event table [AB]

Raw telemetry is **wide** — head identity lives in the *column name*:

```
timestamp, H01 Count, H01 AppTorque, H01 Status, H02 Count, ...   (109 cols)
```

The event table is **long** — head identity is a *value*, one row per closure:

```
ts, pool_id, machine_id, head_id, head_index, torque, status,
error_class, reject_signal, cap_present, count_delta, inferred
```

86,400 × 109  →  **765,711 × 12**

    Why reshape at all: every question we ask is "group by head" or "group by
    hour". Wide data cannot be grouped; long data is one expression.

---

## 7 — Status is a bitfield, not an enum [B]

The codes pair up: `2/3`, `4/5`, `8/9`, `16/17`, `32/33`, `64/65`.

> **Bit 0 is the reject flag. The high bits are the error category.**
> So `65 == 64 | 1` — Bad Closure, rejected.

### The test of that reading

Three months of work assumed only `{0, 2, 65}` existed — that is all one
day-file contains. Running the scaling benchmark over **four** day-files
surfaced two events with status **9**, on 2026-02-04, sixteen seconds apart on
heads H27 and H17.

`9 == 8 | 1` → **No InTorque, rejected.** Decoded correctly, with no code
change. An enum would have said `Unknown (9)`.

    This is the strongest single slide for a design question. We did not
    predict code 9; the decoding survived it because it modelled the structure
    rather than enumerating observations.

---

## 8 — The denominator is a decision, not a formula [B]

A **No Load** cycle is a head closing on nothing. There was no cap to fail.

```
success_rate = closures with status 0  /  closures where a cap was present
```

| On real telemetry, 2026-02-01 | |
|---|---|
| Over cap-present closures | **99.9991 %** |
| Over all cycles | **55.87 %** |
| Difference | **44.1 percentage points** |

The machine is starved 44% of the time. Both figures are always returned, and
**every report states in words which denominator it used.**

    44 points is the difference between "this machine is fine" and "this
    machine is broken". Neither number is wrong; reporting one without saying
    which is.

---

## 9 — The anomaly detector was wrong first [B]

**v1** — robust z-score on per-head reject rates.
Most heads had 0 or 1 rejects, so the median absolute deviation collapsed to
~1e-6, and a head with **2** rejects scored as a wild outlier.

> **Root cause: any spread measure on *rates alone* discards sample size.**

**v2** — exact binomial upper-tail test per head against the fleet median
reject rate, Bonferroni-corrected across 36 heads.

Precision **1.0**, recall **1.0** against the injected fault, plus a regression
test for the original false positive.

    Volunteer this. A panel trusts a team that found its own bug more than one
    whose code never failed. And "precision and recall" only exist because the
    synthetic generator manufactures ground truth - the real data has none.

---

## 10 — The agent loop [B]

```
  query -> parse intent -> ambiguous? -> ASK, stop
              |
              v plan tool sequence      (from the registry)
              v load pool               -> failed? DEGRADED report, stop
              v execute tools
              v empty/error? -> RETRY, relaxing filters cumulatively
              v validate -> ok | partial | degraded
              v assemble -> six mandated sections
              v deliver  -> markdown, plots, HTML/PDF, trace log
```

**Every edge has a test, including the ones that only fire when something
breaks.**

    The report sections are fixed: goal, data used, analyses executed,
    findings, confidence and limits, next checks. Confidence is computed from
    meta.n - never written as prose.

---

## 11 — What the model can and cannot break [B]

It picks tool names and arguments. It never computes.
So a misrouted question gives the **wrong analysis** — never a **wrong number**.

Observed from a 3B model on the first six live questions:

| the model did | the system did |
|---|---|
| `min_n="10"` (a string) | coerced against the declared schema type |
| `bucket="daily"` | mapped onto the enum value `day` |
| `"null"` in every optional slot | treated as not supplied |
| `start="now"`, `end="now"` | dropped — unresolvable against a February pool |
| `machine_id="MCC777"` (real: `MCC777-01`) | relaxed on retry, disclosed in the report |
| answered "is head 26 bad?" fleet-wide | `head_detail` prepended for H26 |

> **The planner drops what it cannot use. `call_tool` rejects it.**
> Model output is noise to absorb; the same value from code is a bug to expose.

    Every one of these was found by pointing it at a real model. All six
    passed the mocked tests. That is the slide's real lesson.

---

## 12 — It runs offline, and it degrades [B]

**Llama 3.2 3B, local, via Ollama.** No API key, no network, nothing leaves the
machine.

| | why |
|---|---|
| Local, not hosted | a hosted endpoint is **not** deterministic at temperature 0 — server-side batching; a local model with a fixed seed is |
| | the demo cannot fail on wifi |
| | plant OT networks are typically air-gapped |
| Falls back to keyword rules | on any failure — unreachable, timeout, malformed reply |
| Header names the planner that **actually answered** | `llm->rules (fallback)` |

    Offer to kill the Ollama process live. The report still comes out, and it
    says on its own header that the rules produced it. Claiming the model
    wrote an answer the rules wrote is exactly the misrepresentation the
    report structure exists to prevent.

---

## 13 — Objective 5: scalability [B]

Agent pipeline vs. a **monolithic script** — the honest first draft: one
function, row-wise accumulation in Python, one fixed answer.

**Fill this table from `docs/benchmark.md` on the day — do not quote from
memory.** The shape of the result:

| | one question | five questions |
|---|---|---|
| 1 day-file | 1.3× | 4.5× |
| 2 day-files | 2.2× | 7.0× |
| 4 day-files | 1.9× | 6.1× |

**1.3–2.2× on one question is modest, and not a trend** — the spread overlaps
between sizes. Say that; do not dress it up.

> **The claim that holds at every size:**
> **monolith pays 5.00× for five questions. Agent pays 1.5×.**

The monolith is *exactly* linear in the number of questions — nothing is
reused. The agent reshapes once; each further question is milliseconds.

    Lead with the break-even. It is the honest number, it pre-empts the
    obvious challenge, and it makes the real claim land harder: this
    architecture is not about computing one number faster, it is about the
    second question being nearly free. An interactive agent is asked many
    questions of one dataset.

    If asked "so why bother for one query?" - you would not. You bother
    because an operator asks six.

---

## 13b — How we got the benchmark wrong [B]

The first harness timed both implementations **while a memory profiler was
attached**.

`tracemalloc` traces every allocation. The monolith is a Python loop
allocating per closure; the agent path is Polars, allocating in Rust where
tracemalloc cannot reach.

| | cost of being profiled |
|---|---|
| Monolith | **~31×** |
| Agent | **~1.2×** |

> It reported a **25× speedup**. The real figure was about **2×**.
> We were measuring the profiler.

Fixed: time and memory in separate passes, each timing the **median of three
runs**, and the spread published so a reader can see the noise.

    Volunteer this one too. It is the same lesson as the anomaly detector: the
    measurement was wrong in the direction that flattered us, and that is
    precisely the direction you have to check hardest. The course rules name
    it - "avoid auto-referentiality".

    If they ask whether the memory column is trustworthy: no, and the report
    says so. tracemalloc cannot see Rust allocations, so the agent's memory is
    a floor, not a total.

---

## 14 — Integration: the seam held [AB]

Two repositories. Two people. No shared code.

Person A's pipeline emits **8** of the contract's 12 columns and types `status`
as `Int64`. Rather than make him change working code, or bend the contract:
**`src/ingestion/adapter.py` converts — and declares what it cannot convert.**

### Verified on his real code, on real telemetry

| | |
|---|---|
| His pipeline | **765,703** events |
| Our independent reshape of the same day | **765,711** events |
| Difference | **exactly 8** — precisely the counter jumps his `delta == 1` filter drops |
| Status decoding disagreements | **0** across 765,703 events |

The 8 lost closures **cannot be recovered downstream**, so they are declared in
`pool_meta["warnings"]` and printed in every report.

> A number the adapter cannot see is a number it must not invent.

    Two independently written decoders agreeing on 765,703 events is the real
    evidence the contract worked. The 8-row gap is not a bug either of us
    introduced - it is a documented upstream choice, quantified.

---

## 15 — How we know it works [AB]

| Claim | How it is established |
|---|---|
| Same question, same numbers | a test runs each query twice and compares |
| Detection actually works | faults injected at known locations; **precision and recall measured** |
| Ordering is stable | every sort key is *total* — a partial key once let tied idle periods swap |
| The contract holds | one assertion, run against both the synthetic generator and A's real output |
| Any report is reproducible | the trace log records every tool, its arguments, its `n`, its timing |
| No traceback reaches the user | malformed input, nonsense query, empty window each tested |

**140 tests.** The pandas→Polars migration was verified by diffing golden
outputs captured before it — which caught a latent determinism bug.

    The trace log is what makes an LLM-planned report auditable: routing may
    vary, what ran is written down.

---

## 16 — What is still open [AB]

**Honest slide. Do not skip it — the panel will find these anyway.**

| Open | Owner | Impact |
|---|---|---|
| **Plant timezone unconfirmed** | A → AROL | file spans 16:00→16:00; evidence fits UTC+8, not Europe/Rome. Every per-day and per-shift KPI depends on it |
| `delta == 1` drops 8 closures/day | A | quantified and declared, not silently absorbed |
| `status` Int16 vs Int64 | AB | contract change; needs both signatures |
| Shift boundaries provisional | A | 06:00/14:00/22:00 is a guess |

We report "timezone unconfirmed" rather than a guess, because that string is
printed in every report as fact.

    If asked "why not just pick UTC+8?" - because the report prints it as
    fact, and a wrong boundary moves closures across midnight. Being visibly
    unsure is cheaper than being confidently wrong.

---

## 17 — The five graded objectives [AB]

| # | Objective | Owner | State |
|---|---|---|---|
| 1 | Cloud sync + local persistence | A | Parquet layer |
| 2 | Agent-based cleaning (polling vs cycle) | A | |
| 3 | Deduplication & logic filtering | A | |
| 4 | Advanced analytics (KPIs, anomaly, trend) | A + B | B's half complete |
| 5 | Scalability & autonomy vs monolithic scripts | B | measured |

    Fill the State column together before the dry run. Do not present an
    objective as done that is not - they will ask to see it.

---

## 18 — Close [AB]

> Three months, two repositories, two interfaces.
>
> The model routes. **Python computes.** The report says what it did,
> what it used, and what it is unsure of.

**Questions.**

---

## Dry-run checklist

- [ ] `ollama serve` running, `llama3.2:3b` pulled — **check the morning of**
- [ ] `python -m pytest tests -q` green in front of the panel
- [ ] Rehearse the fallback demo: kill Ollama mid-talk, ask again
- [ ] `docs/benchmark.json` numbers copied into slide 13
- [ ] Slide 17 State column agreed with Person A
- [ ] One printed report as a handout
- [ ] Timed twice: **20 minutes hard stop**
