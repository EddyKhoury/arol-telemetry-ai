"""Independent raw counter oracle and production planted-signal smoke tests."""
import json
from pathlib import Path

import pytest

from scripts import evaluate_agent
from src.agent.orchestrator import Orchestrator
from src.common import datasource
from src.ingestion.event_pool import build_event_pool


@pytest.fixture
def controlled(tmp_path):
    paths=evaluate_agent.plant_input(tmp_path/'raw')
    expected,boundary=evaluate_agent.scalar_events(paths)
    manifest=build_event_pool(paths,tmp_path/'pool',machine_id='M1')
    config={'data':{'source':'person_a_pool','person_a':{'fixture':str(manifest)},
                    'max_loaded_events':1000},
            'agent':{'planner':'rules'},
            'analytics':{'min_n':3,'torque_expected_min':1.5,'torque_expected_max':2.5,
                         'anomaly_sigma':3.0,'drift_window_seconds':3}}
    return paths,manifest,expected,boundary,config


def test_scalar_counter_reference_keeps_one_boundary_per_head(controlled):
    paths,manifest,expected,boundary,cfg=controlled
    assert len(expected)==48 and boundary==4
    counts={head:sum(r['head_id']==head for r in expected) for head in evaluate_agent.HEADS}
    assert counts=={head:12 for head in evaluate_agent.HEADS}
    assert sum(r['head_id']=='H05' and r['status']==65 for r in expected)==4
    assert [r['torque'] for r in expected if r['head_id']=='H05' and r['torque']!=2.0]==[3.1,0.5]
    stored=json.loads(manifest.read_text())
    assert stored['summary']['boundary_exact_plus_one']==4
    source=datasource.get_source(cfg)
    selected,meta=source.load_for_plan('fixture',[('success_rate_per_head',dict(evaluate_agent.WINDOW))])
    evaluate_agent.compare_event_fields(selected,expected)
    assert meta['loaded_events']==48


@pytest.mark.parametrize('case_id,query,tool',[
    ('planted_torque_thresholds',
     'Which torque values look suspicious for head 5 for machine M1 from 2026-02-01T00:00:00 until 2026-02-01T00:00:13',
     'detect_torque_anomalies'),
    ('planted_rank',
     'Rank heads by cap present success rate for machine M1 from 2026-02-01T00:00:00 until 2026-02-01T00:00:13',
     'rank_heads_by_success'),
    ('planted_peers',
     'Compare head 5 with peers by cap present success rate for machine M1 from 2026-02-01T00:00:00 until 2026-02-01T00:00:13',
     'compare_head_success'),
])
def test_planted_signals_flow_through_production_orchestrator(controlled,case_id,query,tool):
    _,_,_,_,cfg=controlled
    response=Orchestrator(cfg=cfg).answer(query)
    assert response['status']=='ok',response.get('message')
    assert response['plan'].calls[0][0]==tool
    assert response['trace'].to_dict()['n_tool_calls']==1
    name,answer=response['results'][0]
    assert name==tool and answer['ok']
    evaluate_agent.planted_checks(case_id,answer['result'],answer['meta'],response['markdown'])


def test_unspecified_failure_does_not_load_data(controlled,monkeypatch):
    _,_,_,_,cfg=controlled
    engine=Orchestrator(cfg=cfg)
    def forbidden(*args,**kwargs):
        raise AssertionError('Unspecified cause must stop before data loading')
    monkeypatch.setattr(engine.source,'load_for_plan',forbidden)
    answer=engine.answer('Why is H05 failing more?')
    assert answer['status']=='needs_clarification'
    assert answer['trace'].to_dict()['n_tool_calls']==0


def test_fixed_catalogue_has_independent_expected_calls():
    path=Path(evaluate_agent.CATALOGUE)
    dataset=json.loads(path.read_text())
    assert dataset['version']==1 and len(dataset['cases'])==28
    assert sum(row['expected']=='routed' for row in dataset['cases'])==16
    assert sum(row['expected']=='needs_clarification' for row in dataset['cases'])==12
    assert len({row['id'] for row in dataset['cases']})==28
