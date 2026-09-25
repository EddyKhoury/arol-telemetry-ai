"""Calendar-bucket descriptive KPIs and observed-event rates over requested time."""
from datetime import timedelta
import polars as pl

from .event_filters import _bound
from .registered_kpi import _prepare, _aggregations, finish_counts, DEFINITIONS
from ..common.runtime import current_config
from ..common.registry import tool
from ..common.envelope import envelope, data_window

REQUIRED = ['machine_id', 'start', 'end', 'bucket']
PARAMS = REQUIRED + ['head_id']


class TooManyTimeBuckets(ValueError):
    """The requested output grid exceeds the trusted configured limit."""


def bucket_grid(start, end, bucket, max_buckets=1000):
    if bucket not in ('hour', 'day'):
        raise ValueError("bucket must be 'hour' or 'day'")
    if type(max_buckets) is not int or max_buckets < 1:
        raise ValueError('analytics.max_time_buckets must be a positive integer')
    lo, hi = _bound(start), _bound(end)
    if lo is None or hi is None or lo >= hi:
        raise ValueError('Temporal KPIs require explicit start and end, with start before end')
    cursor = lo.replace(minute=0, second=0, microsecond=0)
    if bucket == 'day':
        cursor = cursor.replace(hour=0)
    step = timedelta(hours=1) if bucket == 'hour' else timedelta(days=1)
    grid = []
    while cursor < hi:
        if len(grid) >= max_buckets:
            raise TooManyTimeBuckets(f'Request exceeds the configured {max_buckets} time buckets; select a shorter window or daily buckets')
        try:
            following = cursor + step
        except OverflowError:
            following = hi
        begin, finish = max(lo, cursor), min(hi, following)
        grid.append(dict(calendar_bucket_start=cursor, bucket_start=begin, bucket_end=finish,
                         duration_seconds=(finish-begin).total_seconds()))
        cursor = following
    return grid


def validate_request(machine_id, start, end, bucket, max_buckets=1000):
    if not isinstance(machine_id, str) or not machine_id.strip() or machine_id.lower() in {'all', 'any', 'null', 'none', 'nan'}:
        raise ValueError('Select one explicit machine_id for temporal KPIs')
    return bucket_grid(start, end, bucket, max_buckets)


def add_observed_rates(counts, seconds):
    if seconds <= 0:
        raise ValueError('The requested interval must have positive duration')
    return dict(counts, duration_seconds=seconds,
                observed_events_per_hour=counts['n_observed']*3600/seconds,
                cap_present_events_per_hour=counts['n_cap_present']*3600/seconds,
                successful_events_per_hour=counts['n_success_cap_present']*3600/seconds)


def _run(events, *, machine_id, start, end, bucket, head_id=None, throughput=False):
    maximum = current_config().get('analytics', {}).get('max_time_buckets', 1000)
    grid = validate_request(machine_id, start, end, bucket, maximum)
    frame, applied, min_n = _prepare(events, machine_id=machine_id, start=start, end=end, head_id=head_id)
    overall = finish_counts(frame.select(_aggregations()).row(0, named=True), min_n)
    empty = {key: 0 for key in overall if key.startswith('n_')}
    grouped = (frame.with_columns(pl.col('ts').dt.truncate('1h' if bucket == 'hour' else '1d').alias('_bucket'))
               .group_by('_bucket').agg(_aggregations()))
    buckets = {row.pop('_bucket'): row for row in grouped.to_dicts()}
    by_bucket = []
    for bounds in grid:
        counts = finish_counts(buckets.get(bounds['calendar_bucket_start'], empty), min_n)
        by_bucket.append(dict(bounds, **add_observed_rates(counts, bounds['duration_seconds']),
                              has_observations=counts['n_observed'] > 0))
    # Distinct intervals form an exact partition of the requested half-open window.
    if any(sum(row[key] for row in by_bucket) != overall[key] for key in empty):
        raise ValueError('Bucket counts do not reconcile with overall counts')
    seconds = (_bound(end)-_bound(start)).total_seconds()
    result = dict(overall=add_observed_rates(overall, seconds), by_bucket=by_bucket,
                  requested_window=dict(start=start, end=end), bucket=bucket, n_buckets=len(grid),
                  rate_definitions=dict(DEFINITIONS),
                  throughput_denominator='requested interval duration, not observed first-to-last event span',
                  telemetry_coverage='not_established_from_event_table',
                  bucket_timezone='timestamps used as stored; timezone and DST elapsed-time semantics unconfirmed')
    applied += [f'calendar bucket={bucket}; intervals clipped to requested start/end']
    notes = ('Observed exact +1 events only; counter discontinuities are not reconstructed. '
             'Counts include all statuses and do not require finite torque. '
             'Cap-present fractions retain their explicit denominator and unknown counts. '
             'Events per hour divide counts by the requested interval duration, including partial buckets. '
             'The total rate is computed from total counts and total duration, not an unweighted mean of bucket rates. '
             'Zero observed events do not establish zero production or machine downtime. '
             'Telemetry coverage and the machine operating schedule are not established from event rows. '
             'Naive timestamps are used as stored; no UTC or DST normalization is claimed. '
             + ('meta.n counts observed events.' if throughput else 'meta.n counts confirmed cap-present events.'))
    return envelope(result, n=overall['n_observed'] if throughput else overall['n_cap_present'],
                    filters_applied=applied, window=data_window(frame), notes=notes,
                    units={**{name:'fraction' for name in DEFINITIONS},'duration_seconds':'s',
                           'observed_events_per_hour':'observed events/hour',
                           'cap_present_events_per_hour':'cap-present events/hour',
                           'successful_events_per_hour':'successful observed events/hour'})


@tool(name='kpi_over_time', description='Hourly or daily explicit-denominator KPI counts and fractions, including empty and partial requested intervals. Requires one machine and bounded time; no status prefilter.', params=PARAMS, required=REQUIRED, agent='kpi', owner='integration')
def kpi_over_time(events, *, machine_id, start, end, bucket, head_id=None):
    return _run(events, machine_id=machine_id, start=start, end=end, bucket=bucket, head_id=head_id)


@tool(name='observed_throughput', description='Observed exact +1 event counts per requested hour, with hourly/daily buckets. Not total production or a downtime estimate. Includes all statuses and separately reports cap-present/successful event rates.', params=PARAMS, required=REQUIRED, agent='kpi', owner='integration')
def observed_throughput(events, *, machine_id, start, end, bucket, head_id=None):
    return _run(events, machine_id=machine_id, start=start, end=end, bucket=bucket, head_id=head_id, throughput=True)
