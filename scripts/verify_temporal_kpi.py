"""Compare temporal reports with independent scalar counts and interval arithmetic."""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

import polars as pl
from polars.testing import assert_frame_equal
from src.agent.orchestrator import Orchestrator
from src.common import config, datasource
from src.common.envelope import jsonable
from src.ingestion.conversion import scan_csv_telemetry
from src.ingestion.event_table_polars import build_event_table_frame, EVENT_SCHEMA
from src.ingestion.event_pool import sha256_file
from scripts.verify_explicit_kpi import reference_counts
from scripts.verify_scoped_event_pool import equal

ROOT=Path(__file__).resolve().parents[1]


def reference_intervals(rows, start, end, bucket, min_n):
    lo, hi=datetime.fromisoformat(start),datetime.fromisoformat(end)
    origin=datetime(lo.year,lo.month,lo.day,lo.hour if bucket=='hour' else 0)
    step=timedelta(hours=1 if bucket=='hour' else 24)
    result=[]
    def add_rates(counts,seconds):
        return dict(counts,duration_seconds=seconds,observed_events_per_hour=counts['n_observed']/(seconds/3600),
                    cap_present_events_per_hour=counts['n_cap_present']/(seconds/3600),
                    successful_events_per_hour=counts['n_success_cap_present']/(seconds/3600))
    index=0
    while origin+index*step < hi:
        anchor=origin+index*step
        a,b=max(lo,anchor),min(hi,anchor+step)
        sample=[r for r in rows if a<=r['ts']<b]
        counts=reference_counts(sample,min_n)
        result.append(dict(calendar_bucket_start=anchor.isoformat(),bucket_start=a.isoformat(),bucket_end=b.isoformat(),
                           **add_rates(counts,(b-a).total_seconds()),has_observations=bool(sample)))
        index+=1
    return add_rates(reference_counts(rows,min_n),(hi-lo).total_seconds()),result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    args=parser.parse_args()
    if Path.cwd().resolve()!=ROOT:
        parser.error('Run from repository root')
    manifest_path=(ROOT/args.manifest).resolve()
    manifest_hash=sha256_file(manifest_path)
    manifest=json.loads(manifest_path.read_text())
    machine=manifest['summary']['machine_id']
    first=manifest['partitions'][0]
    csv=ROOT/'data'/first['input_file']
    if sha256_file(csv)!=first['input_sha256']:
        raise ValueError('Original CSV differs from the pool input')
    hashes={str(p.relative_to(ROOT)):sha256_file(p) for p in sorted((ROOT/'src').rglob('*.py'))}
    for name in ['scripts/verify_temporal_kpi.py','scripts/verify_explicit_kpi.py','scripts/verify_scoped_event_pool.py']:
        hashes[name]=sha256_file(ROOT/name)
    state={'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
           'git_status_before_run':subprocess.check_output(['git','status','--short'],text=True).strip(),
           'source_code_sha256':hashes}
    cfg=config.load()
    cfg['data'].update(source='person_a_pool',person_a={'full_pool':str(manifest_path)},max_loaded_events=1_000_000,verify_pool_hashes=False)
    cfg.setdefault('agent',{}).update(planner='rules',max_steps=8)
    min_n=cfg.get('analytics',{}).get('min_n',30)
    print('Building independent events from the first original CSV...',flush=True)
    original=build_event_table_frame(scan_csv_telemetry(csv),machine).collect()
    cases=[('hourly_kpis','success rate by hour','kpi_over_time','hour','2026-02-01T00:30:00','2026-02-01T03:15:00'),
           ('daily_observed_throughput','observed throughput by day','observed_throughput','day','2026-01-31T18:30:00','2026-02-01T12:15:00')]
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    run_dir=ROOT/'data/integration_smoke'/f'temporal-kpi-{stamp}'
    verified=[]
    for i,(name,base,tool,bucket,start,end) in enumerate(cases,1):
        query=base+f' for machine {machine} from {start} until {end}'
        params=dict(machine_id=machine,start=start,end=end,bucket=bucket)
        reference=original.filter((pl.col('ts')>=datetime.fromisoformat(start)) & (pl.col('ts')<datetime.fromisoformat(end)) & (pl.col('machine_id')==machine))
        rows=reference.select('ts','machine_id','head_id','status','error_class','cap_present','reject_signal').to_dicts()
        expected_total,expected_buckets=reference_intervals(rows,start,end,bucket,min_n)
        case_cfg=deepcopy(cfg)
        case_cfg['agent'].update(report_dir=str(run_dir/name/'reports'),trace_dir=str(run_dir/name/'traces'))
        source=datasource.get_source(case_cfg)
        load=source.load_for_plan
        captured=[]
        def record(pool,calls):
            frame,meta=load(pool,calls)
            captured.append(frame.select(list(EVENT_SCHEMA)))
            return frame,meta
        source.load_for_plan=record
        engine=Orchestrator(cfg=case_cfg,source=source)
        print(f'{i}/2 Verifying {name}...',flush=True)
        answer=engine.answer(query,pool='full_pool')
        assert answer['status']=='ok',answer.get('message')
        assert answer['plan'].calls==[(tool,params)]
        assert len(captured)==1
        assert_frame_equal(captured[0],reference)
        assert answer['pool_meta']['selection_parameters']=={k:v for k,v in params.items() if k!='bucket'}
        assert answer['pool_meta']['loaded_events']==len(reference)
        assert len(answer['results'])==1 and answer['trace'].to_dict()['n_tool_calls']==1
        response=answer['results'][0][1]
        assert response['ok'] and response['meta']['params']==params
        result=response['result']
        equal(result['overall'],expected_total)
        equal(result['by_bucket'],expected_buckets)
        assert result['n_buckets']==len(expected_buckets)
        assert result['requested_window']=={'start':start,'end':end}
        assert result['telemetry_coverage']=='not_established_from_event_table'
        assert 'do not establish zero production or machine downtime' in answer['markdown']
        assert response['meta']['n']==expected_total['n_observed' if tool=='observed_throughput' else 'n_cap_present']
        artifacts=engine.deliver(answer,formats=['markdown'])
        detail=run_dir/name/'buckets.json'
        detail.write_text(json.dumps(jsonable({'independent_total':expected_total,'independent_buckets':expected_buckets,'reported':result}),indent=2,allow_nan=False)+'\n')
        artifacts['buckets']=str(detail)
        verified.append(dict(case=name,query=query,parameters=params,loaded_events=len(reference),
                             n_buckets=len(expected_buckets),interval_seconds=[r['duration_seconds'] for r in expected_buckets],
                             observed_events_per_hour=expected_total['observed_events_per_hour'],
                             field_parity=True,all_bucket_counts_and_rates_match=True,
                             details_sha256=sha256_file(detail),
                             artifacts={k:Path(v).relative_to(ROOT).as_posix() for k,v in artifacts.items()}))
        print(f'    PASS: {len(reference):,} events; {len(expected_buckets)} buckets; all counts, durations and rates match.',flush=True)
    if sha256_file(manifest_path)!=manifest_hash or any(sha256_file(ROOT/n)!=v for n,v in hashes.items()):
        raise RuntimeError('Source or manifest changed during verification')
    evidence={**state,'verified':True,'manifest':args.manifest,'manifest_sha256':manifest_hash,
              'input_csv_sha256':first['input_sha256'],'real_queries':verified,'planner':'rules','live_model_requests':0,
              'float_tolerance':{'relative':1e-12,'absolute':1e-12},
              'limits':['Observed-event rates over requested duration, not total production or active-operating-time throughput.',
                        'Event rows do not establish telemetry coverage or machine downtime in empty intervals.',
                        'Two scopes from one original CSV were checked; timezone/DST elapsed-time semantics remain unconfirmed.',
                        'No shift calendars, week buckets, idle classification or new LLM routing.']}
    output=ROOT/'benchmarks/integration'/f'temporal_kpi_{stamp}.json'
    output.write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n')
    entry=(f'## Integration measurement — temporal KPIs {stamp}\n\n'
           '- Hourly KPIs and daily observed-event throughput matched independent scalar counts and requested-interval arithmetic.\n'
           '- Partial intervals were clipped to requested bounds; all bucket counts reconciled with totals. Event fields and scope were preserved.\n'
           '- Reports distinguish recorded-event rates from production completeness, telemetry coverage and machine downtime.\n'
           f'- Evidence: {output.relative_to(ROOT)}.\n'
           '- No live model calls. Timezone/operating schedules, idle classification and broader evaluation remain pending.\n')
    for name in ['PROJECT-AUDIT.md','INTEGRATION-TRACKER.md']:
        p=ROOT/'docs'/name
        p.write_text(p.read_text().rstrip()+'\n\n'+entry)
    print('\nTEMPORAL KPI VERIFICATION COMPLETE')
    print(json.dumps(verified,indent=2))
    print(f'Evidence: {output.relative_to(ROOT)}')
    print('Updated both audit documents. Run git status --short.')


if __name__=='__main__':
    main()
