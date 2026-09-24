"""Verify scoped KPI orchestration with independent Python counts and saved full-pool counts."""
import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import polars as pl
from polars.testing import assert_frame_equal

from src.agent.orchestrator import Orchestrator
from src.common import config, datasource
from src.ingestion.conversion import scan_csv_telemetry
from src.ingestion.event_table_polars import build_event_table_frame, EVENT_SCHEMA
from src.ingestion.event_pool import sha256_file
from src.analytics.registered_kpi import finish_counts
from scripts.verify_scoped_event_pool import equal

ROOT = Path(__file__).resolve().parents[1]


def reference_counts(rows, min_n):
    """Independent scalar oracle; rows can be individual or previously grouped."""
    def count(predicate):
        return sum(int(r.get('n', 1)) for r in rows if predicate(r))
    cap = count(lambda r: r['cap_present'] is True)
    total = count(lambda r: True)
    success = count(lambda r: r['status'] == 0)
    success_cap = count(lambda r: r['status'] == 0 and r['cap_present'] is True)
    reject_cap = count(lambda r: r['reject_signal'] is True and r['cap_present'] is True)
    a_den = count(lambda r: r['error_class'] is not None and r['error_class'] != 'No Load')
    a_num = count(lambda r: r['status'] == 0 and r['error_class'] is not None and r['error_class'] != 'No Load')
    no_load = count(lambda r: r['error_class'] == 'No Load')
    return {
        'n_observed': total, 'n_cap_present': cap,
        'n_cap_absent': count(lambda r: r['cap_present'] is False),
        'n_cap_unknown': count(lambda r: r['cap_present'] is None),
        'n_success_all': success, 'n_success_cap_present': success_cap,
        'n_success_outside_cap_present': success-success_cap,
        'n_reject_all': count(lambda r: r['reject_signal'] is True),
        'n_reject_cap_present': reject_cap,
        'n_reject_outside_cap_present': count(lambda r: r['reject_signal'] is True and r['cap_present'] is not True),
        'n_reject_unknown': count(lambda r: r['reject_signal'] is None),
        'n_no_load_class': no_load, 'n_legacy_a_non_no_load': a_den, 'n_legacy_a_success': a_num,
        'success_rate_cap_present': success_cap/cap if cap else None,
        'reject_rate_cap_present': reject_cap/cap if cap else None,
        'success_fraction_all_observed': success/total if total else None,
        'no_load_fraction_all_observed': no_load/total if total else None,
        'legacy_a_success_rate_non_no_load': a_num/a_den if a_den else None,
        'min_cap_present_n': min_n, 'below_min_cap_present_n': cap < min_n,
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--audit', required=True)
    args=parser.parse_args()
    if Path.cwd().resolve()!=ROOT:
        parser.error('Run from repository root')
    manifest_path=(ROOT/args.manifest).resolve()
    manifest=json.loads(manifest_path.read_text())
    audit_path=(ROOT/args.audit).resolve()
    audit=json.loads(audit_path.read_text())
    if sha256_file(manifest_path)!=audit['manifest_sha256']:
        raise ValueError('The saved denominator audit describes a different manifest')
    hashes={str(p.relative_to(ROOT)):sha256_file(p) for p in sorted((ROOT/'src').rglob('*.py'))}
    hashes['scripts/verify_explicit_kpi.py']=sha256_file(Path(__file__))
    hashes['scripts/verify_scoped_event_pool.py']=sha256_file(ROOT/'scripts/verify_scoped_event_pool.py')
    state={'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
           'git_status_before_run':subprocess.check_output(['git','status','--short'],text=True).strip(),
           'source_code_sha256':hashes}
    cfg=config.load()
    min_n=cfg.get('analytics',{}).get('min_n',30)
    # Validate the new rate arithmetic against saved FULL-POOL grouped counts.
    # This does not claim that the full pool was loaded by the orchestrator.
    audit_reference=reference_counts(audit['grouped_counts'],min_n)
    if audit_reference['n_observed'] != manifest['summary']['observed_events']:
        raise ValueError('Audit grouped counts do not sum to the configured pool total')
    arithmetic=finish_counts({k:v for k,v in audit_reference.items() if k.startswith('n_')},min_n)
    equal(arithmetic,audit_reference)
    summary=audit['summary']
    for key, old_key in [('n_legacy_a_non_no_load','a_non_no_load_denominator'),
                         ('n_cap_present','b_cap_present_denominator'),
                         ('n_success_all','b_success_numerator'),
                         ('n_reject_outside_cap_present','reject_true_outside_cap_present')]:
        assert audit_reference[key]==summary[old_key]
    print('1/3 Full-pool saved-count arithmetic verified (no full-pool orchestration claimed).',flush=True)
    machine=manifest['summary']['machine_id']
    first=manifest['partitions'][0]
    csv=ROOT/'data'/first['input_file']
    if sha256_file(csv)!=first['input_sha256']:
        raise ValueError('Original CSV hash does not match the manifest')
    print('2/3 Building an independent all-status reference for the twelve-hour window...',flush=True)
    reference=build_event_table_frame(scan_csv_telemetry(csv),machine).filter(
        (pl.col('machine_id')==machine) & (pl.col('ts')>=datetime(2026,2,1)) & (pl.col('ts')<datetime(2026,2,1,12))
    ).collect()
    cfg['data'].update(source='person_a_pool',person_a={'full_pool':str(manifest_path)},max_loaded_events=1_000_000,verify_pool_hashes=False)
    cfg.setdefault('agent',{}).update(planner='rules',max_steps=8)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    run_dir=ROOT/'data/integration_smoke'/f'explicit-kpi-{stamp}'
    scope=dict(machine_id=machine,start='2026-02-01T00:00:00',end='2026-02-01T12:00:00')
    cases=[('head_kpis','success rate for head 5',dict(scope,head_id='H05'),['success_rate','success_rate_per_head']),
           ('per_head_kpis','success rate per head',dict(scope),['success_rate_per_head'])]
    verified=[]
    print('3/3 Verifying real KPI questions, including all selected heads...',flush=True)
    for name,base,params,tools in cases:
        query=base+f" for machine {machine} from {scope['start']} until {scope['end']}"
        expected_frame=reference.filter(pl.col('head_id')==params['head_id']) if 'head_id' in params else reference
        # Only scalar status/flag fields are materialised as Python objects.
        rows=expected_frame.select('machine_id','head_id','status','error_class','cap_present','reject_signal').to_dicts()
        expected=reference_counts(rows,min_n)
        groups=defaultdict(list)
        for row in rows:
            groups[(row['machine_id'],row['head_id'])].append(row)
        expected_heads=[dict(machine_id=m,head_id=h,**reference_counts(part,min_n)) for (m,h),part in sorted(groups.items())]
        case_cfg=deepcopy(cfg)
        case_cfg['agent'].update(report_dir=str(run_dir/name/'reports'),trace_dir=str(run_dir/name/'traces'))
        source=datasource.get_source(case_cfg)
        original=source.load_for_plan
        captured=[]
        def capture(pool,calls):
            events,meta=original(pool,calls)
            captured.append(events.select(list(EVENT_SCHEMA)))
            return events,meta
        source.load_for_plan=capture
        engine=Orchestrator(cfg=case_cfg,source=source)
        answer=engine.answer(query,pool='full_pool')
        assert answer['status']=='ok',answer.get('message')
        assert answer['plan'].calls==[(tool,params) for tool in tools]
        assert len(captured)==1
        assert_frame_equal(captured[0],expected_frame)
        assert answer['pool_meta']['loaded_events']==expected['n_observed']
        assert answer['trace'].to_dict()['n_tool_calls']==len(tools)
        assert len(answer['results'])==len(tools)
        for (tool,response),expected_tool in zip(answer['results'],tools):
            assert tool==expected_tool and response['ok']
            assert response['meta']['params']==params
            assert response['meta']['n']==expected['n_cap_present']
            equal(response['result']['overall'],expected)
            if tool=='success_rate_per_head':
                equal(response['result']['per_head'],expected_heads)
                assert response['result']['n_head_groups']==len(expected_heads)
                assert response['result']['n_groups_below_min_cap_present_n']==sum(r['below_min_cap_present_n'] for r in expected_heads)
        assert 'Cap-present rejection flags' in answer['markdown']
        assert 'Legacy A non-No-Load' in answer['markdown']
        artifacts=engine.deliver(answer,formats=['markdown'])
        detail=run_dir/name/'counts.json'
        detail.write_text(json.dumps({'direct':expected,'direct_per_head':expected_heads,'reported':answer['results']},indent=2,allow_nan=False)+'\n')
        artifacts['counts']=str(detail)
        verified.append({'case':name,'query':query,'parameters':params,'loaded_events':expected['n_observed'],
                         'cap_present_n':expected['n_cap_present'],'machine_head_groups':len(expected_heads),
                         'field_parity':True,'all_counts_and_rates_match':True,'tool_calls':len(tools),
                         'counts_sha256':sha256_file(detail),
                         'artifacts':{k:Path(v).relative_to(ROOT).as_posix() for k,v in artifacts.items()}})
        print(f"    PASS {name}: {expected['n_observed']:,} observed events, {expected['n_cap_present']:,} cap-present, {len(expected_heads)} groups.",flush=True)
    assert sha256_file(manifest_path)==audit['manifest_sha256']
    if any(sha256_file(ROOT/name)!=digest for name,digest in hashes.items()):
        raise RuntimeError('Source changed during verification')
    evidence={**state,'manifest':args.manifest,'audit':args.audit,'audit_sha256':sha256_file(audit_path),
              'full_pool_saved_count_arithmetic':arithmetic,'real_queries':verified,'verified':True,
              'planner':'rules','live_model_requests':0,'float_tolerance':{'relative':1e-12,'absolute':1e-12},
              'limits':['Full-pool arithmetic checked on saved grouped counts; orchestration checked on one real twelve-hour window.',
                        'All rates describe observed exact +1 events, not total production.',
                        'No head ranking, fault-cause validation, time buckets or live LLM KPI routing.']}
    output=ROOT/'benchmarks/integration'/f'explicit_kpi_{stamp}.json'
    output.write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n')
    entry=(f'## Integration measurement — explicit KPI rates {stamp}\n\n'
           '- Saved full-pool grouped counts verified the new denominator arithmetic, including rejects outside the cap-present population.\n'
           '- Two real scoped questions matched independent Python counts and rates, including per-machine/head groups.\n'
           '- Event fields and requested scope were preserved; reports and traces were saved.\n'
           '- Deterministic routing only. This does not establish full-pool agent execution, head ranking or fault causes.\n'
           f'- Evidence: {output.relative_to(ROOT)}.\n'
           '- Next action: record the regression result and review remaining diagnostic requirements.\n')
    for name in ['PROJECT-AUDIT.md','INTEGRATION-TRACKER.md']:
        p=ROOT/'docs'/name
        p.write_text(p.read_text().rstrip()+'\n\n'+entry)
    print('\nEXPLICIT KPI VERIFICATION COMPLETE')
    print(json.dumps(verified,indent=2))
    print(f'Evidence: {output.relative_to(ROOT)}')
    print('Updated both audit documents. Run git status --short.')


if __name__=='__main__':
    main()
