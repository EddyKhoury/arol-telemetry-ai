# Person A — Working Spec

**Project:** Agentic AI for Telemetry Analysis on AROL Capping Machines
**Role:** Person A — Data pipeline, statistical analytics, and the tool interface the agent reasons through.

---

## How to use this file

This is a portable working spec. It works in Claude, Claude Code, ChatGPT, Codex, or on its own. It is written so you **build alongside the assistant and understand every piece** — not so an assistant generates the whole thing while you watch.

For each step there are two blocks:

- **Build** — what to implement and the reasoning behind it. Try it yourself first; use the assistant to unblock, review, and explain.
- **Audit** — how to check the step is actually correct before moving on. Run these yourself, or paste the block to an assistant and ask it to verify your code against each point.

**Ground rule for learning:** for the ordinary functions (loaders, stats), letting an assistant draft and you review is fine. For **Step 6 (closure detection)** — write it yourself and use the assistant only to review and to help generate test cases. That is the one part of this project where doing it by hand is the entire point.

**Suggested prompt to start any session:**
> "I'm working through a spec file for a data-pipeline project. I'll paste one step at a time. For each step: let me attempt it first, then review my code against the step's audit checklist and explain anything I got wrong. Don't write the whole thing for me unless I ask — I want to understand it."

---

## The non-negotiable design principle

The language model never does arithmetic. Every number comes from a tested Python function. The model only selects which function to call and explains the result. This is what makes outputs **repeatable** (same question → same numbers) — a hard requirement of the brief. Everything in this spec serves that principle.

---

## Dependency tags

Each step is tagged so you know at a glance whether you can just proceed, or whether you need something from Person B first.

- **[SOLO]** — entirely your work. Nothing from Person B needed. Just build it.
- **[SYNC]** — requires a decision or agreement *with* Person B before it's final. Don't lock it alone.
- **[CONSUMES B]** — you build it, but it takes one of Person B's outputs as input. You can build against a placeholder until his is ready.
- **[FEEDS B]** — your output is something Person B's side depends on. Get it stable and tell him when it changes.

Most steps are **[SOLO]**. The handful that touch your partner are flagged explicitly so nothing surprises you.

---

## Milestones at a glance

| Milestone | Steps | Definition of done |
|---|---|---|
| **M0 — Contract locked** | 1–3 | Schema, tool signature, and config location agreed with Person B and written in the repo |
| **M1 — Data loads & validates** | 4–5 | A dataset pool loads into a raw dataframe; validation reports problems without crashing |
| **M2 — Event table exists** | 6–9 | Closure detection works and passes edge-case tests; clean event table is produced |
| **M3 — Analytics complete** | 10–14 | All statistical functions implemented, each with a passing unit test |
| **M4 — Agent can use my tools** | 15–17 | Tool schemas written; agent selects the right tool for real questions |
| **M5 — Proven & documented** | 18–20 | Anomaly detection evaluated on ground truth; schema and methods documented |
| **M6 — Integrated** | 21–22 | Real pipeline runs end-to-end; demo and slides ready |

### Where your partner is involved (everything else is solo)

| Step | Tag | What's needed from / with Person B |
|---|---|---|
| 1 | SYNC | Agree the event-table schema together |
| 2 | SYNC | Agree the tool signature convention together |
| 3 | SYNC | Agree the shared config structure |
| 9 | FEEDS B | Your event table is what his agent consumes — keep it stable |
| 15 | FEEDS B | Agree the tool-schema format so your tools slot into his registry |
| 17 | CONSUMES B | Needs his agent loop running to test tool selection |
| 18 | CONSUMES B | Uses his synthetic faulty data as evaluation input |
| 20 | FEEDS B | His report assembler surfaces your confidence/limits fields |
| 21 | SYNC | Integration — your pipeline meets his agent |
| 22 | SYNC | Joint demo and presentation |

**Steps 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 16, 19 are entirely solo** — you can build them without waiting on anyone.

---

## Phase 1 — Agree the contract (Milestone M0)

> With Person B, before any code. This prevents rework: everything you build plugs into these shared interfaces.

### Step 1 — Event-table schema
`[SYNC]` · **must be agreed with Person B** — his agent consumes this exact shape, so it can't be decided alone.

**Build.** Agree the exact columns every closure event row will have. Proposed starting point:

| column | type | meaning |
|---|---|---|
| `ts` | datetime (UTC) | timestamp of the closure event |
| `head_id` | string / int | which head closed (e.g. `H01`) |
| `torque` | float | applied closure torque (Nm) for that closure |
| `status` | int | raw closure status code |
| `reject_signal` | bool | whether this status is a reject (from the status table) |
| `error_class` | string | decoded name: `Closure OK`, `No Load`, `No Closure`, `No InTorque`, `No CapTurns`, `Following Error`, `Bad Closure` |

Write it into `docs/schema.md` in the repo. This is the single source of truth both of you code against.

**Audit.**
- [ ] Every column has a name, a type, and a one-line meaning.
- [ ] `error_class` values map exactly to the status codes in the brief (0, 2/3, 4/5, 8/9, 16/17, 32/33, 64/65).
- [ ] Person B has confirmed the agent will consume this exact shape.
- [ ] The schema is committed to the repo, not just discussed.

### Step 2 — Tool signature convention
`[SYNC]` · **must be agreed with Person B** — his agent calls these functions, so the shape is a shared contract.

**Build.** Agree that every analysis function has the same shape:
```python
def function_name(events: pd.DataFrame, **params) -> dict:
    ...
```
Input is always the event table; output is always a JSON-serializable dict (so the agent can consume it). Agree the output convention too — e.g. every dict includes a `"result"` key and a `"meta"` key with sample size.

**Audit.**
- [ ] Both people agree functions take the event table as first argument.
- [ ] Output is always a dict, never a printed string or a bare number.
- [ ] Output dicts are JSON-serializable (no numpy types leaking through — cast to `float`/`int`).
- [ ] A sample-size field is included in output (you'll need it for confidence/limits later).

### Step 3 — Configuration location
`[SYNC]` · **agree the config approach with Person B** — you'll share a config file, so decide the structure together. You can own your own keys.

**Build.** Agree that dataset paths, thresholds, and parameters live in a config file (e.g. `config.yaml`), never hard-coded. Decide the keys now: dataset pool paths, anomaly thresholds, idle-detection window, drift window.

**Audit.**
- [ ] No file path appears as a literal string in any function.
- [ ] Config keys are named and documented.
- [ ] There is a documented way to point the system at a different dataset pool by changing config only.

> **Gate:** Do not start Phase 2 until Steps 1–3 are written in the repo and agreed. This is Milestone M0.

---

## Phase 2a — Data pipeline (Milestone M1 → M2)

> Do steps 4–9 strictly in order. Each consumes the output of the previous one.

### Step 4 — Loader
`[SOLO]` · entirely yours.

**Build.** Write a function that reads one dataset pool into a raw dataframe. Support CSV first; add JSON and Parquet after CSV works. The path comes from config. Return the raw wide table (one row per timestamp, many columns per head: `H01 Count`, `H01 AppTorque`, `H01 Status`, `H02 Count`, …).

Keep loading and cleaning separate — this function just loads.

**Audit.**
- [ ] Path is read from config, not hard-coded.
- [ ] CSV loads correctly; column names match the source.
- [ ] Timestamp column is parsed to real datetime, not left as string.
- [ ] Adding a JSON or Parquet pool works without changing the calling code.
- [ ] Loading a missing/corrupt file fails with a clear error, not a stack-trace crash.

### Step 5 — Validation
`[SOLO]` · entirely yours.

**Build.** Write validation checks that run on the loaded dataframe and *report* problems (via logging / a returned report object) rather than silently dropping data or crashing:
- Missing values (which columns, how many).
- Timestamp consistency: gaps, duplicates, out-of-order rows.
- Dtype checks: counts are integers, torque is float, status is int.
- Units metadata present where expected.

**Audit.**
- [ ] Running validation on clean data returns "no issues" cleanly.
- [ ] Running it on data with an injected missing value / duplicate timestamp / wrong dtype flags exactly that problem.
- [ ] Nothing is silently dropped — every issue is logged or returned.
- [ ] Validation never throws on bad data; it reports.

### Step 6 — Closure detection (THE CORE PROBLEM)
`[SOLO]` · entirely yours — and the one step to write by hand rather than have an assistant generate.

> **Write this one yourself.** Use the assistant to generate test cases and review, not to write the logic. This is the make-or-break step of the whole project.

**Build.** A "closure" is not given in the data — you infer it. Each head has a monotonically increasing `Count`. When head H's count increases from one row to the next, that head performed a closure in that interval.

The logic, per head:
1. Walk the rows in timestamp order.
2. Compare this row's count to the previous row's count for that head.
3. If it increased, a closure occurred — record it, attaching the closure's torque and status from the appropriate row.

**The edge cases that make this hard — write tests for these BEFORE the logic:**
- **Counter holds:** the count stays the same across several rows (no closure — don't emit one).
- **Status flips mid-hold:** status changes while the count is unchanged — decide and document which value represents the closure.
- **Counter increases by more than 1:** more than one closure happened between samples — decide how to handle (document the assumption).
- **Counter wrap / reset:** the count resets to a lower value (rollover or machine restart) — must NOT be read as a negative closure.
- **First row:** no previous row to compare against — define the starting behavior.

**Audit.**
- [ ] Edge-case tests were written *before* the implementation.
- [ ] Test: steady count across N rows → zero closures detected.
- [ ] Test: count increments by 1 → exactly one closure, with correct torque/status attached.
- [ ] Test: count jumps by k>1 → handled per a documented, deliberate rule.
- [ ] Test: count wraps/resets → no spurious closure, no negative counts.
- [ ] Test: first row handled without error.
- [ ] The assumption for each ambiguous case is written down in `docs/`, not just in your head.
- [ ] You can explain the logic out loud without reading the code (you'll need this at the defense).

### Step 7 — Event assembly
`[SOLO]` · entirely yours.

**Build.** For each detected closure, emit one row of the event table (the Step 1 schema). Decode the raw status code into `error_class` and `reject_signal` using the brief's status table:

| status | reject | error_class |
|---|---|---|
| 0 | no | Closure OK |
| 2 / 3 | no / yes | No Load |
| 4 / 5 | no / yes | No Closure |
| 8 / 9 | no / yes | No InTorque |
| 16 / 17 | no / yes | No CapTurns |
| 32 / 33 | no / yes | Following Error |
| 64 / 65 | no / yes | Bad Closure |

**Audit.**
- [ ] Output matches the Step 1 schema exactly (names, types).
- [ ] Every status code maps to the correct `error_class`.
- [ ] Odd codes (3, 5, 9, 17, 33, 65) set `reject_signal = true`; even codes set it `false`.
- [ ] One detected closure → exactly one event row.
- [ ] An unknown status code is handled explicitly (flagged, not silently mislabeled).

### Step 8 — Per-closure timestamp & capping speed
`[SOLO]` · entirely yours.

**Build.** Assign each closure a timestamp (the row where the count incremented). Compute a running capping speed in pieces/hour using an **incremental average** (update the running mean as each closure is added, rather than recomputing over all history).

**Audit.**
- [ ] Each event has a sensible timestamp tied to when the closure occurred.
- [ ] Capping speed is computed incrementally, not by full recompute each time.
- [ ] Speed units are pieces/hour and the value is plausible for the data's time span.
- [ ] Test the incremental average against a known small example by hand.

### Step 9 — Emit the clean event table
`[SOLO]` `[FEEDS B]` · you build it, but this is the artifact Person B's agent consumes — keep it stable and tell him when the shape changes.

**Build.** Produce the final event table — one row per closure event, conforming to the schema. This is the artifact every downstream function (yours and Person B's) consumes.

**Audit.**
- [ ] Output is one row per closure, not per raw timestamp.
- [ ] Schema conforms exactly to Step 1.
- [ ] Running the full pipeline twice on the same input gives an identical event table (determinism).
- [ ] Person B can load this table and it matches what the agent expects.

> **Milestone M2 reached:** the event table exists and is trustworthy.

---

## Phase 2b — Statistical analysis (Milestone M3)

> Small deterministic functions over the event table. Build easiest-first. Write a unit test for each as you go — not at the end.

### Step 10 — Torque statistics
`[SOLO]` · entirely yours.

**Build.** `torque_stats(events, status_filter=None) -> dict`: mean, min, max, standard deviation of torque, overall or filtered by status (e.g. successful closures only). Include sample size in the output.

**Audit.**
- [ ] Returns a dict with mean/min/max/std and sample size.
- [ ] `status_filter="successful"` changes the result correctly.
- [ ] Verified against a tiny hand-computed example.
- [ ] Numbers are plain Python floats (JSON-serializable), not numpy types.

### Step 11 — Torque distribution
`[SOLO]` · entirely yours. (You return the data; Person B's layer draws the plot.)

**Build.** `torque_distribution(events, bins=...) -> dict`: the histogram data (bin edges + counts) behind a distribution plot. This returns *data*, not a plot — plotting is Person B's layer.

**Audit.**
- [ ] Returns bin edges and counts, not an image.
- [ ] Bin count is configurable.
- [ ] Counts sum to the number of events considered.

### Step 12 — Trend analysis
`[SOLO]` · entirely yours.

**Build.** `torque_trend(events, window=...) -> dict`: moving average over time and a drift signal (is the mean torque moving in one direction over the window?). Window size from config.

**Audit.**
- [ ] Moving average length matches the window.
- [ ] On synthetic data with a deliberate upward drift, the drift signal fires.
- [ ] On flat synthetic data, it does not fire (no false positive).

### Step 13 — Anomaly detection
`[SOLO]` · entirely yours. (Step 18 later evaluates this against Person B's synthetic faults.)

**Build.** `detect_anomalies(events, ...) -> dict`: flag anomalous closures using (a) threshold rules (torque outside an expected band) and (b) statistical deviation (e.g. beyond k standard deviations). Return the flagged events and the reason each was flagged.

**Audit.**
- [ ] Each flagged event carries a reason (threshold vs statistical).
- [ ] Thresholds come from config, not hard-coded.
- [ ] On data with planted anomalies, they are caught (this feeds Step 18).
- [ ] On clean data, the false-positive rate is low and reported.

### Step 14 — Head correlation
`[SOLO]` · entirely yours.

**Build.** `head_correlation(events, head_a, head_b) -> dict`: compare behavior between two heads (e.g. torque correlation, success-rate difference). Used to answer "does head 1 behave like head 5?".

**Audit.**
- [ ] Handles heads with different event counts gracefully.
- [ ] Returns an interpretable measure, not just a raw number.
- [ ] Verified on two synthetic heads made deliberately similar / dissimilar.

> **Milestone M3 reached:** analytics complete, each tested.

---

## Phase 3 — Agent tool interface (Milestone M4)

> Connect your functions to the AI. Both you and Person B do prompt work — this is your shared agent experience.

### Step 15 — Tool schemas
`[SOLO]` `[FEEDS B]` · you write the schemas for your tools, but they plug into Person B's agent registry — agree the schema format with him so they slot in cleanly.

**Build.** For each analysis function, write a tool schema (name, description, parameters) the model reads to decide when and how to call it. Clear, honest descriptions matter more than clever code — the model's tool choice is only as good as your descriptions.

**Audit.**
- [ ] Every analysis function has a schema.
- [ ] Each description states plainly what the tool does and when to use it.
- [ ] Parameter names and types match the function signature exactly.
- [ ] No two tool descriptions are so similar the model would confuse them.

### Step 16 — Diagnostic prompts
`[SOLO]` · your query families are yours to own — but you're both doing prompt work, so compare notes with Person B to keep a consistent style.

**Build.** Write and test prompts for the analytical / diagnostic query families you own: "which head behaves differently," "why is head 4 failing more," "compare head 1 and head 2." These guide the agent to chain your tools sensibly.

**Audit.**
- [ ] Each target question maps to a sensible tool sequence.
- [ ] The agent explains its findings using tool outputs, not invented numbers.
- [ ] Rephrasing a question doesn't break tool selection.

### Step 17 — Verify tool selection
`[CONSUMES B]` · needs Person B's agent loop running to test against. Until it's ready, you can dry-run your tool descriptions with any assistant to sanity-check them.

**Build.** Run the real questions through the agent and check it picks your tools correctly. Where it picks wrong, fix the tool *description* (usually the description is the problem, not the code).

**Audit.**
- [ ] For a set of ~10 real questions, the agent selects the right tool(s).
- [ ] Wrong selections were fixed by improving descriptions.
- [ ] The agent never fabricates a number that should have come from a tool.

> **Milestone M4 reached:** the agent can reason through your tools.

---

## Phase 4 — Prove it works & document (Milestone M5)

### Step 18 — Anomaly ground-truth evaluation
`[CONSUMES B]` · uses Person B's synthetic data with known planted faults as input. You can build the evaluation harness now and plug his data in when ready, or make your own small labelled set as a stand-in.

**Build.** Take Person B's synthetic data with known planted faults. Run your anomaly detection against it and compute **precision and recall** against the known ground truth. This converts "we detect anomalies" into measured evidence — a genuine differentiator for the grade.

**Audit.**
- [ ] Ground-truth fault locations are known and documented.
- [ ] Precision and recall are computed and reported as numbers.
- [ ] Results are reproducible (same synthetic seed → same score).
- [ ] Weaknesses are stated honestly (e.g. "misses drift smaller than X").

### Step 19 — Data schema & methods documentation
`[SOLO]` · entirely yours (this is the data-side half of the shared technical docs).

**Build.** Write up: the event-table schema, what each field means, how closure detection works (including the documented edge-case assumptions), and each analytics method. Required deliverable.

**Audit.**
- [ ] Schema doc matches the actual code output.
- [ ] Every closure-detection assumption from Step 6 is written down.
- [ ] Each analytics method has a short "what it does / how it works" entry.
- [ ] A new reader could understand the pipeline from the docs alone.

### Step 20 — Confidence & limits language
`[SOLO]` `[FEEDS B]` · you write the caveats; Person B's report assembler surfaces them in the confidence/limits section — tell him what fields to expect.

**Build.** For each analysis, add honest caveats the agent can surface: sample-size warnings, "not statistically significant at n=40," "no data for head X in this window." The report structure demands a confidence/limits section and almost nobody fills it with anything real.

**Audit.**
- [ ] Low-sample results carry a caveat.
- [ ] Comparisons state whether the difference is meaningful.
- [ ] Missing-data situations are surfaced, not hidden.

> **Milestone M5 reached:** proven and documented.

---

## Phase 5 — Integrate & present (Milestone M6)

### Step 21 — Real end-to-end run
`[SYNC]` · done together — this is where your pipeline and his agent meet for the first time on real data.

**Build.** Swap the synthetic generator for your real pipeline and confirm the whole system runs end-to-end on a real dataset pool, producing at least two report types.

**Audit.**
- [ ] Real pipeline drops in where synthetic data was, no downstream changes.
- [ ] End-to-end run completes and produces reports.
- [ ] Numbers are stable across repeated runs.

### Step 22 — Demo & slides
`[SYNC]` · done together — you present the data/analytics half, he presents the agent/interface half.

**Build.** Help build the demo and prepare your part of the deck — you present the data pipeline and analytics, especially the closure-detection reasoning and the anomaly ground-truth results.

**Audit.**
- [ ] You can walk through closure detection live without notes.
- [ ] The ground-truth precision/recall result is in the deck.
- [ ] A graceful-failure case (bad input / empty window) is shown in the demo.

> **Milestone M6 reached:** integrated and defensible.

---

## The order that matters most

**contract → loader → validation → closure detection (tests first) → event table → analytics → tool schemas → evaluation → docs**

Closure detection (Step 6) is the step that makes or breaks the project. Write it yourself, test it first, and be able to explain it out loud. Everything downstream inherits its correctness.

---

## Session checklist (paste at the top of any working session)

- [ ] I attempted the current step before asking for help.
- [ ] The assistant reviewed my code against this step's **Audit** block.
- [ ] Every audit checkbox for this step passes.
- [ ] I can explain what I built and why, in my own words.
- [ ] I committed the work before moving to the next step.
