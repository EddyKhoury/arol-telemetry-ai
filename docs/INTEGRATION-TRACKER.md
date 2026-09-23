

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
