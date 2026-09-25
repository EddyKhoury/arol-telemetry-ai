# AROL Telemetry AI

Analysis and scoped question answering for industrial AROL capping telemetry.
The system builds an event pool from **observed exact +1 counter changes**,
then runs deterministic analytics and writes a Markdown report and JSON trace.

## Set up

Use Python 3.12 from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest tests -q
```

The controlled evaluation creates its own small CSVs and needs no private
telemetry or Ollama server:

```bash
.venv/bin/python -m scripts.evaluate_agent
```

To check the **committed** project from a separate temporary checkout using
the current virtual environment, first ensure `git status --short` is empty:

```bash
.venv/bin/python -m scripts.check_clean_checkout
```

This check runs the test suite and the controlled evaluation, saves logs under
`data/release_review/`, and removes its temporary checkout. It does not
reinstall dependencies or validate the private dataset on a second machine.

## Demo with telemetry

The raw CSVs and generated event pools are local files under `data/`; they are
not part of Git. Build an event pool from locally available CSVs with
`.venv/bin/python -m scripts.build_event_pool --help`. For a complete pool
already present, run:

```bash
.venv/bin/python -m scripts.demo_agent --examples
.venv/bin/python -m scripts.demo_agent --question 'Average torque for head 5 for machine MCC777eda3db57348ef8a3113a642ae74db from 2026-02-01T00:00:00 until 2026-02-01T12:00:00 for successful closures'
```

If more than one pool exists, pass `--manifest PATH`. The demo uses verified
rule routing by default and writes a Markdown report and JSON trace for each
question under `data/demo_runs/`. See [the demo guide](docs/DEMO.md) for
scoped questions and [the evaluation guide](docs/EVALUATION.md) for the fixed
question set and its limitations.

## Evidence and limits

The integration work used 89 local CSVs, 36 heads and a pool of 54,722,936
**observed** exact +1 events. Its measurements, independent comparisons and
saved evidence are in [the project audit](docs/PROJECT-AUDIT.md),
[the integration tracker](docs/INTEGRATION-TRACKER.md) and
`benchmarks/integration/`. The 28-case controlled evaluation uses synthetic
signals and known supported wording. Its score does not measure accuracy on
arbitrary questions, estimate missed physical closures, infer downtime, or
establish fault causes. Local model routing has separate, more limited
evidence; the default demo uses deterministic rules.

## Project layout

- `src/ingestion/`: CSV processing and observed event-pool construction.
- `src/analytics/`: deterministic analysis tools and scoped statistics.
- `src/agent/`: planning, orchestration, reporting and traces.
- `scripts/`: pool builder, demo and verification commands.
- `tests/`: automated tests; `benchmarks/`: recorded evidence and fixed cases.
- `docs/`: demo, evaluation, contract and implementation audit.
