"""Temporal rates use explicit requested durations, never event-span guesses."""
from datetime import datetime, timedelta
import json
import polars as pl
import pytest

from src.analytics.registered_temporal_kpi import bucket_grid, TooManyTimeBuckets
from src.common.runtime import dispatch_tool
from src.agent.planner import RulePlanner, LLMPlanner
from src.agent.orchestrator import Orchestrator
from src.common import registry
from src.ingestion.event_table_polars import build_event_table, write_event_table_parquet
from src.ingestion.event_pool import build_event_pool

CFG={'agent':{'planner':'rules'},'analytics':{'min_n':3}}
ARGS=dict(machine_id='M1',head_id='H01',start='2026-02-01T00:30:00',end='2026-02-01T03:15:00',bucket='hour')
SUFFIX=' for head 1 for machine M1 from 2026-02-01T00:30:00 until 2026-02-01T03:15:00'


@pytest.fixture
def raw():
    stamps=['00:00:00','00:25:00','00:30:00','00:59:59','01:00:00','01:15:00','03:00:00','03:15:00']
    return pl.DataFrame({'timestamp':[datetime.fromisoformat('2026-02-01T'+s) for s in stamps],
                         'H01 Count':list(range(8)), 'H02 Count':list(range(8)),
                         'H01 Status':[0,0,0,65,2,9,0,65], 'H02 Status':[0]*8,
                         'H01 AppTorque':[2.,2.,float('nan'),2.,2.,float('inf'),2.,2.], 'H02 AppTorque':[2.]*8})


@pytest.fixture
def events(raw):
    return build_event_table(raw,'M1')


def test_grid_clips_first_and_last_intervals_and_keeps_empty_intervals():
    grid=bucket_grid(ARGS['start'],ARGS['end'],'hour')
    assert [r['duration_seconds'] for r in grid]==[1800,3600,3600,900]
    assert grid[0]['bucket_start']==datetime(2026,2,1,0,30)
    assert grid[-1]['bucket_end']==datetime(2026,2,1,3,15)


def test_daily_grid_uses_naive_calendar_days_with_partial_edges():
    grid=bucket_grid('2026-02-01T12:00:00','2026-02-03T12:00:00','day')
    assert [r['duration_seconds'] for r in grid]==[43200,86400,43200]


@pytest.mark.parametrize('tool',['kpi_over_time','observed_throughput'])
@pytest.mark.parametrize('lazy',[False,True])
def test_partial_empty_and_boundary_buckets_reconcile(events,tool,lazy):
    reply=dispatch_tool(tool,events.lazy() if lazy else events,config=CFG,arguments=ARGS)
    assert reply['ok'],reply['error']
    r=reply['result']; o=r['overall']; rows=r['by_bucket']
    assert [v['n_observed'] for v in rows]==[2,2,0,1]
    assert [v['duration_seconds'] for v in rows]==[1800,3600,3600,900]
    assert [v['observed_events_per_hour'] for v in rows]==[4,2,0,4]
    assert o['n_observed']==5 and o['duration_seconds']==9900
    assert o['observed_events_per_hour']==pytest.approx(5/2.75)
    assert o['observed_events_per_hour'] != sum(v['observed_events_per_hour'] for v in rows)/4
    assert r['incremental_mean_bucket_observed_rates'][-1] == pytest.approx(
        sum(v['observed_events_per_hour'] for v in rows) / len(rows))
    assert o['n_cap_present']==3 and o['n_success_cap_present']==2
    assert o['n_reject_cap_present']==1 and o['n_reject_outside_cap_present']==1
    assert o['n_cap_unknown']==1 and o['n_no_load_class']==1
    assert rows[0]['success_rate_cap_present']==.5
    assert rows[1]['success_rate_cap_present'] is None
    assert rows[2]['success_rate_cap_present'] is None and not rows[2]['has_observations']
    assert all(sum(v[k] for v in rows)==o[k] for k in o if k.startswith('n_'))
    assert reply['meta']['n']==(5 if tool=='observed_throughput' else 3)
    assert reply['meta']['data_window']=={'ts_min':'2026-02-01T00:30:00','ts_max':'2026-02-01T03:00:00'}
    assert r['telemetry_coverage']=='not_established_from_event_table'
    json.dumps(reply,allow_nan=False)


def test_daily_runtime_counts(events):
    both=pl.concat([events,events.with_columns((pl.col('ts')+timedelta(days=1)).alias('ts'))])
    args=dict(ARGS,start='2026-02-01T00:00:00',end='2026-02-03T00:00:00',bucket='day')
    reply=dispatch_tool('observed_throughput',both,config=CFG,arguments=args)
    assert reply['ok'],reply['error']
    assert [r['n_observed'] for r in reply['result']['by_bucket']]==[7,7]
    assert reply['result']['overall']['observed_events_per_hour']==pytest.approx(14/48)


@pytest.mark.parametrize('tool',['kpi_over_time','observed_throughput'])
def test_empty_head_keeps_requested_grid_without_claiming_downtime(events,tool):
    reply=dispatch_tool(tool,events,config=CFG,arguments=dict(ARGS,head_id='H99'))
    assert reply['ok'] and reply['result']['n_buckets']==4
    assert all(v['n_observed']==0 and v['success_rate_cap_present'] is None for v in reply['result']['by_bucket'])
    assert 'do not establish zero production or machine downtime' in reply['meta']['notes']


@pytest.mark.parametrize('change', [
    {'bucket':'week'}, {'bucket':'shift'}, {'start':None}, {'end':ARGS['start']},
    {'start':'2026-02-01T00:30:00Z'}, {'machine_id':None}, {'status_filter':0},
    {'cap_present_only':True}, {'min_n':1},
])
def test_temporal_arguments_cannot_change_population_or_supported_calendar(events,change):
    reply=dispatch_tool('kpi_over_time',events,config=CFG,arguments=dict(ARGS,**change))
    assert not reply['ok']


@pytest.mark.parametrize('maximum',[0,-1,True,'1000'])
def test_bucket_budget_must_be_a_trusted_positive_integer(events,maximum):
    reply=dispatch_tool('kpi_over_time',events,config={'analytics':{'max_time_buckets':maximum}},arguments=ARGS)
    assert not reply['ok'] and 'positive integer' in reply['error']


def test_output_grid_budget_is_enforced():
    with pytest.raises(TooManyTimeBuckets):
        bucket_grid(ARGS['start'],ARGS['end'],'hour',3)


@pytest.mark.parametrize('base,tool,bucket',[
    ('success rate by hour','kpi_over_time','hour'),('daily success rate','kpi_over_time','day'),
    ('No Load rate per day','kpi_over_time','day'),('show capping KPIs by hour','kpi_over_time','hour'),
    ('observed throughput by hour','observed_throughput','hour'),('throughput by day','observed_throughput','day'),
])
def test_temporal_grammar_preserves_scope(base,tool,bucket):
    plan=RulePlanner().plan(base+SUFFIX,{})
    assert not plan.ambiguous
    assert plan.calls==[(tool,dict(ARGS,bucket=bucket))]


@pytest.mark.parametrize('query',[
    'success rate by hour','throughput by day for machine M1','daily success rate on 2026-02-01',
    'success rate by hour'+SUFFIX+' for status 0',
    'observed throughput by hour'+SUFFIX+' for successful closures',
    'success rate by hour'+SUFFIX+' excluding H02','success rate by hour'+SUFFIX+' with sigma 2',
    'success rate by hour'+SUFFIX+' for head 2','success rate by hour yesterday',
])
def test_incomplete_or_conflicting_temporal_scope_requests_clarification(query):
    plan=RulePlanner().plan(query,{})
    assert plan.ambiguous and not plan.calls


@pytest.fixture
def sources(tmp_path,raw,events):
    one=write_event_table_parquet(events,tmp_path/'events.parquet')
    paths=[]
    for i,part in enumerate([raw[:4],raw[4:]]):
        path=tmp_path/f'raw-{i}.csv'; part.write_csv(path); paths.append(path)
    pool=build_event_pool(paths,tmp_path/'pool',machine_id='M1')
    return {'person_a':one,'person_a_pool':pool}


@pytest.mark.parametrize('source_name',['person_a','person_a_pool'])
@pytest.mark.parametrize('base',['success rate by hour','observed throughput by hour'])
def test_temporal_orchestration_preserves_scope_and_report_limits(sources,source_name,base):
    cfg={**CFG,'data':{'source':source_name,'person_a':{'fixture':str(sources[source_name])}}}
    answer=Orchestrator(cfg=cfg).answer(base+SUFFIX)
    assert answer['status']=='ok',answer.get('message')
    r=answer['results'][0][1]['result']
    assert r['overall']['n_observed']==5 and r['n_buckets']==4
    assert answer['trace'].to_dict()['n_tool_calls']==1
    assert 'do not establish zero production or machine downtime' in answer['markdown']
    assert 'Nothing anomalous surfaced' not in answer['markdown']
    if source_name=='person_a_pool':
        assert answer['pool_meta']['loaded_events']==5
        assert answer['pool_meta']['selection_parameters']=={k:v for k,v in ARGS.items() if k!='bucket'}


def test_source_rejects_excessive_grid_before_opening_manifest():
    cfg={**CFG,'analytics':{'min_n':3,'max_time_buckets':2},
         'data':{'source':'person_a_pool','person_a':{'fixture':'file-that-does-not-exist.json'}}}
    answer=Orchestrator(cfg=cfg).answer('success rate by hour'+SUFFIX)
    assert answer['status']=='needs_clarification'
    assert 'time buckets' in answer['message']
    assert answer['trace'].to_dict()['n_tool_calls']==0


@pytest.mark.parametrize('base',['success rate by hour','observed throughput by hour'])
def test_llm_temporal_requests_stay_blocked(base,monkeypatch):
    planner=LLMPlanner({'agent':{'llm':{'fallback_to_rules':False}}})
    monkeypatch.setattr(planner,'_chat',lambda *a: pytest.fail('not verified for LLM'))
    assert planner.plan(base+SUFFIX,{}).ambiguous


def test_temporal_schema_advertises_only_supported_buckets():
    specs={s['name']:s for s in registry.get_tool_specs()}
    assert specs['kpi_over_time']['input_schema']['properties']['bucket']['enum']==['hour','day']
