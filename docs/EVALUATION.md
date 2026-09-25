# Controlled agent evaluation

Run from the repository root after the full tests pass:

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -m scripts.evaluate_agent
```

The evaluator reads the fixed questions in
`benchmarks/evaluation/prompts_v1.json`. These are **16 new supported
phrasings** with exact expected tool names and arguments, plus **12 requests
that should stop for clarification**. It records each result, including any
failure, in `benchmarks/integration/agent_evaluation_*.json`. Complete case
results, reports, traces, synthetic CSVs and the event-pool manifest are saved
under ignored `data/integration_smoke/agent-evaluation-*/`.

The run creates two tiny synthetic telemetry CSVs with four heads. Each head
has twelve observed exact +1 events. Four events per machine occur at the
boundary between CSVs. H05 has four status-65 events, eight status-0 events,
and two torque measurements deliberately outside the configured 1.5–2.5 Nm
interval. The other three heads have twelve status-0 events each. An
independent scalar CSV scan checks the event count, boundary carry, status,
torque and decoded fields before any question is evaluated.

For every supported question, the evaluator checks the complete plan, selected
scope, tool response, report, trace and the planted signals where applicable.
The resulting head ranking is a descriptive cap-present success comparison;
threshold flags identify the planted values. Neither result establishes why
a head failed, whether the machine was operating, or whether other physical
closures were missed. Ambiguous requests must produce zero tool calls and must
not open the event pool. No live LLM request is made.

This set is new relative to the original 30 diagnostic questions, but the
authors knew the supported grammar while writing it. Its pass rate is a
controlled integration measure, **not** an estimate of success on arbitrary
language. The earlier real-data and live-model evidence remains separate in
`benchmarks/integration/`. A presentation should show the case results and a
saved trace as well as any score; report unexpected failures rather than
silently deleting a case.
