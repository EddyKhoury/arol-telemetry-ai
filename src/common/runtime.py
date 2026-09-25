"""Trusted, per-dispatch configuration kept outside model tool arguments."""

from contextvars import ContextVar
from copy import deepcopy

from . import registry
from .envelope import failure

_CONFIG = ContextVar("arol_tool_config", default=None)


def current_config():
    config = _CONFIG.get()
    if config is None:
        raise ValueError("This tool requires trusted runtime configuration")
    return deepcopy(config)


def dispatch_tool(name, events, *, config, arguments=None):
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict) or any(
        not isinstance(key, str) for key in arguments
    ):
        return failure("Tool arguments must be a dictionary with string keys", tool=name)
    if not isinstance(config, dict):
        return failure("Runtime configuration must be a dictionary", tool=name)
    reserved = sorted({"name", "events"} & set(arguments))
    if reserved:
        return failure(f"{name} does not accept {reserved}", tool=name, params=arguments)
    token = _CONFIG.set(deepcopy(config))
    try:
        return registry.call_tool(name, events, **arguments)
    finally:
        _CONFIG.reset(token)
