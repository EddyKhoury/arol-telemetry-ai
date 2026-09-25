"""Complete deterministic grammar for explicitly scoped hourly/daily questions."""
import re
from .torque_routing import _parse_canonical_torque_request


def parse_temporal_kpi_request(query):
    text = ' '.join((query or '').split()).rstrip('.?!')
    prefix = r'(?:(?:show me|show|what is|what are) (?:the )?)?'
    metric = r'(?:success rate|reject(?:ion)? rate|no[ -]load rate|capping kpis|kpis|(?:observed )?throughput)'
    matches = [
        re.match(prefix + r'(?P<metric>' + metric + r') (?:by|per) (?P<bucket>hour|day)(?=\s|$)', text, re.I),
        re.match(prefix + r'(?P<bucket>hourly|daily) (?P<metric>' + metric + r')(?=\s|$)', text, re.I),
    ]
    match = next((m for m in matches if m), None)
    if match is None:
        return None
    def clarify():
        return dict(goal='Clarify the temporal KPI and its full scope.', ambiguous=True,
                    clarification=("Ask for 'success rate by hour' or 'observed throughput by day', with "
                                   "'for machine M1' and 'on YYYY-MM-DD' or 'from <ISO> until <ISO>'. "
                                   "An optional head is allowed. Status prefilters, exclusions, relative dates, "
                                   "shift definitions and bucket/threshold overrides are unsupported."),
                    rationale='temporal request requires one explicit machine and bounded time; scope not broadened')
    tail = text[match.end():].strip()
    if re.search(r'\b(?:status|closures|bins)\b', tail, re.I):
        return clarify()
    plan = _parse_canonical_torque_request('Average torque ' + tail)
    if plan is None or plan.get('ambiguous'):
        return clarify()
    params = plan['calls'][0][1]
    if not {'machine_id', 'start', 'end'} <= set(params) or set(params) - {'machine_id', 'start', 'end', 'head_id'}:
        return clarify()
    params['bucket'] = {'hourly':'hour', 'daily':'day'}.get(match['bucket'].lower(), match['bucket'].lower())
    tool = 'observed_throughput' if 'throughput' in match['metric'].lower() else 'kpi_over_time'
    return dict(goal='Describe recorded events and explicit-denominator KPIs in requested time intervals.',
                calls=[(tool, params)], filters=dict(params),
                rationale='complete temporal question parsed; all statuses and requested machine/head/time scope retained')
