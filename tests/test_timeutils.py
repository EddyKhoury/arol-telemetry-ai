"""Shared time bucketing - audit finding F5.

This module is the reason "per day" means the same thing in Person A's drift
tool and Person B's KPI tool. It had 60% coverage and no tests of its own,
which is backwards: it is the most shared code in the project and the least
obviously correct, because the shift bucket has to roll BACKWARDS over
midnight.

Expected values here are worked out from the shift definition, not read off
the implementation - a test that mirrors the code it tests proves nothing.
"""

from datetime import datetime, timedelta

import polars as pl
import pytest

from src.common import timeutils as T


def _floor(iso: str, bucket: str) -> datetime:
    """floor_to on a one-row frame, via an expression."""
    frame = pl.DataFrame({"ts": [datetime.fromisoformat(iso)]})
    return frame.select(T.floor_to(pl.col("ts"), bucket).alias("b"))["b"][0]


def _name(iso: str) -> str:
    frame = pl.DataFrame({"ts": [datetime.fromisoformat(iso)]})
    return frame.select(T.shift_name(pl.col("ts")).alias("s"))["s"][0]


# --- the simple buckets ---------------------------------------------------

@pytest.mark.parametrize("iso,expected", [
    ("2026-02-03T14:37:59", "2026-02-03T14:00:00"),
    ("2026-02-03T00:00:00", "2026-02-03T00:00:00"),   # already on a boundary
    ("2026-02-03T23:59:59", "2026-02-03T23:00:00"),
])
def test_hour_floors_to_the_hour(iso, expected):
    assert _floor(iso, "hour") == datetime.fromisoformat(expected)


@pytest.mark.parametrize("iso,expected", [
    ("2026-02-03T14:37:59", "2026-02-03T00:00:00"),
    ("2026-02-03T00:00:00", "2026-02-03T00:00:00"),
    ("2026-02-03T23:59:59", "2026-02-03T00:00:00"),
])
def test_day_floors_to_midnight(iso, expected):
    assert _floor(iso, "day") == datetime.fromisoformat(expected)


def test_week_floors_to_monday():
    """Polars weeks start on Monday. 2026-02-03 is a Tuesday."""
    assert datetime.fromisoformat("2026-02-03T00:00:00").weekday() == 1
    assert _floor("2026-02-03T14:00:00", "week") == \
        datetime.fromisoformat("2026-02-02T00:00:00")


def test_an_unknown_bucket_is_refused_by_name():
    with pytest.raises(ValueError, match="unknown bucket"):
        _floor("2026-02-03T14:00:00", "fortnight")


# --- the shift bucket, which is the one that can be wrong ----------------
#
# Shifts start at 06:00 (A), 14:00 (B), 22:00 (C). So shift C spans 22:00 on
# one calendar day to 06:00 on the NEXT - meaning a timestamp at 03:00 belongs
# to a shift that started the PREVIOUS day. That rollback is the whole reason
# this function is not a one-line truncate.

@pytest.mark.parametrize("iso,expected", [
    # inside each shift
    ("2026-02-03T09:15:00", "2026-02-03T06:00:00"),   # A
    ("2026-02-03T18:30:00", "2026-02-03T14:00:00"),   # B
    ("2026-02-03T23:30:00", "2026-02-03T22:00:00"),   # C, same day
    # THE ROLLBACK: before 06:00 belongs to yesterday's C
    ("2026-02-03T03:00:00", "2026-02-02T22:00:00"),
    ("2026-02-03T00:00:00", "2026-02-02T22:00:00"),
    ("2026-02-03T05:59:59", "2026-02-02T22:00:00"),
    # exact boundaries belong to the shift they OPEN, not the one they close
    ("2026-02-03T06:00:00", "2026-02-03T06:00:00"),
    ("2026-02-03T14:00:00", "2026-02-03T14:00:00"),
    ("2026-02-03T22:00:00", "2026-02-03T22:00:00"),
    # one second before each boundary is still the previous shift
    ("2026-02-03T13:59:59", "2026-02-03T06:00:00"),
    ("2026-02-03T21:59:59", "2026-02-03T14:00:00"),
])
def test_shift_floors_to_the_shift_start(iso, expected):
    assert _floor(iso, "shift") == datetime.fromisoformat(expected)


def test_the_rollback_crosses_a_month_boundary():
    """01:00 on the 1st belongs to a shift that started in the previous MONTH."""
    assert _floor("2026-03-01T01:00:00", "shift") == \
        datetime.fromisoformat("2026-02-28T22:00:00")


def test_a_shift_floor_is_never_in_the_future():
    """Property, not an example: flooring moves backwards or stays put, for
    every hour of the day. The rollback is exactly where this could break."""
    base = datetime.fromisoformat("2026-02-03T00:00:00")
    for minutes in range(0, 24 * 60, 7):          # every 7 minutes, full day
        ts = base + timedelta(minutes=minutes)
        floored = _floor(ts.isoformat(), "shift")
        assert floored <= ts, f"{ts} floored forwards to {floored}"


def test_shift_floors_are_exactly_eight_hours_apart():
    """Three shifts a day means the distinct floors over 24h must be 8h apart.
    A bucket that silently produced four or two would still 'work'."""
    base = datetime.fromisoformat("2026-02-03T00:00:00")
    floors = sorted({_floor((base + timedelta(minutes=m)).isoformat(), "shift")
                     for m in range(0, 24 * 60, 5)})
    gaps = {(b - a) for a, b in zip(floors, floors[1:])}
    assert gaps == {timedelta(hours=8)}, floors


def test_every_bucket_in_the_vocabulary_actually_works():
    """BUCKETS is the frozen vocabulary the registry advertises to the model.
    A name in it that floor_to cannot handle would be a runtime failure the
    planner is entitled to trigger."""
    for bucket in T.BUCKETS:
        assert _floor("2026-02-03T14:37:00", bucket) is not None


def test_floor_to_works_on_a_series_as_well_as_an_expression():
    """The docstring promises both; kpi.py uses the expression form and
    nothing exercised the Series form."""
    series = pl.Series("ts", [datetime.fromisoformat("2026-02-03T09:15:00")])
    assert T.floor_to(series, "shift")[0] == \
        datetime.fromisoformat("2026-02-03T06:00:00")


# --- shift_name -----------------------------------------------------------
#
# NOTE: nothing in src/ calls shift_name yet. It is public API in a module
# Person A is expected to share (F5), so it is tested rather than left to rot
# untested - but if it is still uncalled at hand-in, delete it.

@pytest.mark.parametrize("iso,expected", [
    ("2026-02-03T06:00:00", "A"),
    ("2026-02-03T13:59:59", "A"),
    ("2026-02-03T14:00:00", "B"),
    ("2026-02-03T21:59:59", "B"),
    ("2026-02-03T22:00:00", "C"),
    ("2026-02-03T03:00:00", "C"),      # before 06:00 is still C
    ("2026-02-03T00:00:00", "C"),
])
def test_shift_name_matches_the_shift_definition(iso, expected):
    assert _name(iso) == expected


def test_shift_name_and_shift_floor_agree():
    """They are two views of one definition. If they ever disagree, a report
    could label a bucket 'shift A' and floor it to B's start."""
    base = datetime.fromisoformat("2026-02-03T00:00:00")
    starts = {label: hour for label, hour in T.SHIFTS}
    for minutes in range(0, 24 * 60, 11):
        ts = base + timedelta(minutes=minutes)
        assert _floor(ts.isoformat(), "shift").hour == starts[_name(ts.isoformat())]


# --- parse_bound ----------------------------------------------------------

def test_a_date_only_bound_is_midnight():
    assert T.parse_bound("2026-02-03") == datetime.fromisoformat("2026-02-03T00:00:00")


def test_a_datetime_passes_through():
    ts = datetime.fromisoformat("2026-02-03T14:30:00")
    assert T.parse_bound(ts) == ts


def test_empty_and_none_mean_no_bound():
    assert T.parse_bound(None) is None
    assert T.parse_bound("") is None


def test_an_offset_is_DROPPED_not_converted():
    """The event table is plant-local naive. Converting a user's window would
    silently move it by hours; ignoring an offset they probably did not mean
    to type is the lesser evil, and the docstring commits to it."""
    assert T.parse_bound("2026-02-03T14:00:00+05:00") == \
        datetime.fromisoformat("2026-02-03T14:00:00")
    assert T.parse_bound("2026-02-03T14:00:00Z") == \
        datetime.fromisoformat("2026-02-03T14:00:00")


def test_an_unparseable_bound_names_the_value_and_the_format():
    with pytest.raises(ValueError) as excinfo:
        T.parse_bound("last tuesday")
    message = str(excinfo.value)
    assert "last tuesday" in message and "ISO-8601" in message


def test_every_bucket_works_on_a_series_too():
    """The Series form was broken for `shift` only: hour/day/week work by
    accident because Series.dt.truncate returns a Series, while the shift
    branch builds pl.when() chains and returned an Expr whatever you passed.
    A shared helper must not behave differently per branch (audit F5)."""
    series = pl.Series("ts", [datetime.fromisoformat("2026-02-03T09:15:00")])
    for bucket in T.BUCKETS:
        out = T.floor_to(series, bucket)
        assert isinstance(out, pl.Series), f"{bucket} returned {type(out).__name__}"
        assert out[0] <= datetime.fromisoformat("2026-02-03T09:15:00")


def test_shift_name_works_on_a_series_too():
    series = pl.Series("ts", [datetime.fromisoformat("2026-02-03T03:00:00")])
    out = T.shift_name(series)
    assert isinstance(out, pl.Series)
    assert out[0] == "C"


def test_the_series_and_expression_forms_agree():
    stamps = [datetime.fromisoformat("2026-02-03T00:00:00")
              + timedelta(minutes=m) for m in range(0, 24 * 60, 13)]
    series = pl.Series("ts", stamps)
    frame = pl.DataFrame({"ts": stamps})
    for bucket in T.BUCKETS:
        via_series = T.floor_to(series, bucket).to_list()
        via_expr = frame.select(T.floor_to(pl.col("ts"), bucket))["ts"].to_list()
        assert via_series == via_expr, bucket
