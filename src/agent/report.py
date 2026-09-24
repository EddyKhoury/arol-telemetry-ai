"""The report assembler.

Enforces the structure the brief requires, in this order and always:

    goal -> data used -> analyses executed -> findings
         -> confidence and limits -> next checks

The confidence/limits section is computed from meta.n and the tool notes, not
written as prose. Almost every team ships that heading with something vague
under it; filling it with real sample sizes and real caveats is cheap here
because every envelope already carries `n`.

Findings are rendered by deterministic templates, one per tool. No model is
involved in producing a number or the sentence around it, so the same query
produces the same report text every time.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def _pct(value, digits=2):
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


# --- per-tool finding templates -------------------------------------------

def _finding_success_rate(result, meta) -> list[str]:
    o = result["overall"]
    lines = [
        f"- Across {o['n_cycles']:,} cycles, {o['n_cap_present']:,} had a cap "
        f"present. Success rate **{_pct(o['success_rate'])}** on cap-present "
        f"closures ({o['n_success']:,} of {o['n_cap_present']:,}).",
        f"- No Load accounted for {o['n_no_load']:,} cycles "
        f"({_pct(o['no_load_rate'])} of all cycles) - the head cycled with no "
        f"cap present. Counting those as failures would report "
        f"{_pct(o['success_rate_all_cycles'])} instead.",
    ]
    if o["n_reject"]:
        lines.append(f"- {o['n_reject']:,} Bad Closures "
                     f"({_pct(o['reject_rate'])} of cap-present closures).")
    buckets = result.get("by_bucket") or []
    if buckets:
        worst = min(buckets, key=lambda b: b["success_rate"]
                    if b["success_rate"] is not None else 2)
        lines.append(f"- Worst {worst['bucket']} bucket: {worst['bucket_start']} "
                     f"at {_pct(worst['success_rate'])} over "
                     f"{worst['n_cap_present']:,} cap-present closures.")
    return lines


def _finding_success_rate_per_head(result, meta) -> list[str]:
    rows = result["per_head"]
    lines = [f"- Ranked {result['n_heads']} heads by success rate, worst first."]
    for row in rows[:3]:
        lines.append(f"  - **{row['head_id']}**: {_pct(row['success_rate'])} "
                     f"({row['n_success']:,}/{row['n_cap_present']:,} cap-present), "
                     f"{row['n_reject']:,} rejects, "
                     f"No Load {_pct(row['no_load_rate'])}.")
    if len(rows) > 1 and rows[0]["success_rate"] is not None \
            and rows[1]["success_rate"] is not None:
        gap = (rows[1]["success_rate"] - rows[0]["success_rate"]) * 100
        lines.append(f"- The worst head trails the next worst by "
                     f"{gap:.2f} percentage points.")
    return lines


def _finding_anomaly_heads(result, meta) -> list[str]:
    if not result["flagged_heads"]:
        return [f"- No head exceeded {result['sigma']} sigma against the fleet. "
                f"Median reject rate {_pct(result['fleet_median_reject_rate'], 3)}."]
    lines = [f"- {result['n_flagged']} head(s) flagged against a fleet median "
             f"reject rate of {_pct(result['fleet_median_reject_rate'], 3)}:"]
    for head in result["flagged_heads"]:
        lines.append(f"  - **{head['head_id']}**: reject rate "
                     f"{_pct(head['reject_rate'], 3)} over "
                     f"{head['n_cap_present']:,} cap-present closures "
                     f"({head['n_reject']:,} rejects vs "
                     f"{head['expected_rejects']} expected, "
                     f"{head['rate_ratio']}x the fleet median, "
                     f"p = {head['p_value']:.2e}).")
    lines.append(f"- Method: {result['method']}.")
    return lines


def _finding_idle_periods(result, meta) -> list[str]:
    if not result["idle_periods"]:
        return [f"- No sustained No Load stretch of at least "
                f"{result['threshold_seconds']:.0f}s was found."]
    lines = [
        f"- {result['n_periods']} idle stretch(es) of at least "
        f"{result['threshold_seconds']:.0f}s across "
        f"{len(result['heads_affected'])} head(s); "
        f"{result['total_idle_seconds'] / 3600:.2f} head-hours in total.",
    ]
    longest = result["idle_periods"][0]
    lines.append(f"- Longest: {longest['head_id']} from {longest['start']} to "
                 f"{longest['end']} ({longest['duration_seconds']:.0f}s, "
                 f"{longest['n_cycles']:,} empty cycles).")
    if len(result["heads_affected"]) > 1:
        lines.append("- The stretch spans multiple heads at the same time, "
                     "which points at supply upstream of the machine rather "
                     "than at any one head.")
    return lines


def _finding_throughput(result, meta) -> list[str]:
    lines = [
        f"- {result['total_closures']:,} closures over "
        f"{result['span_hours']:.2f}h, mean "
        f"{result['mean_closures_per_hour']:,.0f} closures/hour.",
    ]
    buckets = result.get("by_bucket") or []
    if buckets:
        best = max(buckets, key=lambda b: b["closures_per_hour"])
        worst = min(buckets, key=lambda b: b["closures_per_hour"])
        lines.append(f"- Peak {best['closures_per_hour']:,.0f}/h at "
                     f"{best['bucket_start']}; trough "
                     f"{worst['closures_per_hour']:,.0f}/h at "
                     f"{worst['bucket_start']}.")
    if result.get("n_inferred_closures"):
        lines.append(f"- {result['n_inferred_closures']} closure(s) were "
                     f"inferred from counter jumps greater than one "
                     f"(a dropped poll), not observed directly.")
    return lines



def _finding_head_detail(result, meta) -> list[str]:
    where = ("the WORST of" if result["is_worst_head"]
             else f"ranked {result['rank_worst_first']} worst of")
    lines = [
        f"- **{result['head_id']}**: success rate "
        f"**{_pct(result['success_rate'])}** over "
        f"{result['n_cap_present']:,} cap-present closures "
        f"({result['n_reject']:,} rejects, No Load {_pct(result['no_load_rate'])}).",
        f"- That is {where} {result['n_heads']} heads.",
    ]
    if result.get("difference_from_fleet_median") is not None:
        delta = result["difference_from_fleet_median"] * 100
        direction = "below" if delta < 0 else "above"
        lines.append(f"- Fleet median is {_pct(result['fleet_median_success_rate'])}, "
                     f"so this head sits {abs(delta):.3f} percentage points "
                     f"{direction} it.")
    return lines



def _finding_torque_stats(result, meta):
    n = result["sample_size"]
    if n == 0:
        return [
            "- No finite torque observations matched the requested filters.",
            "- Torque statistics cannot be estimated from this empty sample.",
        ]

    lines = [
        f"- Finite torque observations: **{n:,}**.",
        f"- Mean: **{result['mean']:.6g} Nm**; "
        f"minimum: **{result['min']:.6g} Nm**; "
        f"maximum: **{result['max']:.6g} Nm**.",
    ]
    if result["std"] is None:
        lines.append(
            "- Sample standard deviation is undefined for fewer than "
            "two observations."
        )
    else:
        lines.append(
            f"- Sample standard deviation (ddof=1): "
            f"**{result['std']:.6g} Nm**."
        )
    lines.append(
        "- These summary statistics do not establish whether torque "
        "meets engineering limits."
    )
    return lines


def _analytics_number(value):
    return "n/a" if value is None else f"{value:.6g}"


def _finding_torque_distribution(result, meta):
    if result["sample_size"] == 0:
        return ["- No finite torque observations matched; no histogram is available."]
    counts = result["counts"]
    shown = counts[:20]
    label = "Bin counts" if len(counts) <= 20 else "First 20 bin counts"
    return [
        f"- Histogram: {result['sample_size']:,} finite observations in {len(counts)} bins.",
        f"- Bin-edge range: {_analytics_number(result['bin_edges'][0])} to "
        f"{_analytics_number(result['bin_edges'][-1])} Nm.",
        f"- {label}: {shown}.",
    ]


def _finding_torque_trend(result, meta):
    if result["sample_size"] == 0:
        return ["- No finite torque observations matched; no trend can be estimated."]
    return [
        f"- Moving average uses a {result['window_seconds']} s trailing window over "
        f"{result['sample_size']:,} finite observations.",
        f"- Latest-window slope: {_analytics_number(result['drift_slope_per_second'])} Nm/s; "
        f"numerical direction: {result['drift_direction']}.",
        "- This numerical signal alone does not establish an engineering problem or its cause.",
    ]


def _finding_torque_anomalies(result, meta):
    if result["sample_size"] == 0:
        return ["- No finite torque observations matched; anomaly absence cannot be assessed."]
    lines = [
        f"- {result['anomaly_count']:,} of {result['sample_size']:,} observations flagged "
        f"({_pct(result['anomaly_rate'])}).",
        f"- Configured limits: {result['expected_min']} to {result['expected_max']} Nm; "
        f"statistical threshold: {result['sigma']} sample standard deviations.",
    ]
    for item in result["anomalies"][:3]:
        lines.append(f"- Example: {item['head_id']} at {item['ts']}, "
                     f"{_analytics_number(item['torque'])} Nm; reason: {item['reason']}.")
    lines.append("- Flags describe the configured checks; they do not identify a physical cause.")
    return lines


def _finding_head_correlation(result, meta):
    lines = [
        f"- Matched finite torque pairs: {result['matched_torque_samples']:,}; "
        f"Pearson correlation: {_analytics_number(result['torque_correlation'])} "
        f"({result['torque_correlation_interpretation']}).",
        "- Person A denominator: non-null error_class other than No Load. "
        "This is distinct from the cap-present KPI denominator.",
    ]
    for side in ("head_a", "head_b"):
        head = result[side]
        lines.append(f"- {head['head_id']}: {head['event_count']:,} events; "
                     f"mean torque {_analytics_number(head['mean_torque'])} Nm; "
                     f"success {_pct(head['success_rate'])} "
                     f"({head['success_count']:,}/{head['success_evaluable_count']:,}).")
    lines.append("- Correlation does not establish causation.")
    return lines


FINDING_TEMPLATES = {
    "torque_distribution": _finding_torque_distribution,
    "torque_trend": _finding_torque_trend,
    "detect_torque_anomalies": _finding_torque_anomalies,
    "head_correlation": _finding_head_correlation,
    "torque_stats": _finding_torque_stats,
    "success_rate": _finding_success_rate,
    "success_rate_per_head": _finding_success_rate_per_head,
    "anomaly_heads": _finding_anomaly_heads,
    "idle_periods": _finding_idle_periods,
    "throughput": _finding_throughput,
    "head_detail": _finding_head_detail,
}


def assemble(query, plan, results, pool_meta, trace, *, min_n=30) -> str:
    """Render the six mandated sections as Markdown."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ok_results = [(name, r) for name, r in results if r.get("ok")]
    failed = [(name, r) for name, r in results if not r.get("ok")]

    out: list[str] = [
        f"# Telemetry report",
        "",
        f"*Query:* {query}",
        f"*Generated:* {now}  |  *Planner:* {trace.planner}  |  "
        f"*Schema:* {pool_meta.get('schema_version', '?')}",
        "",
        "## 1. Goal",
        "",
        plan.goal,
        "",
        "## 2. Data used",
        "",
        f"- Pool `{pool_meta.get('pool')}` from the **{pool_meta.get('source', '?')}** "
        f"source, {pool_meta.get('n_events', 0):,} closure events "
        f"across {len(pool_meta.get('heads', []))} heads.",
        f"- Window {pool_meta.get('ts_min')} to {pool_meta.get('ts_max')} "
        f"(plant-local, "
        f"{pool_meta.get('timezone') or 'timezone unconfirmed'}).",
        f"- Machines: {', '.join(pool_meta.get('machines', [])) or 'n/a'}.",
    ]
    if pool_meta.get("pool_total_events") is not None:
        out.append(
            f"- Events loaded for the requested scope: {pool_meta['loaded_events']:,} "
            f"of {pool_meta['pool_total_events']:,} stored observed events in this pool."
        )
    if pool_meta.get("rows_read") is not None:
        out.append(f"- Cleaning: {pool_meta.get('rows_read', 0):,} rows read, "
                   f"{pool_meta.get('rows_after_cleaning', 0):,} retained, "
                   f"{pool_meta.get('duplicates_removed', 0):,} duplicates removed.")
    for warning in pool_meta.get("warnings", []):
        out.append(f"- **Warning:** {warning}")
    if plan.filters:
        out.append(f"- Filters requested: "
                   f"{', '.join(f'`{k}={v}`' for k, v in plan.filters.items())}.")

    out += ["", "## 3. Analyses executed", ""]
    for name, result in results:
        meta = result.get("meta", {})
        status = "ok" if result.get("ok") else f"FAILED - {result.get('error')}"
        out.append(f"- `{name}` (agent: {meta.get('agent', '?')}) - "
                   f"n={meta.get('n', 0):,}, {meta.get('elapsed_ms', 0)} ms - {status}")
        if meta.get("filters_applied"):
            out.append(f"  - filters: {', '.join(meta['filters_applied'])}")

    out += ["", "## 4. Findings", ""]
    if not ok_results:
        out.append("No analysis produced a result. See section 5.")
    for name, result in ok_results:
        template = FINDING_TEMPLATES.get(name)
        out.append(f"**{name}**")
        out += (template(result["result"], result["meta"]) if template
                else [f"- {result['result']}"])
        out.append("")

    out += ["## 5. Confidence and limits", ""]
    limits: list[str] = []
    if len(ok_results) > 1:
        limits.append("- These analyses may reuse the same observations. Their sample sizes "
                      "must not be added to claim a count of distinct events.")
    for name, result in ok_results:
        meta = result["meta"]
        if meta.get("notes"):
            limits.append(f"- `{name}`: {meta['notes']}")
        if meta.get("n", 0) < min_n:
            limits.append(f"- `{name}`: n={meta['n']} is below min_n={min_n}.")
    for name, result in failed:
        limits.append(f"- `{name}` produced no result: {result.get('error')}")
    for warning in pool_meta.get("warnings", []):
        limits.append(f"- {warning}")
    if not limits:
        limits.append(f"- All analyses met the minimum sample size "
                      f"(min_n={min_n}); sample sizes are reported per tool.")
    rate_tools = {
        "success_rate", "success_rate_per_head", "head_detail", "anomaly_heads"
    }
    if any(name in rate_tools for name, _ in ok_results):
        limits.append(
            "- Rates are computed over cap-present closures unless a "
            "figure is explicitly labelled all-cycles."
        )
    out += limits

    out += ["", "## 6. Next checks", ""] + _next_checks(ok_results, failed)
    out += ["", "---", "", "## Trace", "",
            f"{trace.to_dict()['n_tool_calls']} tool call(s), "
            f"{trace.elapsed_ms:.0f} ms total.", "", trace.to_markdown(), ""]
    return "\n".join(out)


def _next_checks(ok_results, failed) -> list[str]:
    """Concrete follow-ups implied by what was actually found."""
    checks: list[str] = []
    for name, result in ok_results:
        r = result["result"]
        if name in {"torque_distribution", "torque_trend", "detect_torque_anomalies", "head_correlation"}:
            if result["meta"].get("n", 0) == 0:
                checks.append("- Verify the requested scope and observation coverage before interpreting an empty result.")
            else:
                checks.append("- Review observation coverage and process context before drawing operational conclusions.")
        if name == "torque_stats":
            if r["sample_size"] == 0:
                checks.append(
                    "- Verify data availability and the requested status "
                    "selection before drawing conclusions."
                )
            else:
                checks.append(
                    "- Compare torque statistics with confirmed engineering "
                    "limits before assessing acceptability."
                )
                checks.append(
                    "- Review counter discontinuities separately; this "
                    "report describes observed exact +1 events."
                )
        if name == "anomaly_heads" and r.get("flagged_heads"):
            head = r["flagged_heads"][0]["head_id"]
            checks.append(f"- Run a torque distribution and drift check on "
                          f"`{head}` to separate a mechanical fault from a "
                          f"settings error (Person A's tools).")
            checks.append(f"- Compare `{head}` against its neighbours to see "
                          f"whether the fault is positional.")
        if name == "idle_periods" and r.get("idle_periods"):
            checks.append("- Cross-check the idle window against upstream "
                          "filler/conveyor logs; simultaneous idling on every "
                          "head is a supply problem, not a capping problem.")
        if name == "throughput" and r.get("n_inferred_closures"):
            checks.append("- Investigate the dropped polls: counter jumps "
                          "greater than one mean the 1 Hz sampling missed a "
                          "cycle, which slightly understates every rate.")
    for name, _ in failed:
        checks.append(
            f"- Check the reported error and requested filters for `{name}` "
            "before retrying."
        )
    if not checks:
        checks.append("- Nothing anomalous surfaced; re-run against a longer "
                      "window to confirm the machine is stable over time.")
    return checks


def save(markdown: str, report_dir, stem="report") -> Path:
    out = Path(report_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text(markdown, encoding="utf-8")
    return path
