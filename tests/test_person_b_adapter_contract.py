"""Characterize the current A-to-B adapter without changing either pipeline."""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from src.ingestion.event_table_polars import build_event_table


PERSON_A_ROOT = Path(__file__).resolve().parents[1]
PERSON_B_ROOT = Path(
    os.environ.get(
        "AROL_PERSON_B_REPO",
        str(PERSON_A_ROOT.parent / "arol-telemetry-ai-person-b"),
    )
).resolve()

SORT_KEYS = ["ts", "head_id"]

# Executed in a separate interpreter rooted in Person B's project.
ADAPTER_SCRIPT = """
import json
import sys
from pathlib import Path

import polars as pl

from src.common.schema import validate_events
from src.ingestion.adapter import adapt

input_path, output_path, notes_path, mode = sys.argv[1:]

kwargs = {"pool_id": "contract_test"}
if mode == "preserve":
    kwargs["redecode"] = False

result, notes = adapt(pl.read_parquet(input_path), **kwargs)
validate_events(result)

result.write_parquet(output_path)
Path(notes_path).write_text(json.dumps(notes), encoding="utf-8")
"""


@pytest.fixture(scope="module")
def person_a_events():
    """Generate real Person A output from controlled raw telemetry."""
    statuses = [0, 2, 3, 4, 9, 64, 65, 999]
    n_rows = len(statuses) + 1
    start = datetime(2026, 2, 1, 10, 0, 0)

    raw = {
        "timestamp": [
            start + timedelta(seconds=i)
            for i in range(n_rows)
        ],
    }

    for head in ("H01", "H05"):
        raw[f"{head} Count"] = list(range(100, 100 + n_rows))
        raw[f"{head} AppTorque"] = [2.0] * n_rows
        raw[f"{head} Status"] = [0] + statuses

    events = build_event_table(
        pl.DataFrame(raw),
        machine_id="MCC-CONTRACT-TEST",
    )

    # The first row establishes the counter baseline.
    assert events.height == 16
    assert events.width == 8
    return events


def run_person_b_adapter(events, tmp_path, *, mode):
    adapter_path = PERSON_B_ROOT / "src" / "ingestion" / "adapter.py"
    if not adapter_path.is_file():
        pytest.skip(
            "Person B repository unavailable. Set AROL_PERSON_B_REPO "
            "to its extracted project root."
        )

    input_path = tmp_path / "person_a_events.parquet"
    output_path = tmp_path / "person_b_events.parquet"
    notes_path = tmp_path / "adapter_notes.json"

    events.write_parquet(input_path)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            ADAPTER_SCRIPT,
            str(input_path),
            str(output_path),
            str(notes_path),
            mode,
        ],
        cwd=PERSON_B_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, (
        "Person B adapter failed:\n"
        + completed.stdout
        + completed.stderr
    )

    return (
        pl.read_parquet(output_path),
        json.loads(notes_path.read_text(encoding="utf-8")),
    )


def assert_added_fields(out):
    assert out.width == 12
    assert out.schema["ts"] == pl.Datetime("us")
    assert out.schema["status"] == pl.Int64
    assert out.schema["head_index"] == pl.Int16
    assert out.schema["count_delta"] == pl.Int32
    assert out.schema["inferred"] == pl.Boolean

    assert out["ts"].is_sorted()
    assert out["pool_id"].unique().to_list() == ["contract_test"]
    assert out["count_delta"].unique().to_list() == [1]
    assert out["inferred"].unique().to_list() == [False]

    indices = dict(
        out.select("head_id", "head_index").unique().iter_rows()
    )
    assert indices == {"H01": 1, "H05": 5}


def test_redecode_false_preserves_all_person_a_columns(
    person_a_events, tmp_path
):
    out, notes = run_person_b_adapter(
        person_a_events.reverse(), tmp_path, mode="preserve"
    )

    assert_added_fields(out)
    assert_frame_equal(
        out.select(person_a_events.columns).sort(SORT_KEYS),
        person_a_events.sort(SORT_KEYS),
    )
    assert not any("disagrees" in note for note in notes)


def test_default_redecode_changes_are_explicit(
    person_a_events, tmp_path
):
    out, notes = run_person_b_adapter(
        person_a_events.reverse(), tmp_path, mode="default"
    )

    assert_added_fields(out)

    # Characterize B's current changes, without approving their semantics.
    expected = person_a_events.with_columns(
        pl.when(pl.col("status") == 3)
        .then(pl.lit(False))
        .when(pl.col("status") == 64)
        .then(pl.lit(True))
        .otherwise(pl.col("cap_present"))
        .alias("cap_present"),

        pl.when(pl.col("status") == 999)
        .then(pl.lit(True))
        .otherwise(pl.col("reject_signal"))
        .alias("reject_signal"),
    )

    assert_frame_equal(
        out.select(person_a_events.columns).sort(SORT_KEYS),
        expected.sort(SORT_KEYS),
    )
    assert any("cap_present disagrees" in note for note in notes)
    assert any("reject_signal disagrees" in note for note in notes)


def test_adapter_preserves_duplicate_rows(person_a_events, tmp_path):
    duplicated = pl.concat([
        person_a_events,
        person_a_events.head(1),
    ])

    out, _ = run_person_b_adapter(
        duplicated.reverse(), tmp_path, mode="preserve"
    )

    assert out.height == 17
    assert_frame_equal(
        out.select(duplicated.columns).sort(SORT_KEYS),
        duplicated.sort(SORT_KEYS),
    )


def test_adapter_accepts_empty_person_a_output(person_a_events, tmp_path):
    empty = person_a_events.head(0)

    out, notes = run_person_b_adapter(
        empty, tmp_path, mode="default"
    )

    assert out.height == 0
    assert out.width == 12
    assert out.schema["ts"] == pl.Datetime("us")
    assert out.schema["status"] == pl.Int64
    assert out.schema["reject_signal"] == pl.Boolean
    assert out.schema["cap_present"] == pl.Boolean
    assert any("empty" in note for note in notes)
