"""Require an explicit comparison metric, one machine and a bounded time window."""
import re
from .torque_routing import _parse_canonical_torque_request


def parse_head_kpi_request(query):
    text=' '.join((query or '').split()).rstrip('.?!')
    prefix=r'(?:(?:show me|show) (?:the )?)?'
    ranking=re.match(prefix+r'rank heads by cap[- ]present success rate(?=\s|$)',text,re.I)
    comparison=re.match(prefix+r'compare (?:head\s*|h)(\d+) with peers by cap[- ]present success rate(?=\s|$)',text,re.I)
    if not ranking and not comparison:
        return None
    def clarify():
        return dict(goal='Specify the head comparison scope.', ambiguous=True,
                    clarification=("Use 'rank heads by cap-present success rate' or 'compare head 5 with peers by cap-present success rate', "
                                   "followed by 'for machine M1' and 'on YYYY-MM-DD' or 'from <ISO> until <ISO>'. "
                                   "Peers are other available heads in that same window. Status filters, selected peer subsets and threshold overrides are unsupported."),
                    rationale='comparison requires explicit metric, machine and bounded time; no data loaded')
    match=ranking or comparison
    tail=text[match.end():].strip()
    if re.search(r'\b(?:status|closures|bins)\b',tail,re.I):
        return clarify()
    parsed=_parse_canonical_torque_request('Average torque '+tail)
    if parsed is None or parsed.get('ambiguous'):
        return clarify()
    params=parsed['calls'][0][1]
    if set(params)!={'machine_id','start','end'}:
        return clarify()
    if comparison:
        number=int(comparison.group(1))
        if number<1:
            return clarify()
        params['head_id']=f'H{number:02d}'
    name='compare_head_success' if comparison else 'rank_heads_by_success'
    return dict(goal='Compare cap-present success fractions descriptively within the explicitly requested machine/time population.',
                calls=[(name,params)], filters=dict(params),
                rationale='explicit comparison metric and full population scope; the named head is the focus and other selected heads provide peers')
