"""Descriptive head rankings; peer differences are not causal or significance tests."""
from copy import deepcopy
from fractions import Fraction
import re
from statistics import median

from .registered_kpi import _calculate
from .event_filters import _bound
from ..common.registry import tool

POPULATION = ['machine_id', 'start', 'end']


def validate_population(machine_id, start, end, head_id=None):
    if not isinstance(machine_id, str) or not machine_id.strip() or machine_id.lower() in {'all','any','none','null','nan'}:
        raise ValueError('Select one explicit machine_id for head comparisons')
    lo, hi = _bound(start), _bound(end)
    if lo is None or hi is None or lo >= hi:
        raise ValueError('Head comparisons require an explicit start and end, with start before end')
    if head_id is not None:
        if (not isinstance(head_id, str) or not re.fullmatch(r'H\d+', head_id)
                or int(head_id[1:]) < 1 or head_id != f'H{int(head_id[1:]):02d}'):
            raise ValueError('The focus head_id must be one canonical identifier, for example H05')


def _rate(row):
    return Fraction(row['n_success_cap_present'], row['n_cap_present'])


def rank_counts(rows, min_n):
    """Competition ranks use exact ratios: ties get equal ranks (1, 1, 3)."""
    if type(min_n) is not int or min_n < 1:
        raise ValueError('min_n must be a positive integer')
    rows = deepcopy(rows)
    if len({r['machine_id'] for r in rows}) > 1:
        raise ValueError('Rank exactly one machine at a time')
    if len({r['head_id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate head summaries cannot be ranked')
    for row in rows:
        n, ok = row['n_cap_present'], row['n_success_cap_present']
        if type(n) is not int or type(ok) is not int or not 0 <= ok <= n:
            raise ValueError('Invalid cap-present success counts')
        row['eligible_for_ranking'] = n >= min_n
        row['rank_lowest_success_first'] = None
        row['exclusion_reason'] = None if n >= min_n else 'insufficient_cap_present_sample'
    eligible = sorted((r for r in rows if r['eligible_for_ranking']), key=lambda r: (_rate(r), r['head_id']))
    if len(eligible) >= 2:
        previous = None
        rank = None
        for index, row in enumerate(eligible, 1):
            value = _rate(row)
            if value != previous:
                rank = index
            row['rank_lowest_success_first'] = rank
            previous = value
    excluded = sorted((r for r in rows if not r['eligible_for_ranking']), key=lambda r: r['head_id'])
    return eligible + excluded


def compare_with_peers(ranked, head_id):
    """Unweighted median across eligible OTHER heads, requiring two peers."""
    focus = next((r for r in ranked if r['head_id'] == head_id), None)
    peers = [r for r in ranked if r['head_id'] != head_id and r['eligible_for_ranking']]
    result = dict(focus_head_id=head_id, focus=deepcopy(focus), eligible_peer_heads=[r['head_id'] for r in peers],
                  n_eligible_peers=len(peers), peer_median_success_rate=None,
                  difference_from_peer_median_pp=None, comparison_available=False, comparison_reason=None)
    if focus is None:
        result['comparison_reason'] = 'focus_head_not_found'
    elif not focus['eligible_for_ranking']:
        result['comparison_reason'] = 'focus_below_minimum_sample'
    elif len(peers) < 2:
        result['comparison_reason'] = 'fewer_than_two_eligible_peers'
    else:
        baseline = median([_rate(r) for r in peers])
        result.update(peer_median_success_rate=float(baseline),
                      difference_from_peer_median_pp=float((_rate(focus)-baseline)*100),
                      comparison_available=True)
    return result


def _run(events, *, machine_id, start, end, head_id=None):
    validate_population(machine_id, start, end, head_id)
    # head_id is the explicitly requested comparison subject. The population
    # consists of all supplied heads in the SAME requested machine/time window.
    response = _calculate(events, per_head=True, machine_id=machine_id, start=start, end=end)
    result = response['result']
    threshold = result['overall']['min_cap_present_n']
    ranked = rank_counts(result.pop('per_head'), threshold)
    result['ranked_heads'] = ranked
    result['n_eligible_heads'] = sum(r['eligible_for_ranking'] for r in ranked)
    result['ranking_available'] = result['n_eligible_heads'] >= 2
    result['metric'] = 'success_rate_cap_present'
    result['ordering'] = 'ascending success fraction; exact-ratio ties share competition ranks'
    result['population_scope'] = dict(machine_id=machine_id, start=start, end=end)
    result['min_cap_present_n'] = threshold
    result['comparison_method'] = 'unweighted median success fraction of eligible other heads; at least two peers required'
    if head_id is not None:
        result.update(compare_with_peers(ranked, head_id))
    response['meta']['notes'] = response['meta']['notes'].replace('no head ranking or statistical significance claim is made', 'no statistical significance claim is made')
    response['meta']['notes'] += (
        ' Descriptive ordering only; sample-size eligibility does not prove significance or comparability. '
        'Unknown-cap events are reported but excluded from cap-present rates. '
        'Peers are all available other heads in the same selected machine/time window, not heads outside that scope. '
        'Different operating conditions or missing observations may affect comparisons. No fault cause is established.'
    )
    if head_id is not None:
        response['meta']['filters_applied'].append(f'focus_head_id={head_id}; peer population retains other heads in the same machine/time window')
    return response


@tool(name='rank_heads_by_success', description='Descriptively rank available heads by cap-present success fraction within one explicitly selected machine/time window. Small samples are excluded; ties share ranks.', params=POPULATION, required=POPULATION, agent='kpi', owner='integration')
def rank_heads_by_success(events, *, machine_id, start, end):
    return _run(events, machine_id=machine_id, start=start, end=end)


@tool(name='compare_head_success', description='Compare one focus head with the unweighted median of eligible other heads in the SAME explicit machine/time window. head_id selects the focus, not a filter removing peers. No causal claims.', params=POPULATION+['head_id'], required=POPULATION+['head_id'], agent='kpi', owner='integration')
def compare_head_success(events, *, machine_id, start, end, head_id):
    if head_id is None:
        raise ValueError('An explicit focus head_id is required')
    return _run(events, machine_id=machine_id, start=start, end=end, head_id=head_id)
