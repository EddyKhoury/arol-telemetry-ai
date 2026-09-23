

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
