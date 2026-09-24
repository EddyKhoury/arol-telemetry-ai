"""Anchored diagnostic phrasings mapped onto the verified torque grammar.

Only the analysis phrase is rewritten. Every remaining character is handed
to the strict scope parser; negation, exclusions and extra clauses are not
discarded. These are explicit language templates, not general NLU accuracy.
"""
import re


def _clarify(reason):
    return {
        "goal": "Clarify the diagnostic comparison before analysing events.",
        "ambiguous": True, "clarification": reason,
        "rationale": "diagnostic context is incomplete; no data loaded or tool called",
    }


def rewrite_diagnostic_question(text):
    """Return a rewrite descriptor, a clarification, or None for no match."""
    # The question catalogue includes these intentions, but does not define
    # a fleet comparison baseline or establish a failure/root-cause metric.
    if re.match(r"(?:which head behaves differently|are any heads behaving unusually|"
                r"can you identify a head whose behavior differs)(?=\s|$)", text, re.I):
        return _clarify(
            "Specify the comparison metric and reference heads or fleet baseline, "
            "plus the machine and time window. A two-head torque comparison is "
            "available; fleet-wide diagnosis is not yet integrated."
        )
    if re.match(r"(?:why is (?:h|head\s*)\d+ failing|what could explain the failures on "
                r"(?:head\s*)?h?\d+|investigate why (?:h|head\s*)\d+ appears worse)(?=\s|$)", text, re.I):
        return _clarify(
            "Specify what counts as a failure, the comparison baseline, machine "
            "and time window. Torque statistics and anomaly flags can describe "
            "observations, but do not establish the cause of a head's failures."
        )

    templates = [
        # Combined analyses precede overlapping single-analysis phrases.
        (r"(?:is torque drifting and are there anomalies|check both torque trend and abnormal events|"
         r"do we have a drift problem or isolated outliers|show torque trend and anomalies)",
         "Show torque trend", ("torque_trend", "detect_torque_anomalies")),
        (r"(?:summarize torque and show its distribution|give me torque statistics together with the histogram|"
         r"what are the torque values like overall|show torque statistics and distribution)",
         "Show torque distribution", ("torque_stats", "torque_distribution")),
        (r"(?:what is the torque for successful closures only|show torque statistics only for good closures|"
         r"how does torque look when status is successful)",
         "Average torque for successful closures", ("torque_stats",)),
        (r"(?:give me (?:a|the) summary of closure torque|what is the average,\s*minimum and maximum torque)",
         "Average torque", ("torque_stats",)),
        (r"(?:how is torque distributed|give me (?:the )?torque histogram data)",
         "Show torque distribution", ("torque_distribution",)),
        (r"(?:is torque drifting over time|is the average torque moving upward or downward)",
         "Show torque trend", ("torque_trend",)),
        (r"(?:are there any abnormal torque events|find anomalous closures|which torque values look suspicious)",
         "Find torque anomalies", ("detect_torque_anomalies",)),
    ]
    for pattern, canonical, tools in templates:
        match = re.match(r"(?:" + pattern + r")(?=\s|$)", text, re.I)
        if match:
            return {"canonical": canonical + text[match.end():], "tools": tools}

    head = r"(?:head\s*)?h\s*[-#]?\s*(\d+)|head\s*[-#]?\s*(\d+)"
    # Two captures per head allow both 'head H01' and 'head 1'; use one
    # normalisation path and let the existing parser reject zero/equal heads.
    patterns = [
        r"compare (?:" + head + r") (?:and|versus|vs) (?:" + head + r")",
        r"does (?:" + head + r") behave like (?:" + head + r")",
        r"what is different between (?:" + head + r") and (?:" + head + r")",
    ]
    for pattern in patterns:
        match = re.match(r"(?:" + pattern + r")(?=\s|$)", text, re.I)
        if match:
            groups = match.groups()
            first, second = groups[0] or groups[1], groups[2] or groups[3]
            return {"canonical": f"Compare torque between H{first} and H{second}" + text[match.end():],
                    "tools": ("head_correlation",)}
    return None
