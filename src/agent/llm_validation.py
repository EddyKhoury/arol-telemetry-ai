"""Strict validation of model tool proposals; never delete or repair arguments."""
import json
from datetime import datetime

VERIFIED_TOOLS = frozenset({
    "torque_stats", "torque_distribution", "torque_trend",
    "detect_torque_anomalies", "head_correlation",
})


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_calls(message, lookup):
    """Require one registered, verified tool with canonical, typed parameters."""
    if not isinstance(message, dict):
        raise ValueError("Model message must be an object")
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list) or len(raw_calls) != 1:
        raise ValueError("Exactly one tool call is required")
    raw = raw_calls[0]
    if not isinstance(raw, dict) or not isinstance(raw.get("function"), dict):
        raise ValueError("Tool call must contain a function object")
    function = raw["function"]
    name = function.get("name")
    if not isinstance(name, str) or name not in VERIFIED_TOOLS:
        raise ValueError("Model selected an unsupported tool")
    spec = lookup(name)
    if spec is None:
        raise ValueError("Model selected an unregistered tool")
    if "arguments" not in function:
        raise ValueError("Missing tool arguments object")
    args = function["arguments"]
    if isinstance(args, str):
        args = json.loads(args, object_pairs_hook=_json_object)
    if not isinstance(args, dict) or any(not isinstance(key, str) for key in args):
        raise ValueError("Tool arguments must be an object with string keys")
    unknown = set(args) - set(spec.params)
    if unknown:
        raise ValueError("Unsupported argument names: " + ", ".join(sorted(unknown)))
    missing = set(spec.required) - set(args)
    if missing:
        raise ValueError("Missing required arguments: " + ", ".join(sorted(missing)))
    bounds = {}
    for key, value in args.items():
        if key == "bins":
            if type(value) is not int or value <= 0:
                raise ValueError("bins must be a positive integer")
        elif key == "status_filter":
            if not (type(value) is int or value == "successful"):
                raise ValueError("status_filter must be an integer or 'successful'; omit unused filters")
        elif key in {"head_id", "head_a", "head_b", "machine_id", "start", "end"}:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must be a non-empty string")
            if key in {"start", "end"}:
                bound = datetime.fromisoformat(value)
                if bound.tzinfo is not None:
                    raise ValueError("Timezone-aware bounds are not supported")
                bounds[key] = bound
        else:
            raise ValueError(f"Argument has no verified validation rule: {key}")
    if "start" in bounds and "end" in bounds and bounds["start"] >= bounds["end"]:
        raise ValueError("start must be earlier than end")
    if name == "head_correlation" and args["head_a"] == args["head_b"]:
        raise ValueError("Head comparison requires distinct heads")
    return [(name, dict(args))]
