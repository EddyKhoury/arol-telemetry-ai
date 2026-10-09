"""Compare one bounded pool idle result against the original CSV status rows.

The reference loop reads CSV columns directly, never calls the production
idle detector, and verifies input hashes recorded by the pool builder.
"""

import argparse
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path

import polars as pl

from src.agent.orchestrator import Orchestrator
from src.ingestion.conversion import scan_csv_telemetry


def _hash(path):
    digest = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _reference(manifest, csv_dir, lo, hi, threshold):
    previous = start = last = None
    run = gaps = duplicates = count = all_no_load = 0
    periods = []

    def close():
        if run >= threshold:
            periods.append({'start': start.isoformat(),
                            'end': (last + timedelta(seconds=1)).isoformat(),
                            'duration_seconds': run, 'n_readings': run})

    for part in manifest['partitions']:
        if part['ts_min'] is None or part['ts_max'] < lo.isoformat() or part['ts_min'] >= hi.isoformat():
            continue
        source = csv_dir / part['input_file']
        if not source.is_file() or _hash(source) != part['input_sha256']:
            raise ValueError(f'Missing or changed original CSV: {source}')
        columns = scan_csv_telemetry(source).collect_schema().names()
        statuses = sorted(name for name in columns if name.endswith(' Status'))
        if len(statuses) != manifest['summary']['heads']:
            raise ValueError(f'Unexpected number of status columns: {source}')
        raw = scan_csv_telemetry(source).select(['timestamp', *statuses]).filter(
            (pl.col('timestamp') >= lo) & (pl.col('timestamp') < hi)).collect()
        for row in raw.iter_rows():
            ts, *codes = row
            yes = all(code in (2, 3) for code in codes)
            step = None if previous is None else (ts - previous).total_seconds()
            if step is not None:
                if step < 0:
                    raise ValueError('Original CSV timestamps go backwards')
                gaps += step > 1
                duplicates += step == 0
            if run and (not yes or step != 1):
                close()
                start = last = None
                run = 0
            if yes:
                if not run:
                    start = ts
                last = ts
                run += 1
                all_no_load += 1
            previous = ts
            count += 1
    if run:
        close()
    return {'idle_periods': periods, 'n_periods': len(periods),
            'total_idle_seconds': sum(p['duration_seconds'] for p in periods),
            'threshold_seconds': threshold, 'n_raw_readings': count,
            'n_all_heads_no_load': all_no_load, 'timestamp_gaps': gaps,
            'duplicate_timestamps': duplicates}


def verify(manifest_path, csv_dir, start, end, threshold=300):
    manifest_path, csv_dir = Path(manifest_path).resolve(), Path(csv_dir).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    lo, hi = datetime.fromisoformat(start), datetime.fromisoformat(end)
    if lo.tzinfo or hi.tzinfo or lo >= hi or type(threshold) is not int or threshold < 1:
        raise ValueError('Use naive stored timestamps, start < end, and a positive threshold')
    machine = manifest['summary']['machine_id']
    direct = _reference(manifest, csv_dir, lo, hi, threshold)
    cfg = {'data': {'source': 'person_a_pool', 'person_a': {'check': str(manifest_path)},
                    'max_loaded_events': max(1, direct['n_raw_readings'])},
           'agent': {'planner': 'rules', 'report_dir': str(manifest_path.parent / 'idle-check-reports'),
                     'trace_dir': str(manifest_path.parent / 'idle-check-traces')},
           'analytics': {'idle_window_seconds': threshold}}
    query = f'Machine idle for machine {machine} from {start} until {end}'
    result = Orchestrator(cfg=cfg).answer(query, pool='check')
    if result['status'] != 'ok':
        raise AssertionError(f"Idle orchestration failed: {result['status']} {result.get('message')}")
    actual = result['results'][0][1]['result']
    if actual != direct:
        raise AssertionError(f'CSV and pool idle results differ: CSV={direct!r}, pool={actual!r}')
    return {'matched': True, 'machine_id': machine, 'start': start, 'end': end,
            'threshold_seconds': threshold, 'n_raw_readings': direct['n_raw_readings'],
            'n_periods': direct['n_periods'], 'periods': direct['idle_periods'],
            'tool_calls': result['trace'].to_dict()['n_tool_calls']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--csv-dir', type=Path, required=True)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--threshold-seconds', type=int, default=300)
    args = parser.parse_args()
    print(json.dumps(verify(args.manifest, args.csv_dir, args.start, args.end,
                            args.threshold_seconds), indent=2))


if __name__ == '__main__':
    main()
