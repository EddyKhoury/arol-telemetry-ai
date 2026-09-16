"""Where the event table comes from - the one-key Phase-5 swap.

`data.source` is the single key that moves the whole system from synthetic
data to Person A's real output. It had 60% coverage, and the branch with the
least coverage was PersonASource, which is the one that now runs the demo.

A failure here does not produce a wrong number; it produces no report at all,
or a report about the wrong data. Both are worse.
"""

from datetime import datetime, timedelta

import polars as pl
import pytest

from src.common import datasource, schema
from src.ingestion import adapter


def _person_a_parquet(path, statuses=(0, 0, 2, 65), heads=("H01", "H02")):
    """Write a Parquet in Person A's exact event schema."""
    t0 = datetime.fromisoformat("2026-02-01T00:00:00")
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
    pl.DataFrame(rows, schema=dict(adapter.PERSON_A_COLUMNS)).write_parquet(path)
    return path


# --- the switch itself ----------------------------------------------------

@pytest.mark.parametrize("key,cls", [
    ("synthetic", datasource.SyntheticSource),
    ("person_a", datasource.PersonASource),
    ("real", datasource.RealSource),
])
def test_the_source_key_selects_the_source(cfg, key, cls):
    cfg["data"]["source"] = key
    assert isinstance(datasource.get_source(cfg), cls)


def test_the_key_is_case_insensitive(cfg):
    cfg["data"]["source"] = "Person_A"
    assert isinstance(datasource.get_source(cfg), datasource.PersonASource)


def test_an_unknown_source_names_the_valid_ones(cfg):
    """A typo in config.yaml must not read as 'no data'."""
    cfg["data"]["source"] = "postgres"
    with pytest.raises(ValueError) as excinfo:
        datasource.get_source(cfg)
    message = str(excinfo.value)
    assert "postgres" in message
    for valid in ("synthetic", "person_a", "real"):
        assert valid in message


def test_a_missing_source_key_defaults_to_synthetic(cfg):
    cfg["data"].pop("source", None)
    assert isinstance(datasource.get_source(cfg), datasource.SyntheticSource)


def test_the_interface_is_abstract():
    base = datasource.DataSource()
    for call in (base.list_pools, lambda: base.load_pool("x"),
                 lambda: base.pool_meta("x")):
        with pytest.raises(NotImplementedError):
            call()


# --- synthetic ------------------------------------------------------------

def test_synthetic_produces_a_conforming_table(cfg):
    source = datasource.get_source(cfg)
    events = source.load_pool("synthetic")
    assert schema.validate_events(events, strict=False) == []


def test_synthetic_meta_warns_that_it_is_not_real(cfg):
    """A report built on generated data must say so in its own body."""
    meta = datasource.get_source(cfg).pool_meta("synthetic")
    assert any("SYNTHETIC" in w for w in meta["warnings"])
    assert meta["source"] == "synthetic"


def test_synthetic_exposes_ground_truth(cfg):
    """Only this source has it - it is what makes precision/recall possible."""
    gt = datasource.get_source(cfg).ground_truth("synthetic")
    assert gt["faults"] and gt["schema_version"] == schema.SCHEMA_VERSION


def test_synthetic_is_generated_once_per_source(cfg):
    """Regenerating per question would make the CLI feel broken and, worse,
    a per-call seed change would break determinism."""
    source = datasource.get_source(cfg)
    assert source.load_pool("synthetic") is source.load_pool("synthetic")


# --- person_a -------------------------------------------------------------

@pytest.fixture
def person_a_cfg(cfg, tmp_path):
    parquet = _person_a_parquet(tmp_path / "feb.parquet")
    cfg["data"]["source"] = "person_a"
    cfg["data"]["person_a"] = {"feb": str(parquet)}
    return cfg


def test_person_a_output_becomes_a_conforming_table(person_a_cfg):
    events = datasource.get_source(person_a_cfg).load_pool("feb")
    assert schema.validate_events(events, strict=False) == []
    assert list(events.columns) == list(schema.EVENT_COLUMNS)
    assert events["pool_id"].unique().to_list() == ["feb"]


def test_person_a_meta_carries_the_adapter_warnings(person_a_cfg):
    """The dropped-closure warning has to reach the report, or the undercount
    is invisible to whoever reads it."""
    meta = datasource.get_source(person_a_cfg).pool_meta("feb")
    assert any("count_delta is 1 for every event" in w for w in meta["warnings"])
    assert meta["source"] == "person-a"
    assert meta["n_events"] == 8


def test_person_a_meta_does_not_claim_cleaning_it_did_not_do(person_a_cfg):
    """0 would assert the adapter checked for duplicates. Cleaning happens
    upstream and is objective 2 - Person A's, and not written yet."""
    meta = datasource.get_source(person_a_cfg).pool_meta("feb")
    assert meta["duplicates_removed"] is None
    assert meta["rows_after_cleaning"] is None


def test_only_pools_whose_file_exists_are_listed(person_a_cfg, tmp_path):
    """`pools` must not advertise a pool that cannot be loaded."""
    person_a_cfg["data"]["person_a"]["mar"] = str(tmp_path / "absent.parquet")
    assert datasource.get_source(person_a_cfg).list_pools() == ["feb"]


def test_an_unconfigured_pool_names_the_ones_that_exist(person_a_cfg):
    source = datasource.get_source(person_a_cfg)
    with pytest.raises(KeyError) as excinfo:
        source.load_pool("apr")
    assert "apr" in str(excinfo.value) and "feb" in str(excinfo.value)


def test_a_configured_but_missing_file_says_what_to_do(person_a_cfg, tmp_path):
    """The likeliest real failure: cache/ is gitignored, so a fresh clone has
    the config and not the data. The message must point at the fix."""
    person_a_cfg["data"]["person_a"]["feb"] = str(tmp_path / "gone.parquet")
    with pytest.raises(FileNotFoundError) as excinfo:
        datasource.get_source(person_a_cfg).load_pool("feb")
    message = str(excinfo.value)
    assert "gone.parquet" in message
    assert "write_event_table_parquet" in message


def test_the_parquet_is_read_and_adapted_once(person_a_cfg):
    source = datasource.get_source(person_a_cfg)
    assert source.load_pool("feb") is source.load_pool("feb")


def test_an_empty_person_a_section_lists_no_pools(cfg):
    cfg["data"]["source"] = "person_a"
    cfg["data"].pop("person_a", None)
    assert datasource.get_source(cfg).list_pools() == []


def test_a_frame_that_is_not_his_is_refused(person_a_cfg, tmp_path):
    """Pointing the key at the wrong Parquet must fail loudly, not silently
    produce a table with missing columns."""
    pl.DataFrame({"nope": [1, 2]}).write_parquet(tmp_path / "wrong.parquet")
    person_a_cfg["data"]["person_a"]["feb"] = str(tmp_path / "wrong.parquet")
    with pytest.raises(adapter.AdapterError, match="missing"):
        datasource.get_source(person_a_cfg).load_pool("feb")


# --- real (still Person A's stub) ----------------------------------------

def test_real_lists_pools_from_config(cfg, tmp_path):
    csv = tmp_path / "day.csv"
    csv.write_text("timestamp\n", encoding="utf-8")
    cfg["data"]["source"] = "real"
    cfg["data"]["pools"] = {"feb": [str(csv)], "mar": []}
    assert datasource.get_source(cfg).list_pools() == ["feb"]


def test_real_load_still_says_whose_job_it_is(cfg):
    """Until WP1 lands, the error has to name the owner and the workaround -
    this is the message anyone hits who flips the key too early."""
    from src.ingestion import api

    cfg["data"]["source"] = "real"
    cfg["data"]["pools"] = {"feb": ["nonexistent.csv"]}
    with pytest.raises(api.NotImplementedByPersonA) as excinfo:
        datasource.get_source(cfg).load_pool("feb")
    assert "Person A" in str(excinfo.value)
    assert "synthetic" in str(excinfo.value)
