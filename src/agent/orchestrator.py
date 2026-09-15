"""The orchestrator - the agent loop from reference diagram 02.

    user query
      -> parse intent (scope, filters, time window)
      -> ambiguous? ask the user
      -> plan tool sequence from the registry
      -> execute tools (structured results only)
      -> validate results (empty, error, low n) -> retry, or degrade
      -> assemble report (findings, limits, next checks)
      -> deliver (text, trace log)

Under the MAS framing this is the Orchestrator agent. It delegates to the
Ingestion agent (via the data source), then to the Analytics/KPI agents (via
the tool registry), and never computes anything itself.
"""

from __future__ import annotations

from pathlib import Path

from ..common import config as config_mod
from ..common import datasource, registry
from ..analytics import kpi  # noqa: F401 - importing registers the KPI tools
from . import report as report_mod
from .planner import get_planner
from .trace import Trace

# Filters worth dropping on a retry, least destructive first.
RELAXABLE = ("start", "end", "head_id")


class Orchestrator:
    def __init__(self, cfg=None, source=None, planner=None):
        self.cfg = cfg if cfg is not None else config_mod.load()
        self.source = source or datasource.get_source(self.cfg)
        self.planner = planner or get_planner(self.cfg)
        self.min_n = config_mod.get(self.cfg, "analytics.min_n", 30)
        self.max_steps = config_mod.get(self.cfg, "agent.max_steps", 8)

    # -- the loop ----------------------------------------------------------

    def answer(self, query: str, pool: str | None = None) -> dict:
        trace = Trace(query, planner=self.planner.name)

        pool = pool or (self.source.list_pools() or ["synthetic"])[0]
        plan = self.planner.plan(query, {"pool": pool})

        # A planner that quietly fell back must say so: the report header
        # names the planner, and naming the one we asked for rather than the
        # one that answered would misrepresent how the answer was produced.
        fallback_error = getattr(self.planner, "last_error", None)
        if fallback_error:
            trace.planner = f"{self.planner.name}->rules (fallback)"
            trace.note(f"{self.planner.name} planner unavailable "
                       f"({fallback_error}); routed by keyword rules instead")

        trace.step("plan", goal=plan.goal, rationale=plan.rationale,
                   calls=[c[0] for c in plan.calls], filters=plan.filters,
                   ambiguous=plan.ambiguous)

        if plan.ambiguous:
            trace.note("stopped for clarification")
            return {
                "status": "needs_clarification",
                "query": query,
                "message": plan.clarification,
                "markdown": f"# Clarification needed\n\n{plan.clarification}\n",
                "results": [],
                "plan": plan,
                "trace": trace,
            }

        try:
            events = self.source.load_pool(pool)
            meta = self.source.pool_meta(pool)
            trace.step("load_pool", pool=pool, n_events=int(len(events)),
                       source=self.source.name)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            trace.step("load_pool", pool=pool, ok=False, error=message)
            trace.note("degraded: no data could be loaded")
            return {
                "status": "degraded",
                "query": query,
                "message": f"Could not load pool {pool!r}: {message}",
                "markdown": (f"# Report unavailable\n\nCould not load pool "
                             f"`{pool}`.\n\n> {message}\n"),
                "results": [],
                "plan": plan,
                "trace": trace,
            }

        results = []
        for tool_name, params in plan.calls[:self.max_steps]:
            result = registry.call_tool(tool_name, events, **params)
            trace.tool_call(tool_name, params, result)

            if not result["ok"]:
                retried = self._retry(tool_name, params, events, trace)
                if retried is not None:
                    result = retried
            results.append((tool_name, result))

        ok = [r for _, r in results if r["ok"]]
        if not ok:
            trace.note("degraded: every tool returned an error")
            status = "degraded"
        elif len(ok) < len(results):
            trace.note("partial: some tools returned no result")
            status = "partial"
        else:
            status = "ok"
        trace.step("validate", status=status, n_ok=len(ok), n_total=len(results))

        markdown = report_mod.assemble(query, plan, results, meta, trace,
                                       min_n=self.min_n)
        trace.step("assemble", chars=len(markdown))

        return {
            "status": status,
            "query": query,
            "message": "",
            "markdown": markdown,
            "results": results,
            "plan": plan,
            "trace": trace,
            "pool_meta": meta,
        }

    def _retry(self, tool_name, params, events, trace):
        """Relax one filter at a time and try again, as diagram 02 requires."""
        for key in RELAXABLE:
            if key not in params:
                continue
            relaxed = {k: v for k, v in params.items() if k != key}
            trace.step("retry", tool=tool_name, dropped=key, params=relaxed)
            result = registry.call_tool(tool_name, events, **relaxed)
            trace.tool_call(tool_name, relaxed, result)
            if result["ok"]:
                result["meta"]["notes"] = (
                    (result["meta"].get("notes") or "") +
                    f" (retried without {key}; the original filter matched nothing)"
                ).strip()
                return result
        return None

    # -- delivery ----------------------------------------------------------

    def deliver(self, answer: dict, *, save=True, formats=None) -> dict:
        """Write the report, its figures and its trace. Returns the paths.

        Markdown and the trace always. Plots and HTML/PDF are opt-in per call
        or via agent.export in config, because rendering figures costs a
        second or so and the terminal user usually does not want them.
        """
        paths = {}
        if not save:
            return paths

        report_dir = Path(config_mod.get(self.cfg, "agent.report_dir", "reports"))
        wanted = formats if formats is not None else             (config_mod.get(self.cfg, "agent.export") or ["markdown"])

        md_path = report_mod.save(answer["markdown"], report_dir)
        paths["report"] = str(md_path)
        paths["trace"] = str(answer["trace"].save(
            config_mod.get(self.cfg, "agent.trace_dir", "logs")))

        figures = []
        if "plots" in wanted or "html" in wanted or "pdf" in wanted:
            from ..interface import plots as plots_mod
            figures = plots_mod.render(answer["results"],
                                       report_dir / md_path.stem)
            paths["figures"] = [str(p) for _, p in figures]

        if "html" in wanted or "pdf" in wanted:
            from ..interface import export as export_mod
            html_path = export_mod.save_html(
                answer["markdown"], report_dir / md_path.stem,
                figures=figures, stem=md_path.stem)
            paths["html"] = str(html_path)
            if "pdf" in wanted:
                pdf = export_mod.save_pdf(html_path)
                if pdf is not None:
                    paths["pdf"] = str(pdf)
        return paths
