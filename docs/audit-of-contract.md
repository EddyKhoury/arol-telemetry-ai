# Audit of the proposed contract

**From:** Person B **To:** Person A **Date:** 2026-08-28

Your contract is well above the usual integration doc: grounded in the real
files rather than the brief's idealisation, honest about what is still open,
and it picks the right seam. I have accepted the direction and **built against
it** - `docs/contract.md` is your document with amendments merged in, and every
clause in it is now enforced by a test in `tests/`.

Below is what I changed and why. Findings are numbered so we can argue about
them individually.

---

## What I kept, deliberately

- **The event table as the integration seam.** One row per closure is the right
  abstraction and it let me build the entire agent before your loader exists.
- **"The model never does arithmetic."** This is the strongest idea in either of
  our documents. It is now structural: `src/analytics/` cannot import a model,
  and `tests/test_agent.py::test_the_same_query_produces_the_same_report`
  fails if determinism ever breaks.
- **`{result, meta}` with mandatory `meta.n`.** Right instinct - `n` is what
  makes the confidence/limits section real instead of decorative. The report
  assembler computes that section from `n`, never from prose.
- **Return-don't-throw on empty results.** The orchestrator depends on it.
- **Pool = ordered, stitched stream.** Genuine correctness trap, well caught.
- **Your success-rate denominator proposal.** Adopted as-is; see F-DEN below.

Your arithmetic checks out too: 36 heads x 3 + 1 = 109 columns, 86,400 rows =
1 Hz for a day. I have not been able to verify these against the CSVs myself -
see "What I still need".

---

## Blocking findings (fixed in `docs/contract.md`)

**F1 - There was no load interface.** Every tool takes `events` as its first
argument, but nothing specified the function that *produces* that DataFrame. I
could not have written a line of agent code. Added as contract section 4 and
stubbed at `src/ingestion/api.py`: `list_pools`, `load_pool`, `pool_meta`.

`pool_meta` is not a nicety - the report's "data used" section and the
orchestrator's ambiguity handling both read it. It also carries
`rows_read` / `rows_after_cleaning` / `duplicates_removed`, for the reason in F7.

**F2 - The contract erased half my job, and contradicts our plan.** Section 2
opened "Every analysis function *Person A writes*...". But the plan's own split
table gives me the WP2 KPI half - success rates, per-head aggregation, time
bucketing, filtering, idle, dedup. So I write tools too, the envelope is my
format as much as yours, and `analytics.idle_window_seconds` feeds *my* tool
even though the section is labelled yours. Config ownership is per key, not per
section. Also: you asked me to review the success-rate denominator, but success
rate is my function - you were asking me to review my own deliverable.

**F3 - No tool registry.** The planner needs a list of callable tools with typed
parameters. A `**params` signature gives me nothing to generate that from, and a
hand-maintained parallel schema list would have drifted within a week. Added
`src/common/registry.py`: `@tool(...)` registers a function, and
`get_tool_specs()` generates the planner's JSON schemas from the same
declaration the function is called with, so they cannot disagree. Register your
tools there and they become agent-callable with no further work.

**F4 - No shared parameter vocabulary.** With `**params` untyped, a planner will
emit `head`, `head_no`, `from_date`, `since` and dispatch fails at runtime. The
vocabulary is now frozen in `PARAM_VOCABULARY` and **registration fails at
import** if a tool invents a name. An alias table absorbs the obvious
near-misses and records the substitution in the trace.

**F5 - Timezone was asserted, not decided.** The schema said "datetime (UTC)".
Plant telemetry is almost certainly local plant time; converting to UTC shifts
closures across midnight and every per-day and per-shift KPI - mine - stops
matching what the operator saw. Decision: **plant-local naive timestamps**, tz
reported in `pool_meta`, and all bucketing through `src/common/timeutils.py` so
we cannot each write our own `.dt.floor()`.

**F6 - "+1 only" is an observation, not a rule.** True of your files; the
contract never said what the loader does when `delta > 1` (dropped poll) or
`delta < 0` (reset/wrap) - and your own plan flags counter wrap as *the hidden
difficulty*. Now specified, with a `count_delta` column so a report can say
"3 closures inferred from a dropped sample". Throughput sums `count_delta`,
not rows.

---

## Findings on graded requirements the contract dropped

These are the ones I would most like you to push back on if you disagree,
because they change your workload.

**F7 - Cleaning and dedup were declared unnecessary.** The contract says "data
is otherwise clean: no missing cells, no duplicate timestamps". But Q3 grades
this in **two of its five objectives**: *"Cleaning Agents ... specifically
addressing the mismatch between polling frequency and the actual production
cycle"* and *"Deduplication & Logic Filtering"*. The polling/cycle mismatch is
exactly your 1 Hz sampling against a slower capping cycle. A cleaning stage has
to exist, be named, and be *measured* - which is why `pool_meta` carries the
row counts and every report prints them, even when nothing was removed.

**F8 - No local persistence layer.** Q3 objective 1 is *"pull raw datasets from
the Cloud and manage a local data persistence layer"*. The config was a flat
list of local CSV paths. This is also my latency problem: re-parsing 57 MB per
chat question makes the demo unusable. One fix serves both - a Parquet event
cache (`data.cache_dir`, already in config.yaml) plus a thin sync step.

**F9 - No scalability evidence, and nobody owned it.** Q3 objective 5 asks us to
*demonstrate the agent approach handles increasing data volumes better than
monolithic scripts*, and the course rules explicitly forbid unmeasured claims
("our tool is fast"). I propose I own this: a harness over 1/2/4/8 day-files
measuring wall time and peak memory against a naive baseline script.

**F10 - "Multi-Agent System" vs one agent with tools.** Q3 is *titled* MAS and
lists "agent communication protocols and coordination models" as required
background. Your mechanism is better than a chatty multi-agent design and I am
not proposing to change it. I have renamed the components instead: Orchestrator
delegating to Ingestion, Cleaning, Analytics and KPI agents, each with a
declared message contract (the event table and the envelope, nothing else).
`@tool(agent=...)` records ownership and it surfaces in every trace line. This
costs us nothing and closes a gradeable gap.

---

## Smaller findings, all now in the contract

- **F11 - Status is probably a bitfield.** Your unseen codes pair as *n* / *n+1*
  (`2/3`, `4/5`, ... `64/65`). Bit 0 as the reject flag reproduces all three
  observed codes exactly - `65 == 64 | 1` - and explains why your own
  `reject_signal` column exists. Implemented that way, degrading to
  `Unknown (<code>)` rather than crashing. **You have the AROL code table and I
  do not: please confirm or refute.** If it is a flat enum, we revert the
  decoder and nothing else changes.
- **F12** - `pool_id` added; "compare February to March" had nothing to group by.
- **F13** - capping speed had no owner; it is `throughput`, mine.
- **F14** - `error` now always present, plus `ok`, so my dispatcher never
  branches on key existence.
- **F15** - `meta` extended with `tool`, `agent`, `params`, `elapsed_ms`,
  `data_window`, so the trace log is free rather than bolted on.
- **F16** - added `src/common/` for what belongs to neither of us, plus
  `.gitignore` (**the 57 MB CSVs must never be committed**), `requirements.txt`,
  and the plain-ASCII `README` the brief requires as a deliverable.
- **F17** - the contract existed only as a PDF. It is now
  `docs/contract.md` in git, where it can be edited and signed.
- **F19** - Q3 mentions an `angle` field the real files do not have. The loader
  should tolerate extra per-head columns rather than assume exactly three.

**F-DEN - your OPEN item 1, agreed.** Excluding No Load from the denominator is
right. Two additions: reports always state the denominator in words, and
`no_load_rate` is a KPI in its own right - sustained No Load means bottles are
not arriving, which is a real operational signal rather than noise. On the
synthetic pool the two denominators give 99.86% vs 91.05%. You were right that
it drives most of the numbers.

---

## One correction to my own work, for the record

My first anomaly detector used a robust z-score (median absolute deviation) on
per-head reject rates. It produced a false positive: with most heads sitting on
0 or 1 rejects, the MAD collapses to about 1e-6, so a head with 2 rejects
instead of 1 scored as a wild outlier. Any purely rate-based spread measure
ignores how many closures the rate was computed from.

Replaced with an exact binomial upper-tail test per head against the fleet
median rate, Bonferroni-corrected across heads. Precision and recall are now
both 1.0 against the injected fault, and there is a regression test for the
false-positive case. Worth knowing if you use a similar approach for
torque-based anomalies - the same trap applies to any small-count rate.

---

## What I still need from you

1. **The AROL telemetry spec** you quoted (48 heads, status codes 3, 4/5, 8/9,
   16/17, 32/33, 64). None of that is in the Q3 brief - it is not a document I
   have. It is what settles F11.
2. **The CSVs, or one day-file**, so I can run the conformance test against real
   output rather than only against my generator.
3. **Two verifications on the full stitched pools** (not per file): distinct
   status codes across all pools, and counts of `delta > 1` and `delta < 0`.
   A single occurrence turns F6 from hypothetical into a required loader rule.
4. **Confirmation of the shift boundaries** (currently 06/14/22, provisional).

## What you can use immediately

- `src/testing/synth.py` - the synthetic generator, with ground truth. This is
  the fixture your Phase-4 precision/recall evaluation runs against.
  `generate()` returns `(events, ground_truth)`; ground truth names every
  injected fault, its head and its window.
- `src/common/registry.py` - register your tools and they become agent-callable.
- `src/common/schema.py` - `validate_events()` is the one assertion that makes
  the synthetic-to-real swap safe. Run it on your loader's output.
