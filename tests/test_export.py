"""Plots and export - WP4.

The brief asks for "reports plus plots and tables", so these are deliverables.
Two properties matter beyond "it produced a file":

  - a figure renders what a tool already returned, so a number in a chart is
    the same number as in the findings;
  - neither plotting nor export may cost the user a report they already have,
    so every failure path degrades instead of raising.
"""

import json

import pytest

from src.agent.orchestrator import Orchestrator
from src.common import registry as R
from src.interface import export, plots


@pytest.fixture
def results(events):
    """Envelopes from real tools, as deliver() would pass them."""
    return [(name, R.call_tool(name, events, **kwargs))
            for name, kwargs in [("success_rate", {}),
                                 ("success_rate_per_head", {}),
                                 ("anomaly_heads", {}),
                                 ("idle_periods", {}),
                                 ("throughput", {"bucket": "hour"}),
                                 ("head_detail", {"head_id": "H01"})]]


# --- plots ----------------------------------------------------------------

def test_every_plottable_tool_produces_a_figure(results, tmp_path):
    made = dict(plots.render(results, tmp_path))
    for name in ("success_rate", "success_rate_per_head", "throughput",
                 "idle_periods", "head_detail"):
        assert name in made, f"{name} produced no figure"
        assert made[name].exists() and made[name].stat().st_size > 1000


def test_a_tool_without_a_plotter_is_skipped(results, tmp_path):
    """anomaly_heads has no figure; that must not be an error."""
    made = dict(plots.render(results, tmp_path))
    assert "anomaly_heads" not in made


def test_failed_results_are_not_plotted(events, tmp_path):
    bad = [("success_rate", R.call_tool("success_rate", events,
                                        start="2030-01-01"))]
    assert plots.render(bad, tmp_path) == []


def test_a_broken_plotter_does_not_lose_the_report(results, tmp_path, monkeypatch):
    """A figure is a nice-to-have; the text is the deliverable."""
    monkeypatch.setitem(plots.PLOTTERS, "success_rate",
                        lambda r, d: (_ for _ in ()).throw(RuntimeError("boom")))
    made = dict(plots.render(results, tmp_path))
    assert "success_rate" not in made
    assert "throughput" in made          # the others still rendered


def test_figures_are_deterministic(results, tmp_path):
    """Same envelope, same bytes - no timestamp or jitter baked in."""
    first = tmp_path / "a"
    second = tmp_path / "b"
    made_a = dict(plots.render(results, first))
    made_b = dict(plots.render(results, second))
    for name in made_a:
        assert made_a[name].read_bytes() == made_b[name].read_bytes(), name


# --- markdown -> html -----------------------------------------------------

@pytest.mark.parametrize("markdown,expected", [
    ("# Title", "<h1>Title</h1>"),
    ("## 1. Goal", "<h2>1. Goal</h2>"),
    ("- a bullet", "<li>a bullet</li>"),
    ("**bold**", "<strong>bold</strong>"),
    ("`code`", "<code>code</code>"),
    ("---", "<hr>"),
])
def test_markdown_constructs_convert(markdown, expected):
    assert expected in export.markdown_to_html_body(markdown)


def test_a_table_converts():
    body = export.markdown_to_html_body(
        "| # | step |\n|---|------|\n| 0 | plan |")
    assert "<table>" in body and "<th>step</th>" in body and "<td>plan</td>" in body


def test_html_is_escaped_not_injected():
    body = export.markdown_to_html_body("- <script>alert(1)</script>")
    assert "<script>" not in body and "&lt;script&gt;" in body


def test_figures_are_embedded_before_the_limits_section(results, tmp_path):
    made = plots.render(results, tmp_path)
    html = export.to_html("## 4. Findings\n\n## 5. Confidence and limits\n",
                          figures=made)
    assert "<figure>" in html
    assert html.index("<figure>") < html.index("5. Confidence and limits")


# --- end to end through the orchestrator ----------------------------------

def test_deliver_writes_every_requested_format(cfg, tmp_path):
    cfg["agent"]["report_dir"] = str(tmp_path / "reports")
    cfg["agent"]["trace_dir"] = str(tmp_path / "logs")
    agent = Orchestrator(cfg)
    answer = agent.answer("is anything wrong with head 26?")

    paths = agent.deliver(answer, formats=["markdown", "plots", "html"])
    assert paths["report"].endswith(".md")
    assert paths["html"].endswith(".html")
    assert paths["figures"]
    assert json.loads(open(paths["trace"], encoding="utf-8").read())["n_tool_calls"] >= 1


def test_markdown_only_writes_no_figures(cfg, tmp_path):
    """The terminal user should not pay a second for charts they cannot see."""
    cfg["agent"]["report_dir"] = str(tmp_path / "reports")
    cfg["agent"]["trace_dir"] = str(tmp_path / "logs")
    agent = Orchestrator(cfg)
    paths = agent.deliver(agent.answer("kpi summary"), formats=["markdown"])
    assert "figures" not in paths and "html" not in paths


def test_no_save_writes_nothing(cfg, tmp_path):
    cfg["agent"]["report_dir"] = str(tmp_path / "reports")
    agent = Orchestrator(cfg)
    assert agent.deliver(agent.answer("kpi summary"), save=False) == {}


# --- PDF: the failure paths, which are the ones that matter --------------
#
# save_pdf shells out to a headless Chrome/Edge. Asserting that a PDF appears
# would tie the suite to whatever browser happens to be installed. What must
# hold on every machine is the promise in its docstring: a missing PDF never
# costs the user the report they already have.

def test_no_browser_returns_none_rather_than_raising(tmp_path, monkeypatch):
    from src.interface import export

    html = tmp_path / "r.html"
    html.write_text("<p>hi</p>", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.setattr("pathlib.Path.exists",
                        lambda self: self.suffix == ".html")
    assert export.save_pdf(html) is None


def test_a_browser_that_crashes_returns_none(tmp_path, monkeypatch):
    from src.interface import export

    html = tmp_path / "r.html"
    html.write_text("<p>hi</p>", encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("browser exploded")
    monkeypatch.setattr("subprocess.run", boom)
    assert export.save_pdf(html) is None


def test_a_browser_that_writes_nothing_returns_none(tmp_path, monkeypatch):
    """Chrome can exit 0 and still produce no file. Returning the path anyway
    would hand the caller a path to nothing."""
    from src.interface import export

    html = tmp_path / "r.html"
    html.write_text("<p>hi</p>", encoding="utf-8")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: None)
    assert export.save_pdf(html) is None


def test_deliver_still_reports_when_the_pdf_cannot_be_made(cfg, tmp_path,
                                                           monkeypatch):
    """The whole point: no browser on the exam machine must not mean no
    report."""
    from pathlib import Path

    from src.agent.orchestrator import Orchestrator
    from src.interface import export

    monkeypatch.setattr(export, "save_pdf", lambda *a, **k: None)
    cfg["agent"]["report_dir"] = str(tmp_path / "reports")
    cfg["agent"]["trace_dir"] = str(tmp_path / "logs")

    agent = Orchestrator(cfg)
    answer = agent.answer("kpi summary")
    paths = agent.deliver(answer, formats=["markdown", "html", "pdf"])

    assert "pdf" not in paths            # honestly absent
    assert Path(paths["report"]).exists()
    assert Path(paths["html"]).exists()
