DIAGNOSTIC_QUERY_CASES = [
    {
        "id": "torque_summary",
        "questions": [
            "What are the torque statistics?",
            "Give me a summary of closure torque.",
            "What is the average, minimum and maximum torque?",
        ],
        "expected_tools": [
            "torque_stats",
        ],
    },
    {
        "id": "successful_torque_summary",
        "questions": [
            "What is the torque for successful closures only?",
            "Show torque statistics only for good closures.",
            "How does torque look when status is successful?",
        ],
        "expected_tools": [
            "torque_stats",
        ],
        "expected_arguments": {
            "status_filter": "successful",
        },
    },
    {
        "id": "torque_distribution",
        "questions": [
            "Show me the torque distribution.",
            "How is torque distributed?",
            "Give me the torque histogram data.",
        ],
        "expected_tools": [
            "torque_distribution",
        ],
    },
    {
        "id": "torque_trend",
        "questions": [
            "Is torque drifting over time?",
            "Show me the torque trend.",
            "Is the average torque moving upward or downward?",
        ],
        "expected_tools": [
            "torque_trend",
        ],
    },
    {
        "id": "torque_anomalies",
        "questions": [
            "Are there any abnormal torque events?",
            "Find anomalous closures.",
            "Which torque values look suspicious?",
        ],
        "expected_tools": [
            "detect_torque_anomalies",
        ],
    },
    {
        "id": "compare_heads",
        "questions": [
            "Compare H01 and H05.",
            "Does H01 behave like H05?",
            "What is different between head H01 and H05?",
        ],
        "expected_tools": [
            "head_correlation",
        ],
        "expected_arguments": {
            "head_a": "H01",
            "head_b": "H05",
        },
    },
    {
        "id": "head_behaves_differently",
        "questions": [
            "Which head behaves differently?",
            "Are any heads behaving unusually compared with another head?",
            "Can you identify a head whose behavior differs from its peers?",
        ],
        "expected_tools": [
            "head_correlation",
        ],
        "notes": (
            "The agent may need to compare multiple head pairs. "
            "Every numerical comparison must come from tool output."
        ),
    },
    {
        "id": "why_head_failing",
        "questions": [
            "Why is H04 failing more?",
            "What could explain the failures on head H04?",
            "Investigate why H04 appears worse.",
        ],
        "expected_tools": [
            "torque_stats",
            "detect_torque_anomalies",
        ],
        "notes": (
            "Depending on Person B's orchestration, additional comparison "
            "calls may be useful. Numerical claims must remain tool-grounded."
        ),
    },
    {
        "id": "trend_and_anomalies",
        "questions": [
            "Is torque drifting and are there anomalies?",
            "Check both torque trend and abnormal events.",
            "Do we have a drift problem or isolated outliers?",
        ],
        "expected_tools": [
            "torque_trend",
            "detect_torque_anomalies",
        ],
    },
    {
        "id": "distribution_and_summary",
        "questions": [
            "Summarize torque and show its distribution.",
            "Give me torque statistics together with the histogram.",
            "What are the torque values like overall?",
        ],
        "expected_tools": [
            "torque_stats",
            "torque_distribution",
        ],
    },
]


def list_diagnostic_query_cases():
    """
    Return defensive copies of the diagnostic query suite.
    """

    from copy import deepcopy

    return deepcopy(
        DIAGNOSTIC_QUERY_CASES
    )