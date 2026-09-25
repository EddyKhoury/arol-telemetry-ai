"""Smoke-test the public CLI on the saved scoped real-data reference."""
import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess

from scripts.demo_agent import ROOT, main as demo_main

REFERENCE = ROOT / 'benchmarks/integration/torque_stats_scoped_real_2026-02-01.json'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != ROOT:
        parser.error('Run from the repository root')
    reference = json.loads(REFERENCE.read_text(encoding='utf-8'))
    query = reference['query']
    expected = reference['direct_statistics']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    capture = io.StringIO()
    with redirect_stdout(capture):
        code = demo_main(['--manifest', args.manifest, '--question', query,
                          '--json', '--output', str(ROOT / 'data/integration_smoke/demo-cli')])
    if code != 0:
        raise AssertionError('CLI query failed: ' + capture.getvalue())
    reply = json.loads(capture.getvalue())
    if reply['status'] != 'ok' or reply['planner'] != 'rules':
        raise AssertionError('The real demo did not complete with deterministic routing')
    if len(reply['results']) != 1 or reply['results'][0][0] != 'torque_stats':
        raise AssertionError('Unexpected demo tool plan')
    actual = reply['results'][0][1]['result']
    for key, value in expected.items():
        observed = actual[key]
        if (not math.isclose(observed, value, rel_tol=1e-12, abs_tol=1e-12)
                if isinstance(value, float) else observed != value):
            raise AssertionError(f'{key}: {observed} differs from saved independent reference {value}')
    if reply['results'][0][1]['meta']['params'] != reference['applied_parameters']:
        raise AssertionError('The command did not preserve the saved query scope')
    if reply['trace']['n_tool_calls'] != 1:
        raise AssertionError('Expected exactly one tool call in the trace')
    report, trace = (Path(reply['artifacts'][key]) for key in ('report', 'trace'))
    if report.read_text(encoding='utf-8') != reply['markdown']:
        raise AssertionError('Saved Markdown differs from displayed findings')
    if json.loads(trace.read_text(encoding='utf-8'))['n_tool_calls'] != 1:
        raise AssertionError('Saved trace does not record the executed tool')
    manifest = Path(args.manifest).resolve()
    evidence = {
        'git_commit_before_run': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'git_status_before_run': subprocess.check_output(['git', 'status', '--short'], text=True).strip(),
        'manifest': str(manifest.relative_to(ROOT)) if manifest.is_relative_to(ROOT) else str(manifest),
        'manifest_sha256': sha256(manifest), 'query': query,
        'source_code_sha256': {
            name: sha256(ROOT / name) for name in (
                'scripts/demo_agent.py', 'scripts/verify_demo_agent.py',
                'src/agent/orchestrator.py', 'src/common/event_pool_source.py')},
        'reference': str(REFERENCE.relative_to(ROOT)),
        'reference_sha256': sha256(REFERENCE),
        'planner': reply['planner'], 'status': reply['status'],
        'tool_calls': reply['trace']['n_tool_calls'],
        'statistics': actual, 'matches_prior_independent_reference': True,
        'artifacts': {key: str(Path(value).relative_to(ROOT))
                      for key, value in reply['artifacts'].items()},
        'limits': [
            'This is CLI/report/trace smoke verification against a previously independently checked query.',
            'It does not rerun the full independent CSV oracle or evaluate held-out language.',
            'The deterministic planner was used; no live model inference ran.',
            'Only observed exact +1 events; no counter discontinuity reconstruction or downtime inference.',
        ],
    }
    output = ROOT / 'benchmarks/integration' / f'demo_cli_{stamp}.json'
    output.write_text(json.dumps(evidence, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    heading = f'## Integration measurement — demo CLI {stamp}'
    text = (heading + '\n\n- The public command answered the verified H05 scoped torque question '
            'on the saved real event pool. Report, trace, scope and statistics matched the previous '
            'independent reference.\n- Rules planner; one tool call; no live model requests.\n'
            f'- Evidence: {output.relative_to(ROOT).as_posix()}.\n'
            '- Remaining diagnostic causes require explicit definitions; evaluate held-out queries and '
            'prepare the clean checkout before presenting.\n')
    for name in ('PROJECT-AUDIT.md', 'INTEGRATION-TRACKER.md'):
        path = ROOT / 'docs' / name
        path.write_text(path.read_text(encoding='utf-8').rstrip() + '\n\n' + text, encoding='utf-8')
    print('DEMO CLI REAL-DATA VERIFICATION PASSED')
    print(json.dumps({'status': reply['status'], 'tool_calls': reply['trace']['n_tool_calls'],
                      'sample_size': actual['sample_size'], 'statistics_match': True,
                      'report': evidence['artifacts']['report'],
                      'trace': evidence['artifacts']['trace'],
                      'evidence': str(output.relative_to(ROOT))}, indent=2))
    print('Updated both audit documents. Run git status --short.')


if __name__ == '__main__':
    main()
