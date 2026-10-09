# AROL integrated agent demo

Run from the repository root with the project's Python environment. The event
pool contains observed exact +1 counter events from the supplied CSVs. It is
generated data under `data/`, so a new checkout needs the original telemetry
files and a locally built pool before the demo can run. The 89-file pool used
for the integration checks is at
`data/event_pools/continuous-20260924-080513-930170/manifest.json` on the
verification machine. The code never downloads the raw data.

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -m scripts.demo_agent --examples
.venv/bin/python -m scripts.demo_agent --question \
  'Average torque for head 5 for machine MCC777eda3db57348ef8a3113a642ae74db from 2026-02-01T00:00:00 until 2026-02-01T12:00:00 for successful closures'
```

Without `--question` the command opens an interactive prompt; type `exit` to
finish. It selects the sole complete manifest under `data/event_pools/`. If you
have more than one local pool, supply `--manifest data/event_pools/.../manifest.json`.
Each question writes a Markdown report and JSON trace into a separate folder
inside a new session under `data/demo_runs/`. The directory is ignored by Git.
Use `--output DIR` to select another parent directory. Add `--json` to a
scripted `--question` for one JSON object per question. A command with any
clarification or degraded outcome exits with status 2 and still saves a trace.
Pass `--plots` on a chartable analysis to save PNG figures linked from the
Markdown report. A fresh checkout also includes three [synthetic sample
reports](samples/README.md) with figures and a documented generator.

To compare one short idle window directly with the original CSV status rows
after installing this update, run from the project root (change `--csv-dir`
if the 89 original telemetry CSVs are elsewhere):

```bash
.venv/bin/python -m scripts.verify_idle_real \
  --manifest data/event_pools/continuous-20260924-080513-930170/manifest.json \
  --csv-dir data \
  --start 2026-02-01T15:55:00 --end 2026-02-01T16:05:00
```

It checks the original CSV hashes in the manifest and compares an independent
raw-status loop with the integrated `machine_idle` result. A matching result
with zero qualifying periods verifies this window's computation; it does not
establish whether there was a qualifying idle interval elsewhere in the pool.

Try a bounded success-rate question or a daily observed-throughput question:

```bash
.venv/bin/python -m scripts.demo_agent --question \
  'Success rate for head 5 for machine MCC777eda3db57348ef8a3113a642ae74db from 2026-02-01T00:00:00 until 2026-02-01T12:00:00'
.venv/bin/python -m scripts.demo_agent --question \
  'Observed throughput by hour for machine MCC777eda3db57348ef8a3113a642ae74db from 2026-02-01T00:00:00 until 2026-02-01T01:00:00'
.venv/bin/python -m scripts.demo_agent --plots --question \
  'Machine idle for machine MCC777eda3db57348ef8a3113a642ae74db from 2026-02-01T00:00:00 until 2026-02-01T01:00:00'
```

The default planner is deterministic rules. `--planner llm` requests the
configured local model and currently permits only the five previously checked
single torque analyses. Validation refuses model proposals that change the
requested tool or scope; transport fallback, when enabled, appears in the
trace. Other analyses remain available through the deterministic planner.

The event source caps loaded rows using `data.max_loaded_events` (default
1,000,000). A broad request asks for narrower scope without collecting the
entire 54,722,936-event pool. Capping KPIs report explicit cap-present
denominators and unknowns. Throughput measures recorded exact +1 events per
requested duration; it does not measure total physical production, sensor
coverage, operating time, downtime, or fault causes. Timestamps use stored
naive values; their timezone and daylight-saving semantics are unconfirmed.

For a fresh checkout with the original CSVs available locally, build a pool
once with `python -m scripts.build_event_pool --help`; do not put raw telemetry
or built pools in Git. The project audit and `benchmarks/integration/` contain
the reproducible comparison methods and results from the verification machine.
