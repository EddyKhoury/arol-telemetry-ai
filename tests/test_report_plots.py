"""Figures derive from successful tool results and the saved report links them."""

from pathlib import Path

from src.interface.plots import render


def test_histogram_and_temporal_figures_from_envelopes(tmp_path):
    replies = [
        ("torque_distribution", {"ok": True, "result": {
            "bin_edges": [1.0, 2.0, 3.0], "counts": [3, 5]}}),
        ("observed_throughput", {"ok": True, "result": {"by_bucket": [
            {"bucket_start": "2026-02-01T00:00:00", "observed_events_per_hour": 12.0},
            {"bucket_start": "2026-02-01T01:00:00", "observed_events_per_hour": 9.0}]}}),
    ]
    figures = render(replies, tmp_path)
    assert [name for name, _ in figures] == ["torque_distribution", "observed_throughput"]
    for _, path in figures:
        assert Path(path).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_empty_and_failed_analyses_do_not_fabricate_plots(tmp_path):
    assert render([("torque_distribution", {"ok": True, "result": {
        "bin_edges": [], "counts": []}}),
        ("torque_trend", {"ok": False, "result": {}})], tmp_path) == []
