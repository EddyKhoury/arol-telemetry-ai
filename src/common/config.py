"""Configuration loading.

All paths, thresholds and parameters live in config.yaml - the brief requires
that nothing be hard-coded. config.local.yaml, if present, is merged on top so
each of us can point at our own data without touching the shared file.
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config.yaml"
LOCAL_CONFIG = REPO_ROOT / "config.local.yaml"


class ConfigError(ValueError):
    pass


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load(path: str | Path | None = None) -> dict:
    """Load config.yaml, merge config.local.yaml over it, resolve paths."""
    path = Path(path) if path else DEFAULT_CONFIG
    if not path.exists():
        raise ConfigError(f"no config at {path}")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if LOCAL_CONFIG.exists() and path == DEFAULT_CONFIG:
        cfg = _deep_merge(cfg, yaml.safe_load(LOCAL_CONFIG.read_text(encoding="utf-8")) or {})

    for section, key in (("data", "cache_dir"), ("agent", "report_dir"),
                         ("agent", "trace_dir")):
        value = cfg.get(section, {}).get(key)
        if value and not Path(value).is_absolute():
            cfg[section][key] = str(REPO_ROOT / value)

    cfg["data"]["pools"] = {
        name: [str(REPO_ROOT / p) if not Path(p).is_absolute() else p
               for p in (files or [])]
        for name, files in (cfg.get("data", {}).get("pools") or {}).items()
    }
    return cfg


def get(cfg: dict, dotted: str, default=None):
    """cfg lookup by dotted path: get(cfg, 'analytics.anomaly_sigma')."""
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
