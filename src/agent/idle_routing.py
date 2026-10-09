"""Strict, machine-wide raw-status idle requests."""

import re

from .torque_routing import _parse_canonical_torque_request


def parse_idle_request(query):
    text = " ".join((query or "").split()).rstrip(".?!")
    prefix = re.match(r"(?:(?:show|find|report|detect) )?(?:machine )?(?:idle|no[ -]load periods|sustained no[ -]load)(?=\s|$)", text, re.I)
    if prefix is None:
        return None
    clarification = dict(
        goal="Clarify the raw-status idle window.", ambiguous=True,
        clarification=("Ask for 'machine idle for machine M1 from <ISO> until <ISO>'. "
                       "This check needs one machine, a bounded time interval, and every head. "
                       "Head, status and threshold overrides are unsupported."),
        rationale="idle analysis requires a complete machine-wide raw-status scope")
    tail = text[prefix.end():].strip()
    plan = _parse_canonical_torque_request("Average torque " + tail)
    if plan is None or plan.get("ambiguous"):
        return clarification
    params = plan["calls"][0][1]
    if set(params) != {"machine_id", "start", "end"}:
        return clarification
    return dict(goal="Identify observed intervals with No Load on every head for the configured sustained duration.",
                calls=[("machine_idle", params)], filters=dict(params),
                rationale="bounded all-head raw-status idle request")
