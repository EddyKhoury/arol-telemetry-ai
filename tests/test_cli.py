"""The command-line interface - WP4, and the surface the demo actually uses.

This module had 0% coverage. Every other part of the system was tested and the
thing a human types was not, which is the wrong way round for a project whose
assessment includes a live demonstration: a broken `report idle` is invisible
to the rest of the suite and very visible in front of a panel.

Every test here runs against a temp config pinned to the synthetic source and
the rule-based planner, so nothing touches a model server, the real telemetry,
or the developer's own config.local.yaml.
"""

import sys
from pathlib import Path

import pytest
import yaml

from src.common import config as config_mod
from src.interface import cli


@pytest.fixture
def cli_config(tmp_path):
    """A config file of our own: synthetic data, rules planner, temp output.

    config_mod.load only merges config.local.yaml when the path IS the repo
    default, so pointing at a temp file isolates these tests from whatever the
    developer has set locally - including `source: person_a`, which would make
    the CLI tests depend on a Parquet file being present.
    """
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    cfg["data"]["source"] = "synthetic"
    cfg["data"]["synthetic"] = {**cfg["data"]["synthetic"],
                                "days": 1, "n_heads": 4,
                                "closure_interval_seconds": 120.0}
    cfg["agent"]["planner"] = "rules"
    cfg["agent"]["report_dir"] = str(tmp_path / "reports")
    cfg["agent"]["trace_dir"] = str(tmp_path / "logs")
    cfg["agent"]["export"] = ["markdown"]
    cfg["data"]["cache_dir"] = str(tmp_path / "cache")

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def _run(cli_config, *argv):
    return cli.main(["--config", str(cli_config), *argv])


# --- the informational commands ------------------------------------------

def test_tools_lists_every_registered_tool(cli_config, capsys):
    from src.common import registry

    assert _run(cli_config, "tools") == 0
    out = capsys.readouterr().out
    for name in registry.list_tools():
        assert name in out, f"{name} missing from `tools` output"
    assert "params:" in out


def test_tools_names_the_owning_agent(cli_config, capsys):
    """The MAS framing (F10) is declared in code and must be visible."""
    _run(cli_config, "tools")
    assert "[kpi/B]" in capsys.readouterr().out


def test_pools_lists_a_pool_with_its_window(cli_config, capsys):
    assert _run(cli_config, "pools") == 0
    out = capsys.readouterr().out
    assert "synthetic" in out and "events" in out and "->" in out


# --- the canned reports ---------------------------------------------------

@pytest.mark.parametrize("kind", sorted(cli.REPORT_QUERIES))
def test_every_canned_report_produces_findings(cli_config, kind, capsys):
    """`report <kind>` is sugar for a query. A kind whose query no longer
    routes to a tool would still exit 0 while printing an empty report - so
    assert on the findings, not the exit code."""
    assert _run(cli_config, "--no-save", "report", kind) == 0
    out = capsys.readouterr().out
    assert "## 4. Findings" in out
    assert "No analysis produced a result" not in out, \
        f"`report {kind}` routed to nothing"


def test_report_rejects_an_unknown_kind(cli_config):
    with pytest.raises(SystemExit) as excinfo:
        _run(cli_config, "report", "nonsense")
    assert excinfo.value.code == 2


# --- ask ------------------------------------------------------------------

def test_ask_answers_and_exits_zero(cli_config, capsys):
    assert _run(cli_config, "--no-save", "ask", "what is the success rate?") == 0
    assert "## 4. Findings" in capsys.readouterr().out


def test_ask_joins_a_multi_word_question(cli_config, capsys):
    """`question` is nargs="+", so an unquoted question arrives as a list."""
    assert _run(cli_config, "--no-save", "ask",
                "which", "head", "is", "worst") == 0     # unquoted, 4 argv items
    assert "## 4. Findings" in capsys.readouterr().out


def test_an_unanswerable_question_exits_nonzero(cli_config, capsys):
    """A shell caller needs to be able to tell 'I answered' from 'I could not'.
    Clarification is not success."""
    assert _run(cli_config, "--no-save", "ask", "what is the weather") == 1
    assert "Clarification needed" in capsys.readouterr().out


# --- saving ---------------------------------------------------------------

def test_a_report_and_trace_are_written_by_default(cli_config, tmp_path, capsys):
    assert _run(cli_config, "ask", "what is the success rate?") == 0
    reports = list((tmp_path / "reports").glob("*.md"))
    traces = list((tmp_path / "logs").glob("*.json"))
    assert len(reports) == 1 and len(traces) == 1
    assert "## 4. Findings" in reports[0].read_text(encoding="utf-8")
    assert "[saved] report" in capsys.readouterr().err


def test_no_save_writes_nothing(cli_config, tmp_path):
    assert _run(cli_config, "--no-save", "ask", "what is the success rate?") == 0
    assert not (tmp_path / "reports").exists() or \
        not list((tmp_path / "reports").glob("*.md"))


def test_the_trace_reproduces_the_report(cli_config, tmp_path):
    """Audit F15: a report nobody can retrace is not explainable."""
    import json

    _run(cli_config, "ask", "which heads are anomalous")
    trace = json.loads(list((tmp_path / "logs").glob("*.json"))[0]
                       .read_text(encoding="utf-8"))
    kinds = [step["kind"] for step in trace["steps"]]
    assert kinds[0] == "plan" and "tool_call" in kinds and "assemble" in kinds
    assert trace["planner"] == "rules"


def test_format_html_produces_an_html_file(cli_config, tmp_path):
    assert _run(cli_config, "--format", "html",
                "ask", "what is the success rate?") == 0
    assert list((tmp_path / "reports").rglob("*.html"))


def test_an_unknown_format_is_refused(cli_config):
    with pytest.raises(SystemExit) as excinfo:
        _run(cli_config, "--format", "powerpoint", "ask", "kpis")
    assert excinfo.value.code == 2


# --- chat -----------------------------------------------------------------

def _answers(monkeypatch, *lines):
    """Feed chat a scripted stdin."""
    supply = iter(lines)

    def fake_input(prompt=""):
        try:
            return next(supply)
        except StopIteration:
            raise EOFError
    monkeypatch.setattr("builtins.input", fake_input)


def test_chat_exits_on_quit(cli_config, monkeypatch, capsys):
    _answers(monkeypatch, "quit")
    assert _run(cli_config, "chat") == 0
    assert "Ask a question" in capsys.readouterr().out


def test_chat_exits_on_eof(cli_config, monkeypatch):
    """Ctrl-D must not traceback in front of an audience."""
    _answers(monkeypatch)
    assert _run(cli_config, "chat") == 0


def test_chat_ignores_a_blank_line(cli_config, monkeypatch, capsys):
    _answers(monkeypatch, "", "   ", "quit")
    assert _run(cli_config, "chat") == 0
    assert "## 4. Findings" not in capsys.readouterr().out


def test_chat_answers_then_keeps_going(cli_config, monkeypatch, capsys):
    _answers(monkeypatch, "what is the success rate?", "quit")
    assert _run(cli_config, "--no-save", "chat") == 0
    assert "## 4. Findings" in capsys.readouterr().out


def test_chat_asks_for_clarification_without_dying(cli_config, monkeypatch,
                                                   capsys):
    """The clarification branch continues the loop rather than exiting - a
    nonsense question mid-demo must not end the session."""
    _answers(monkeypatch, "what is the weather", "what is the success rate?",
             "quit")
    assert _run(cli_config, "--no-save", "chat") == 0
    out = capsys.readouterr().out
    assert "could not tell" in out.lower()
    assert "## 4. Findings" in out          # and it carried on afterwards


# --- argument handling ----------------------------------------------------

def test_a_missing_subcommand_is_an_error(cli_config):
    with pytest.raises(SystemExit) as excinfo:
        _run(cli_config)
    assert excinfo.value.code == 2


def test_a_missing_config_file_is_reported_clearly(tmp_path):
    with pytest.raises(config_mod.ConfigError, match="no config at"):
        cli.main(["--config", str(tmp_path / "nope.yaml"), "tools"])


def test_the_pool_flag_reaches_the_orchestrator(cli_config, capsys):
    assert _run(cli_config, "--no-save", "--pool", "synthetic",
                "ask", "what is the success rate?") == 0
    assert "Pool `synthetic`" in capsys.readouterr().out
