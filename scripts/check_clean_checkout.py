"""Run tests and the controlled evaluation from a temporary checkout.

Use the currently active project environment. This check neither installs
dependencies nor reads the private telemetry files in the working checkout.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    return subprocess.check_output(
        ['git', *args], cwd=ROOT, text=True, stderr=subprocess.PIPE,
    ).strip()


def run_case(label: str, command: list[str], checkout: Path, logs: Path) -> dict:
    environment = os.environ.copy()
    environment['PYTHONPATH'] = str(checkout)
    try:
        completed = subprocess.run(
            command, cwd=checkout, env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=180, check=False,
        )
        content = completed.stdout
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        content = exc.stdout or b''
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='replace')
        content += '\nTimed out after 180 seconds.\n'
        exit_code = 124
    path = logs / f'{label}.log'
    path.write_text(content, encoding='utf-8')
    print(f'\n{label}: {"PASS" if exit_code == 0 else "FAIL"} (exit {exit_code})')
    print('\n'.join(content.rstrip().splitlines()[-12:]))
    return {'exit_code': exit_code, 'log': str(path.relative_to(ROOT))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    if Path.cwd().resolve() != ROOT:
        parser.error('Run from the repository root.')
    if Path(git('rev-parse', '--show-toplevel')).resolve() != ROOT:
        parser.error('This script must run inside its own Git checkout.')
    status = git('status', '--porcelain', '--untracked-files=normal')
    if status:
        parser.error('Commit or set aside tracked and untracked changes first.')
    commit = git('rev-parse', 'HEAD')
    session = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    logs = ROOT / 'data' / 'release_review' / f'{session}-{uuid4().hex[:8]}'
    logs.mkdir(parents=True, exist_ok=False)
    outcomes: dict = {'source_commit': commit, 'python': sys.executable,
                      'isolation': 'temporary detached Git worktree; existing virtualenv',
                      'private_csv_used': False, 'logs': str(logs.relative_to(ROOT))}
    checkout_added = False
    with tempfile.TemporaryDirectory(prefix='arol-fresh-checkout-') as directory:
        checkout = Path(directory) / 'checkout'
        try:
            subprocess.run(['git', 'worktree', 'add', '--quiet', '--detach',
                            str(checkout), commit], cwd=ROOT, check=True)
            checkout_added = True
            paths = ('README.MD', 'docs/DEMO.md', 'docs/EVALUATION.md',
                     'scripts/demo_agent.py', 'scripts/evaluate_agent.py')
            missing = [name for name in paths if not (checkout / name).is_file()]
            if missing:
                raise RuntimeError(f'Missing tracked release files: {missing}')
            print('1/2 Running the full tests from a detached checkout...', flush=True)
            outcomes['tests'] = run_case(
                'tests', [sys.executable, '-m', 'pytest', 'tests', '-q'], checkout, logs)
            if outcomes['tests']['exit_code'] != 0:
                outcomes['evaluation'] = {'skipped': 'Tests failed.'}
            else:
                print('2/2 Running the 28-case controlled evaluation...', flush=True)
                outcomes['evaluation'] = run_case(
                    'evaluation', [sys.executable, '-m', 'scripts.evaluate_agent'],
                    checkout, logs)
        except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
            outcomes['setup_error'] = f'{type(exc).__name__}: {exc}'
        finally:
            if checkout_added:
                try:
                    subprocess.run(['git', 'worktree', 'remove', '--force',
                                    str(checkout)], cwd=ROOT, check=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                except subprocess.CalledProcessError as exc:
                    outcomes['cleanup_error'] = exc.stderr.decode(errors='replace')
                    print(f'Worktree cleanup failed: {exc.stderr.decode(errors="replace")}')
    outcomes['passed'] = (
        outcomes.get('tests', {}).get('exit_code') == 0
        and outcomes.get('evaluation', {}).get('exit_code') == 0
        and not outcomes.get('setup_error') and not outcomes.get('cleanup_error')
    )
    outcomes['limits'] = (
        'This reuses the installed environment. It does not test dependency installation, '
        'the private 89-file event pool, or live Ollama inference.'
    )
    path = logs / 'summary.json'
    path.write_text(json.dumps(outcomes, indent=2) + '\n', encoding='utf-8')
    print(f'\nCLEAN CHECKOUT: {"PASS" if outcomes["passed"] else "FAIL"}')
    print(f'Summary: {path.relative_to(ROOT)}')
    print('Temporary checkout removed. Current branch and private data were untouched.')
    return 0 if outcomes['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
