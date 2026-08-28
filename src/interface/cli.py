"""Command-line interface - the backbone of WP4.

    python -m src.interface.cli report kpi
    python -m src.interface.cli report anomalies --pool synthetic
    python -m src.interface.cli ask "is anything wrong with head 26?"
    python -m src.interface.cli chat
    python -m src.interface.cli tools
    python -m src.interface.cli pools

Chat mode runs the same orchestrator as the one-shot commands - there is one
agent, not two code paths that can drift apart.
"""

from __future__ import annotations

import argparse
import sys

from ..common import config as config_mod
from ..common import registry
from ..agent.orchestrator import Orchestrator

# `report <type>` is sugar for a canned query, so the CLI and the chat share
# one planner rather than having their own routing.
REPORT_QUERIES = {
    "kpi": "kpi performance summary",
    "anomalies": "which heads are anomalous",
    "idle": "idle and no load periods",
    "throughput": "throughput by hour",
}


def _run(orchestrator, query, pool, save, quiet=False):
    answer = orchestrator.answer(query, pool=pool)
    if not quiet:
        print(answer["markdown"])
    paths = orchestrator.deliver(answer, save=save)
    if paths:
        print(f"\n[saved] report: {paths['report']}", file=sys.stderr)
        print(f"[saved] trace : {paths['trace']}", file=sys.stderr)
    return answer


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="arol-agent",
        description="Agentic telemetry analysis for AROL capping machines.")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument("--pool", default=None, help="which data pool to use")
    parser.add_argument("--no-save", action="store_true",
                        help="print only; do not write report/trace files")
    sub = parser.add_subparsers(dest="command", required=True)

    p_report = sub.add_parser("report", help="generate a canned report")
    p_report.add_argument("kind", choices=sorted(REPORT_QUERIES))

    p_ask = sub.add_parser("ask", help="ask one question in plain language")
    p_ask.add_argument("question", nargs="+")

    sub.add_parser("chat", help="interactive session")
    sub.add_parser("tools", help="list registered tools")
    sub.add_parser("pools", help="list available data pools")

    args = parser.parse_args(argv)
    cfg = config_mod.load(args.config)
    orchestrator = Orchestrator(cfg)
    save = not args.no_save

    if args.command == "tools":
        for spec in registry.get_tool_specs():
            tool = registry.get(spec["name"])
            print(f"{spec['name']:<24} [{tool.agent}/{tool.owner}] "
                  f"{spec['description']}")
            print(f"{'':<24} params: {', '.join(tool.params) or '(none)'}")
        return 0

    if args.command == "pools":
        source = orchestrator.source
        for pool in source.list_pools():
            meta = source.pool_meta(pool)
            print(f"{pool:<16} {meta['n_events']:>10,} events  "
                  f"{meta['ts_min']} -> {meta['ts_max']}  "
                  f"[{meta['source'] if 'source' in meta else source.name}]")
        return 0

    if args.command == "report":
        _run(orchestrator, REPORT_QUERIES[args.kind], args.pool, save)
        return 0

    if args.command == "ask":
        answer = _run(orchestrator, " ".join(args.question), args.pool, save)
        return 0 if answer["status"] in ("ok", "partial") else 1

    if args.command == "chat":
        print("AROL telemetry agent. Ask a question, or 'quit'.\n")
        while True:
            try:
                query = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if query.lower() in {"quit", "exit", "q"}:
                return 0
            if not query:
                continue
            answer = orchestrator.answer(query, pool=args.pool)
            if answer["status"] == "needs_clarification":
                print(f"\n{answer['message']}\n")
                continue
            print("\n" + answer["markdown"] + "\n")
            orchestrator.deliver(answer, save=save)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
