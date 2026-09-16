"""The A/B seam: Person A's 8-column event table -> the 12-column contract.

Two levels. The replica tests build a frame to his committed EVENT_SCHEMA and
always run. The live test imports his actual pipeline and runs a real day-file
through it, and skips when his repo is not beside this one - so a fresh clone
stays green while the machine that has both proves the integration for real.
"""

from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from src.common import schema
from src.ingestion import adapter

from . import person_a_bridge

PERSON_A_REPO = Path(__file__).resolve().parents[2] / "person-a"


def _person_a_frame(statuses, heads=("H01",), start="2026-02-01 00:00:00"):
    """A replica of what Person A's build_event_table returns."""
    t0 = datetime.fromisoformat(start.replace(" ", "T"))
    rows = []
    for head in heads:
        for i, status in enumerate(statuses):
            decoded = schema.decode_status(status)
            rows.append({
                "ts": t0 + timedelta(seconds=i * 6),
                "machine_id": "MCC777-01",
                "head_id": head,
                "torque": 2.0,
                "status": int(status),
                "error_class": decoded["error_class"],
                "reject_signal": decoded["reject_signal"],
                "cap_present": decoded["cap_present"],
            })
    return pl.DataFrame(rows, schema=dict(adapter.PERSON_A_COLUMNS))


# --- the conversion -------------------------------------------------------

def test_his_frame_becomes_a_conforming_event_table():
    """The whole point: after adapt(), validate_events passes."""
    frame, notes = adapter.adapt(_person_a_frame([0, 0, 2, 65]), pool_id="feb")
    assert schema.validate_events(frame, strict=False) == []
    assert list(frame.columns) == list(schema.EVENT_COLUMNS)
    assert notes


def test_the_four_missing_columns_are_supplied():
    frame, _ = adapter.adapt(_person_a_frame([0] * 4, heads=("H07",)),
                             pool_id="mar")
    assert frame["pool_id"].unique().to_list() == ["mar"]
    assert frame["head_index"].unique().to_list() == [7]
    assert frame["count_delta"].unique().to_list() == [1]
    assert frame["inferred"].unique().to_list() == [False]


def test_head_index_sorts_numerically_not_lexically():
    frame, _ = adapter.adapt(
        _person_a_frame([0], heads=("H02", "H10", "H01")), pool_id="feb")
    assert frame["head_index"].to_list() == [1, 2, 10]


def test_status_is_narrowed_to_the_contract_dtype():
    frame, _ = adapter.adapt(_person_a_frame([0, 2, 65]), pool_id="feb")
    assert frame.schema["status"] == pl.Int16


def test_an_out_of_range_status_raises_instead_of_wrapping():
    """Polars wraps on a narrowing cast, so 40000 would become a negative
    number and decode as a nonsense category. Silent corruption is the one
    outcome the adapter must never produce."""
    frame = _person_a_frame([0]).with_columns(
        pl.lit(40000, dtype=pl.Int64).alias("status"))
    with pytest.raises(adapter.AdapterError, match="does not fit Int16"):
        adapter.adapt(frame, pool_id="feb")


def test_the_dropped_closures_are_declared_not_hidden():
    """His detector filters `delta == 1` upstream, so 8 real caps per
    machine-day never reach us. The adapter cannot recover them; it must say
    so rather than let a total look complete."""
    _, notes = adapter.adapt(_person_a_frame([0] * 3), pool_id="feb")
    assert any("count_delta is 1 for every event" in n for n in notes)
    assert any("undercount" in n for n in notes)


def test_an_empty_frame_is_handled():
    empty = pl.DataFrame(schema=dict(adapter.PERSON_A_COLUMNS))
    frame, notes = adapter.adapt(empty, pool_id="feb")
    assert frame.height == 0
    assert schema.validate_events(frame, strict=False) == []


def test_a_frame_that_is_not_his_is_refused_clearly():
    with pytest.raises(adapter.AdapterError, match="missing"):
        adapter.adapt(pl.DataFrame({"nope": [1]}), pool_id="feb")


# --- the independent re-decode -------------------------------------------

def test_a_decoding_disagreement_is_reported_not_swallowed():
    """His decoder and ours were written separately from the same AROL table.
    A mismatch is a finding about the integration, not noise."""
    frame = _person_a_frame([2]).with_columns(
        pl.lit(True, dtype=pl.Boolean).alias("cap_present"))   # ours says False
    out, notes = adapter.adapt(frame, pool_id="feb")
    assert any("cap_present disagrees" in n for n in notes)
    assert out["cap_present"].to_list() == [False]             # contract wins


def test_agreement_produces_no_noise():
    _, notes = adapter.adapt(_person_a_frame([0, 2, 65]), pool_id="feb")
    assert not [n for n in notes if "disagrees" in n]


def test_the_tri_state_null_is_not_counted_as_a_disagreement():
    """null != null is true in SQL logic; comparing naively would report a
    disagreement on every code 4/8/16/32 event."""
    _, notes = adapter.adapt(_person_a_frame([4, 8, 16, 32]), pool_id="feb")
    assert not [n for n in notes if "disagrees" in n]


# --- pool_meta ------------------------------------------------------------

def test_describe_does_not_claim_cleaning_it_did_not_do():
    """0 duplicates removed would assert the adapter checked. It did not -
    cleaning is upstream, and objectives 2 and 3 are Person A's."""
    frame, notes = adapter.adapt(_person_a_frame([0] * 5), pool_id="feb")
    meta = adapter.describe(frame, pool_id="feb", notes=notes)
    assert meta["duplicates_removed"] is None
    assert meta["rows_after_cleaning"] is None
    assert meta["n_events"] == 5
    assert meta["schema_version"] == schema.SCHEMA_VERSION
    assert meta["warnings"]


# --- the live integration -------------------------------------------------

@pytest.mark.skipif(not person_a_bridge.available(),
                    reason="Person A's repo is not beside this one")
def test_person_as_real_pipeline_output_conforms(tmp_path):
    """Run a real day-file through Person A's ACTUAL pipeline, adapt the
    result, and assert it satisfies the contract and answers a KPI question.

    This is the test the integration rests on. Everything above is a replica
    of his schema; this one is his code, on real telemetry.
    """
    from src.common import registry as R
    from src.testing import benchmark

    archive = Path(benchmark.ARCHIVE)
    if not archive.exists():
        pytest.skip("telemetry archive not present")

    parquet = tmp_path / "person_a_events.parquet"
    person_a_bridge.build_event_table(archive, benchmark.MONTH, parquet)

    his = pl.read_parquet(parquet)
    assert list(his.columns) == list(adapter.PERSON_A_COLUMNS), \
        f"his event schema changed: {his.columns}"
    assert his.schema["status"] == pl.Int64, "the Int64/Int16 gap closed?"

    events, notes = adapter.adapt(his, pool_id="feb")
    assert schema.validate_events(events, strict=False) == []
    assert events.height > 0

    out = R.call_tool("success_rate", events)
    assert out["ok"], out["error"]
    assert out["result"]["overall"]["n_cycles"] == events.height


@pytest.mark.skipif(not person_a_bridge.available(),
                    reason="Person A's repo is not beside this one")
def test_his_pipeline_and_ours_agree_on_the_same_day(tmp_path):
    """Two independent reshapes of the same telemetry must produce the same
    closures. Our benchmark path keeps `delta > 0`; his keeps `delta == 1`.
    The difference is the dropped-sample gap, and it should be exactly the
    counter jumps - not a systematic disagreement about what a closure is.
    """
    from src.testing import benchmark

    archive = Path(benchmark.ARCHIVE)
    if not archive.exists():
        pytest.skip("telemetry archive not present")

    parquet = tmp_path / "person_a_events.parquet"
    person_a_bridge.build_event_table(archive, benchmark.MONTH, parquet)
    his, _ = adapter.adapt(pl.read_parquet(parquet), pool_id="feb")

    ours = benchmark.build_events(benchmark.day_files(archive, benchmark.MONTH, 1))

    jumps = int(ours.filter(pl.col("count_delta") > 1).height)
    assert ours.height - his.height == jumps, (
        f"ours {ours.height}, his {his.height}, counter jumps {jumps}: the "
        f"gap should be exactly the rows his `delta == 1` filter drops")

    # and the closures they agree on must carry identical torque and status
    key = ["ts", "head_id"]
    joined = his.join(ours.select(key + ["torque", "status"]), on=key,
                      how="inner", suffix="_ours")
    assert joined.height > 0
    assert joined.filter(pl.col("status") != pl.col("status_ours")).height == 0
    assert joined.filter(
        (pl.col("torque") - pl.col("torque_ours")).abs() > 1e-9).height == 0
