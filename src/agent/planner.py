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


class LLMPlanner(Planner):
    """Model-driven planning over registry.get_tool_specs().

    Deliberately unimplemented until the rule path is proven end to end. The
    orchestrator already treats planners interchangeably, so landing this is a
    self-contained change: build a tool-use request from get_tool_specs(),
    run the loop at temperature 0, and return the same Plan object.
    """

    name = "llm"

    def __init__(self, cfg):
        self.cfg = cfg
        self.model = cfg.get("agent", {}).get("model")
        self.temperature = cfg.get("agent", {}).get("temperature", 0.0)

    def plan(self, query: str, context: dict) -> Plan:
        raise NotImplementedError(
            "LLMPlanner is Step 4. Set agent.planner: rules in config.yaml. "
            "Tool definitions are already available via registry.get_tool_specs()."
        )


def get_planner(cfg) -> Planner:
    kind = (cfg.get("agent", {}).get("planner") or "rules").lower()
    if kind == "rules":
        return RulePlanner()
    if kind == "llm":
        return LLMPlanner(cfg)
    raise ValueError(f"agent.planner must be 'rules' or 'llm', got {kind!r}")
