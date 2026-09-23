

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
