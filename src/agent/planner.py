"""Planners: decide which tools to call, with which parameters.

Two implementations behind one interface:

  RulePlanner  deterministic keyword routing. No network, no API key, no model.
  LLMPlanner   the model picks tools from registry.get_tool_specs().

The rule planner is built first on purpose. It proves the whole dispatch and
report path end to end without a model in the way, it is the determinism
baseline the LLM planner is checked against, and it is the fallback if the API
is unreachable during the demo. `agent.planner` in config.yaml selects one.

Neither planner ever computes a number. It chooses tools and arguments; the
tools do the arithmetic. That separation is the project's central claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..common import registry


@dataclass
class Plan:
    """What the planner decided to do."""
    goal: str
    calls: list[tuple[str, dict]] = field(default_factory=list)
    filters: dict = field(default_factory=dict)
    ambiguous: bool = False
    clarification: str = ""
    rationale: str = ""


class Planner:
    name = "abstract"

    def plan(self, query: str, context: dict) -> Plan:
        raise NotImplementedError


# --- intent parsing --------------------------------------------------------

HEAD_RE = re.compile(r"\bh(?:ead)?\s*[-#]?\s*(\d{1,2})\b", re.I)
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
BUCKET_WORDS = {"hour": "hour", "hourly": "hour", "shift": "shift",
                "day": "day", "daily": "day", "week": "week", "weekly": "week"}

INTENTS = (
    # (name, keywords, goal, tool calls as (tool, extra params))
    ("anomalies",
     ("anomal", "wrong", "problem", "issue", "fault", "outlier", "suspicious",
      "reject", "failing", "fail"),
     "Identify heads behaving abnormally and quantify how far out they are.",
     [("anomaly_heads", {}), ("success_rate_per_head", {})]),
    ("idle",
     ("idle", "downtime", "down time", "starv", "no load", "no-load", "stopped",
      "stoppage", "empty"),
     "Locate sustained No Load stretches and attribute them to heads.",
     [("idle_periods", {}), ("success_rate", {})]),
    ("throughput",
     ("throughput", "speed", "output", "productivity", "rate per hour",
      "pieces", "capping speed", "how many", "volume"),
     "Measure capping speed over time.",
     [("throughput", {"bucket": "hour"}), ("success_rate", {})]),
    ("kpi",
     ("kpi", "performance", "success", "summary", "overview", "report",
      "how is", "health", "quality"),
     "Summarise machine performance against the agreed KPIs.",
     [("success_rate", {}), ("success_rate_per_head", {})]),
)


def parse_intent(query: str) -> tuple[str, dict]:
    """Extract the intent name and any filters the query pins down."""
    text = (query or "").lower()

    filters: dict = {}
    heads = [f"H{int(m):02d}" for m in HEAD_RE.findall(text)]
    if heads:
        filters["head_id"] = heads[0] if len(heads) == 1 else heads

    dates = DATE_RE.findall(text)
    if len(dates) == 1:
        filters["start"] = dates[0]
    elif len(dates) >= 2:
        filters["start"], filters["end"] = dates[0], dates[1]

    for word, bucket in BUCKET_WORDS.items():
        if re.search(rf"\b(?:per|by|each)\s+{word}\b", text) or f"{word}ly" in text:
            filters["bucket"] = bucket
            break

    best, best_hits = None, 0
    for name, keywords, _, _ in INTENTS:
        hits = sum(1 for k in keywords if k in text)
        if hits > best_hits:
            best, best_hits = name, hits

    return (best or "unknown"), filters


class RulePlanner(Planner):
    """Deterministic keyword routing. Same query in, same plan out, always."""

    name = "rules"

    def plan(self, query: str, context: dict) -> Plan:
        intent, filters = parse_intent(query)

        if intent == "unknown":
            available = ", ".join(name for name, *_ in INTENTS)
            return Plan(
                goal="Clarify what the user is asking for.",
                ambiguous=True,
                clarification=(
                    f"I could not tell which analysis you want. Ask about one of: "
                    f"{available}. For example: 'success rate per head yesterday', "
                    f"'is anything wrong with head 5', 'throughput by hour'."
                ),
                rationale="no intent keyword matched",
            )

        name, _, goal, calls = next(i for i in INTENTS if i[0] == intent)

        # When the user names a head, answer about THAT head first. The
        # fleet-comparison tools cannot take a single head - an outlier test
        # needs something to compare against - so without this the question
        # silently widened from "is head 26 bad?" to "which heads are bad?".
        if "head_id" in filters and registry.get("head_detail") is not None:
            calls = [("head_detail", {})] + list(calls)
            goal = (f"Assess head {filters['head_id']} and place it against "
                    f"the rest of the fleet.")

        resolved = []
        for tool_name, extra in calls:
            spec = registry.get(tool_name)
            params = dict(extra)
            # Only pass filters the tool actually declares - the registry would
            # reject the rest, and a rejected call wastes a step.
            for key, value in filters.items():
                if spec and key in spec.params:
                    params[key] = value
            resolved.append((tool_name, params))

        return Plan(
            goal=goal,
            calls=resolved,
            filters=filters,
            rationale=f"matched intent {name!r} on keyword overlap",
        )


SYSTEM_PROMPT = """You route questions about industrial capping-machine \
telemetry to analysis tools. You do NOT answer the question yourself and you \
NEVER compute, estimate or invent a number - deterministic Python functions do \
all arithmetic.

Choose one or more of the supplied tools that together answer the user's \
question, and fill in only parameters the user actually specified. Omit any \
parameter they did not mention rather than guessing a value.

If the question is not about capping telemetry, or is too vague to map onto a \
tool, call no tools and reply with one short sentence saying what you need."""


def _to_ollama_tools(specs: list[dict]) -> list[dict]:
    """registry's Anthropic-style specs -> the OpenAI/Ollama function shape."""
    return [
        {"type": "function",
         "function": {"name": s["name"],
                      "description": s["description"],
                      "parameters": s["input_schema"]}}
        for s in specs
    ]


class LLMPlanner(Planner):
    """Model-driven planning over registry.get_tool_specs().

    Talks to a local Ollama server, so the whole system runs offline: no API
    key, no network, and - unlike a hosted endpoint, where server-side batching
    makes even temperature 0 non-deterministic - a fixed seed makes the routing
    itself reproducible.

    The model only ever picks tool names and arguments. Every number in the
    report still comes from tested Python, so a weak local model can misroute
    but cannot produce a wrong figure.

    Any failure - server down, model missing, timeout, unparseable reply -
    falls back to RulePlanner rather than losing the answer. The trace records
    which planner actually ran, so a report never misrepresents itself.
    """

    name = "llm"

    def __init__(self, cfg):
        self.cfg = cfg
        agent = cfg.get("agent", {}) or {}
        llm = agent.get("llm", {}) or {}
        self.host = llm.get("host", "http://localhost:11434").rstrip("/")
        self.model = llm.get("model", agent.get("model", "llama3.2:3b"))
        self.temperature = float(llm.get("temperature", agent.get("temperature", 0.0)))
        self.seed = llm.get("seed", 42)
        self.timeout = float(llm.get("timeout_seconds", 60))
        self.fallback = bool(llm.get("fallback_to_rules", True))
        self._rules = RulePlanner()
        self.last_error: str | None = None

    # -- transport ---------------------------------------------------------

    def _chat(self, query: str, tools: list[dict]) -> dict:
        """One non-streaming call to Ollama. Overridden in tests."""
        import json
        import urllib.request

        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": query}],
            "tools": tools,
            "stream": False,
            "options": {"temperature": self.temperature, "seed": self.seed},
        }
        request = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def available(self) -> bool:
        """Is the server reachable and the model pulled?"""
        import json
        import urllib.request
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=3) as r:
                names = [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
            return any(n == self.model or n.startswith(self.model.split(":")[0])
                       for n in names)
        except Exception:
            return False

    # -- planning ----------------------------------------------------------

    def plan(self, query: str, context: dict) -> Plan:
        self.last_error = None
        try:
            specs = registry.get_tool_specs()
            reply = self._chat(query, _to_ollama_tools(specs))
            message = reply.get("message", {}) or {}
            calls = self._extract_calls(message)

            if not calls:
                text = (message.get("content") or "").strip()
                return Plan(
                    goal="Clarify what the user is asking for.",
                    ambiguous=True,
                    clarification=text or (
                        "I could not map that to an analysis. Ask about "
                        "anomalies, idle periods, throughput or KPIs."),
                    rationale=f"{self.model} selected no tool",
                )

            goal = (message.get("content") or "").strip() or \
                f"Answer: {query.strip()}"
            return Plan(goal=goal, calls=calls,
                        filters=dict(calls[0][1]) if calls else {},
                        rationale=f"{self.model} selected "
                                  f"{', '.join(n for n, _ in calls)}")

        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            if not self.fallback:
                raise
            plan = self._rules.plan(query, context)
            plan.rationale = (f"LLM planner unavailable ({self.last_error}); "
                              f"fell back to rules - {plan.rationale}")
            return plan

    def _extract_calls(self, message: dict) -> list[tuple[str, dict]]:
        """Keep only calls naming a registered tool with accepted parameters.

        A small local model will occasionally invent a tool or an argument.
        call_tool would reject those anyway, but dropping them here saves a
        wasted step and keeps the trace honest about what was really run.
        """
        calls: list[tuple[str, dict]] = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function", raw) or {}
            name = function.get("name")
            spec = registry.get(name) if name else None
            if spec is None:
                continue
            args = function.get("arguments") or {}
            if isinstance(args, str):
                import json
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            params, _ = registry.normalise_params(
                {k: v for k, v in args.items() if v not in (None, "")})
            calls.append((name, {k: v for k, v in params.items()
                                 if k in spec.params}))
        return calls


def get_planner(cfg) -> Planner:
    kind = (cfg.get("agent", {}).get("planner") or "rules").lower()
    if kind == "rules":
        return RulePlanner()
    if kind == "llm":
        return LLMPlanner(cfg)
    raise ValueError(f"agent.planner must be 'rules' or 'llm', got {kind!r}")
