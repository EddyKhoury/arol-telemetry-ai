"""Verify descriptive ranking and focus-versus-peer reports on real scoped events."""
import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
from functools import cmp_to_key
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
from scripts.verify_explicit_kpi import reference_counts
from scripts.verify_scoped_event_pool import equal

ROOT=Path(__file__).resolve().parents[1]


def independent_ranks(per_head, min_n):
    eligible=[dict(r) for r in per_head if r['n_cap_present']>=min_n]
    excluded=[dict(r) for r in per_head if r['n_cap_present']<min_n]
    def compare(a,b):
        left=a['n_success_cap_present']*b['n_cap_present']
        right=b['n_success_cap_present']*a['n_cap_present']
        return (left>right)-(left<right) or ((a['head_id']>b['head_id'])-(a['head_id']<b['head_id']))
    eligible.sort(key=cmp_to_key(compare))
    for row in eligible:
        lesser=sum(other['n_success_cap_present']*row['n_cap_present'] < row['n_success_cap_present']*other['n_cap_present'] for other in eligible)
        row.update(eligible_for_ranking=True,exclusion_reason=None,
                   rank_lowest_success_first=1+lesser if len(eligible)>=2 else None)
    for row in excluded:
        row.update(eligible_for_ranking=False,exclusion_reason='insufficient_cap_present_sample',rank_lowest_success_first=None)
    return eligible+sorted(excluded,key=lambda r:r['head_id'])


def independent_comparison(rows, head):
    focus=next((r for r in rows if r['head_id']==head),None)
    peers=[r for r in rows if r['head_id']!=head and r['eligible_for_ranking']]
    reason=('focus_head_not_found' if focus is None else 'focus_below_minimum_sample' if not focus['eligible_for_ranking']
            else 'fewer_than_two_eligible_peers' if len(peers)<2 else None)
    baseline=delta=None
    if reason is None:
        values=sorted(Fraction(r['n_success_cap_present'],r['n_cap_present']) for r in peers)
        n=len(values)
        middle=values[n//2] if n%2 else (values[n//2-1]+values[n//2])/2
        baseline=float(middle)
        delta=float(100*(Fraction(focus['n_success_cap_present'],focus['n_cap_present'])-middle))
    return dict(focus_head_id=head,focus=focus,eligible_peer_heads=[r['head_id'] for r in peers],n_eligible_peers=len(peers),
                peer_median_success_rate=baseline,difference_from_peer_median_pp=delta,
                comparison_available=reason is None,comparison_reason=reason)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    args=parser.parse_args()
    if Path.cwd().resolve()!=ROOT:
        parser.error('Run from the repository root')
    path=(ROOT/args.manifest).resolve()
    manifest_hash=sha256_file(path)
    manifest=json.loads(path.read_text())
    machine=manifest['summary']['machine_id']
    first=manifest['partitions'][0]
    csv=ROOT/'data'/first['input_file']
    if sha256_file(csv)!=first['input_sha256']:
        raise ValueError('Original CSV differs from the manifest')
    hashes={str(p.relative_to(ROOT)):sha256_file(p) for p in sorted((ROOT/'src').rglob('*.py'))}
    for name in ['scripts/verify_head_kpi.py','scripts/verify_explicit_kpi.py','scripts/verify_scoped_event_pool.py']:
        hashes[name]=sha256_file(ROOT/name)
    state={'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
           'git_status_before_run':subprocess.check_output(['git','status','--short'],text=True).strip(),
           'source_code_sha256':hashes}
    cfg=config.load()
    min_n=cfg.get('analytics',{}).get('min_n',30)
    scope=dict(machine_id=machine,start='2026-02-01T00:00:00',end='2026-02-01T12:00:00')
    print('Building independent per-head counts from the first original CSV...',flush=True)
    original=build_event_table_frame(scan_csv_telemetry(csv),machine).filter(
        (pl.col('machine_id')==machine)&(pl.col('ts')>=datetime(2026,2,1))&(pl.col('ts')<datetime(2026,2,1,12))
    ).collect()
    rows=original.select('machine_id','head_id','status','error_class','cap_present','reject_signal').to_dicts()
    groups=defaultdict(list)
    for row in rows:
        groups[(row['machine_id'],row['head_id'])].append(row)
    reference=[dict(machine_id=m,head_id=h,**reference_counts(part,min_n)) for (m,h),part in sorted(groups.items())]
    ranked=independent_ranks(reference,min_n)
    overall=reference_counts(rows,min_n)
    comparison=independent_comparison(ranked,'H05')
    cfg['data'].update(source='person_a_pool',person_a={'full_pool':str(path)},max_loaded_events=1_000_000,verify_pool_hashes=False)
    cfg.setdefault('agent',{}).update(planner='rules',max_steps=8)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    run_dir=ROOT/'data/integration_smoke'/f'head-kpi-{stamp}'
    cases=[('ranking','rank heads by cap-present success rate','rank_heads_by_success',dict(scope)),
           ('focus_vs_peers','compare head 5 with peers by cap-present success rate','compare_head_success',dict(scope,head_id='H05'))]
    verified=[]
    for i,(name,base,tool,params) in enumerate(cases,1):
        query=base+f" for machine {machine} from {scope['start']} until {scope['end']}"
        print(f'{i}/2 Verifying {name}...',flush=True)
        case_cfg=deepcopy(cfg)
        case_cfg['agent'].update(report_dir=str(run_dir/name/'reports'),trace_dir=str(run_dir/name/'traces'))
        source=datasource.get_source(case_cfg)
        load=source.load_for_plan
        captured=[]
        def record(pool,calls):
            events,meta=load(pool,calls)
            captured.append(events.select(list(EVENT_SCHEMA)))
            return events,meta
        source.load_for_plan=record
        engine=Orchestrator(cfg=case_cfg,source=source)
        answer=engine.answer(query,pool='full_pool')
        assert answer['status']=='ok',answer.get('message')
        assert answer['plan'].calls==[(tool,params)]
        assert len(captured)==1
        assert_frame_equal(captured[0],original)
        assert answer['pool_meta']['selection_parameters']==scope
        assert answer['pool_meta']['comparison_population']==scope
        assert answer['pool_meta']['comparison_focus_head']==params.get('head_id')
        assert answer['pool_meta']['loaded_events']==len(original)
        assert len(answer['results'])==1 and answer['trace'].to_dict()['n_tool_calls']==1
        response=answer['results'][0][1]
        assert response['ok'] and response['meta']['params']==params
        assert response['meta']['n']==overall['n_cap_present']
        result=response['result']
        equal(result['overall'],overall)
        equal(result['ranked_heads'],ranked)
        assert result['n_head_groups']==len(reference)
        assert result['n_eligible_heads']==sum(r['eligible_for_ranking'] for r in ranked)
        assert result['ranking_available']==(result['n_eligible_heads']>=2)
        assert result['population_scope']==scope
        if tool=='compare_head_success':
            equal({key:result[key] for key in comparison},comparison)
            assert 'head_id identifies the focus' in answer['markdown']
        assert 'not a statistical anomaly test or a fault diagnosis' in answer['markdown']
        artifacts=engine.deliver(answer,formats=['markdown'])
        detail=run_dir/name/'comparison.json'
        detail.write_text(json.dumps({'independent_ranked_heads':ranked,'independent_comparison':comparison,'reported':result},indent=2,allow_nan=False)+'\n')
        artifacts['comparison']=str(detail)
        verified.append(dict(case=name,query=query,parameters=params,loaded_events=len(original),
                             n_heads=len(reference),n_eligible_heads=result['n_eligible_heads'],
                             field_parity=True,counts_ranks_and_peer_comparison_match=True,
                             comparison_available=result.get('comparison_available'),
                             focus_difference_pp=result.get('difference_from_peer_median_pp'),
                             detail_sha256=sha256_file(detail),
                             artifacts={k:Path(v).relative_to(ROOT).as_posix() for k,v in artifacts.items()}))
        print(f"    PASS: {len(original):,} events; {len(reference)} heads; eligible={result['n_eligible_heads']}; counts and ranks match.",flush=True)
    if sha256_file(path)!=manifest_hash or any(sha256_file(ROOT/n)!=v for n,v in hashes.items()):
        raise RuntimeError('Source or manifest changed during verification')
    evidence={**state,'manifest':args.manifest,'manifest_sha256':manifest_hash,'input_csv_sha256':first['input_sha256'],
              'verified':True,'real_queries':verified,'planner':'rules','live_model_requests':0,
              'float_tolerance':{'relative':1e-12,'absolute':1e-12},
              'limits':['Descriptive ranking only, not a significance test or fault-cause diagnosis.',
                        'Checked one real twelve-hour population; operation differences and observation completeness remain unverified.',
                        'Peers are eligible other observed heads in the explicit machine/time population.',
                        'Six general diagnostic catalogue questions remain deferred; no live LLM comparison routing.']}
    output=ROOT/'benchmarks/integration'/f'head_kpi_{stamp}.json'
    output.write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n')
    entry=(f'## Integration measurement — descriptive head comparisons {stamp}\n\n'
           '- Two real queries matched independent per-head counts, exact-ratio competition ranks and the focus-versus-peer calculation.\n'
           '- Original event fields and explicit machine/time population were preserved. Reports and traces were saved.\n'
           '- Focus was excluded from the unweighted peer median. Small-sample exclusions and tied ranks remain visible.\n'
           '- Deterministic descriptive results only; no significance, root-cause or new LLM routing claim.\n'
           f'- Evidence: {output.relative_to(ROOT)}.\n'
           '- Next action: record regression results and continue with remaining temporal KPI requirements.\n')
    for name in ['PROJECT-AUDIT.md','INTEGRATION-TRACKER.md']:
        p=ROOT/'docs'/name
        p.write_text(p.read_text().rstrip()+'\n\n'+entry)
    print('\nHEAD COMPARISON VERIFICATION COMPLETE')
    print(json.dumps(verified,indent=2))
    print(f'Evidence: {output.relative_to(ROOT)}')
    print('Updated both audit documents. Run git status --short.')


if __name__=='__main__':
    main()
