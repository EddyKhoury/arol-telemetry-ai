"""The shared tool registry.

Audit finding F3: the orchestrator has to hand the planner a list of callable
tools with typed parameters. A bare `def f(events, **params)` signature gives
us nothing to generate that from, and a hand-maintained parallel list of
schemas drifts from the code within a week.

Both sides register here. Person A registers ingestion/statistical tools,
Person B registers KPI tools; `get_tool_specs()` produces the planner's tool
list from the same declarations the functions are actually called with, so the
two cannot disagree.

Audit finding F4: parameter names are frozen in PARAM_VOCABULARY. Every tool
that takes a time window calls it `start`/`end`, every tool that takes a head
calls it `head_id`. ALIASES absorbs the obvious near-misses an LLM will emit.
"""

from __future__ import annotations

from typing import Callable

from . import envelope as env

# --- the frozen parameter vocabulary (F4) ---------------------------------

PARAM_VOCABULARY: dict[str, dict] = {
    "start": {"type": "string",
              "description": "Window start, ISO-8601, plant-local. Inclusive."},
    "end": {"type": "string",
            "description": "Window end, ISO-8601, plant-local. Exclusive."},
    "head_id": {"type": ["string", "array"],
                "description": "Head, e.g. 'H05', or a list of heads. Omit for all heads."},
    "machine_id": {"type": "string",
                   "description": "Machine identifier, e.g. 'MCC777'. Omit for all machines."},
    "pool": {"type": "string",
             "description": "Which data pool to analyse, e.g. 'feb'."},
    "bucket": {"type": "string", "enum": ["hour", "shift", "day", "week"],
               "description": "Time granularity to group by."},
    "cap_present_only": {"type": "boolean",
                         "description": "Restrict to closures where a cap was actually applied."},
    "min_n": {"type": "integer",
              "description": "Suppress groups with fewer than this many events."},
    "sigma": {"type": "number",
              "description": "Standard deviations from the mean before flagging an anomaly."},
    "window_seconds": {"type": "integer",
                       "description": "Rolling window length in seconds."},
}

# What a planner is likely to say -> what the tools actually accept.
ALIASES: dict[str, str] = {
    "head": "head_id", "head_no": "head_id", "heads": "head_id",
    "head_ids": "head_id", "machine": "machine_id", "from": "start",
    "to": "end", "since": "start", "until": "end", "from_date": "start",
    "to_date": "end", "start_time": "start", "end_time": "end",
    "granularity": "bucket", "group_by": "bucket", "freq": "bucket",
    "interval": "bucket", "threshold_sigma": "sigma", "n_sigma": "sigma",
    "dataset": "pool", "pool_id": "pool",
}

# Which named agent owns a tool (F10 - the MAS framing).
AGENTS = ("ingestion", "cleaning", "analytics", "kpi")

_REGISTRY: dict[str, "ToolSpec"] = {}


class ToolSpec:
    def __init__(self, fn: Callable, name: str, description: str,
                 params: list[str], agent: str, owner: str,
                 required: list[str]):
        self.fn = fn
        self.name = name
        self.description = description
        self.params = params
        self.agent = agent
        self.owner = owner
        self.required = required

    def json_schema(self) -> dict:
        """The tool definition handed to an LLM for function calling."""
        props = {p: dict(PARAM_VOCABULARY[p]) for p in self.params}
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": props,
                "required": list(self.required),
            },
        }


def tool(*, name: str, description: str, params: list[str],
         agent: str = "analytics", owner: str = "B",
         required: list[str] | None = None):
    """Register an analysis function as an agent-callable tool.

    Every parameter must already exist in PARAM_VOCABULARY - that is what
    stops the two halves of the project inventing divergent names.
    """
    def decorate(fn: Callable) -> Callable:
        unknown = [p for p in params if p not in PARAM_VOCABULARY]
        if unknown:
            raise KeyError(
                f"{name}: parameters {unknown} are not in PARAM_VOCABULARY. "
                "Add them there first so both sides agree on the name."
            )
        if agent not in AGENTS:
            raise ValueError(f"{name}: agent must be one of {AGENTS}")
        if name in _REGISTRY:
            raise KeyError(f"tool {name!r} is already registered")
        _REGISTRY[name] = ToolSpec(fn, name, description, params, agent,
                                   owner, required or [])
        fn.tool_name = name
        return fn
    return decorate


def normalise_params(params: dict) -> tuple[dict, list[str]]:
    """Map aliases onto canonical names. Returns (params, renames_applied)."""
    out, renames = {}, []
    for key, value in params.items():
        canonical = ALIASES.get(key, key)
        if canonical != key:
            renames.append(f"{key}->{canonical}")
        out[canonical] = value
    return out, renames


def get_tool_specs(agent: str | None = None) -> list[dict]:
    """Tool definitions for the planner, optionally filtered to one agent."""
    return [s.json_schema() for s in _REGISTRY.values()
            if agent is None or s.agent == agent]


def list_tools() -> list[str]:
    return sorted(_REGISTRY)


def get(name: str):
    return _REGISTRY.get(name)


def call_tool(name: str, events, **params) -> dict:
    """Invoke a registered tool and guarantee a well-formed envelope.

    Never raises. A missing tool, a bad parameter, or a bug inside the tool
    all come back as a failure envelope, because the orchestrator has to be
    able to degrade and still produce a report.
    """
    spec = _REGISTRY.get(name)
    if spec is None:
        return env.failure(
            f"no such tool {name!r}; available: {', '.join(list_tools())}",
            tool=name, params=params,
        )

    params, renames = normalise_params(params)
    unknown = [p for p in params if p not in spec.params]
    if unknown:
        return env.failure(
            f"{name} does not accept {unknown}; it accepts {spec.params}",
            tool=name, params=params,
        )
    missing = [p for p in spec.required if p not in params]
    if missing:
        return env.failure(f"{name} requires {missing}", tool=name,
                           params=params)

    try:
        with env.Timer() as timer:
            result = spec.fn(events, **params)
    except Exception as exc:  # a tool bug must not kill the whole report
        return env.failure(f"{type(exc).__name__}: {exc}", tool=name,
                           params=params)

    if not isinstance(result, dict) or "meta" not in result:
        return env.failure(
            f"{name} returned {type(result).__name__}, not an envelope",
            tool=name, params=params,
        )

    # Fill in what the tool did not have to bother with itself.
    meta = result["meta"]
    meta["tool"] = meta.get("tool") or name
    meta["agent"] = spec.agent
    meta["params"] = env.jsonable(params)
    meta["elapsed_ms"] = round(timer.ms, 2)
    if renames:
        meta["filters_applied"] = list(meta.get("filters_applied", [])) + \
            [f"param alias {r}" for r in renames]
    return result
