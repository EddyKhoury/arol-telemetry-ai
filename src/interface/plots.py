"""Plots for the report - WP4.

The brief asks for "repeatable, explainable outputs (reports plus plots and
tables)", so a figure is a deliverable, not decoration.

Two rules, both inherited from the rest of the system:

  1. A plot renders what a tool already returned. It never recomputes, never
     re-filters, never touches the event table. If a number appears in a
     figure it also appears in the findings, because both read the same
     envelope.

  2. Figures are deterministic. No random jitter, no seaborn defaults that
     shift between versions, no timestamp baked into the image. The same
     envelope produces the same PNG.

matplotlib runs headless (Agg) so this works over SSH and in CI.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")           # no display needed; must precede pyplot
import matplotlib.pyplot as plt  # noqa: E402

# One muted palette, used everywhere, so figures read as one set.
OK_COLOUR = "#2F7D4F"
WARN_COLOUR = "#8A6D1F"
BAD_COLOUR = "#A63A2E"
NEUTRAL = "#5A6672"
GRID = "#DDE3E9"

FIGSIZE = (9, 4.5)
DPI = 120


def _style(ax, title: str, xlabel: str = "", ylabel: str = ""):
    ax.set_title(title, fontsize=11, loc="left", pad=10)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=9)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=9)
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(labelsize=8)


def _save(fig, out_dir: Path, stem: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}.png"
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return path


# --- one plotter per tool, keyed like the report's finding templates -------

def _plot_success_rate_per_head(result, out_dir) -> Path | None:
    rows = [r for r in result.get("per_head", []) if r["success_rate"] is not None]
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: r["head_index"])
    labels = [r["head_id"] for r in rows]
    values = [r["success_rate"] * 100 for r in rows]
    worst = min(values)

    fig, ax = plt.subplots(figsize=FIGSIZE)
    colours = [BAD_COLOUR if v == worst else OK_COLOUR for v in values]
    ax.bar(labels, values, color=colours, width=0.7)
    # Zoom to the interesting range: on a healthy machine every bar is ~100%
    # and a full 0-100 axis would show 36 identical bars saying nothing.
    ax.set_ylim(max(0, worst - (100 - worst) * 0.4), 100.05)
    _style(ax, "Success rate per head (cap-present closures)", "", "%")
    ax.tick_params(axis="x", rotation=90)
    return _save(fig, out_dir, "success_rate_per_head")


def _plot_throughput(result, out_dir) -> Path | None:
    buckets = result.get("by_bucket") or []
    if len(buckets) < 2:
        return None
    x = [b["bucket_start"][11:16] for b in buckets]
    y = [b["closures_per_hour"] for b in buckets]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.fill_between(range(len(y)), y, color=OK_COLOUR, alpha=0.15)
    ax.plot(range(len(y)), y, color=OK_COLOUR, linewidth=1.8)
    lowest = min(range(len(y)), key=lambda i: y[i])
    ax.plot([lowest], [y[lowest]], "o", color=BAD_COLOUR, markersize=6)
    ax.annotate(f"{y[lowest]:,.0f}/h", (lowest, y[lowest]),
                textcoords="offset points", xytext=(0, -14),
                fontsize=8, color=BAD_COLOUR, ha="center")
    ax.set_xticks(range(0, len(x), max(1, len(x) // 12)))
    ax.set_xticklabels([x[i] for i in range(0, len(x), max(1, len(x) // 12))])
    _style(ax, "Capping speed over time", "", "closures / hour")
    return _save(fig, out_dir, "throughput")


def _plot_success_rate(result, out_dir) -> Path | None:
    """The denominator, as a picture. Worth 44 points on real data."""
    o = result.get("overall") or {}
    if not o.get("n_cycles"):
        return None
    parts = [("Closure OK", o["n_success"], OK_COLOUR),
             ("No Load", o["n_no_load"], WARN_COLOUR),
             ("Bad Closure", o["n_reject"], BAD_COLOUR)]
    parts = [p for p in parts if p[1]]

    fig, ax = plt.subplots(figsize=(9, 2.2))
    left = 0
    total = sum(p[1] for p in parts)
    for label, value, colour in parts:
        ax.barh([0], [value], left=left, color=colour, height=0.6,
                label=f"{label}  {value:,} ({value / total:.1%})")
        left += value
    ax.set_yticks([])
    ax.set_xlim(0, total)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15),
              ncol=len(parts), frameon=False, fontsize=8)
    _style(ax, "Every cycle, by outcome - No Load is not a failure", "cycles")
    ax.grid(False)
    return _save(fig, out_dir, "outcome_mix")


def _plot_idle_periods(result, out_dir) -> Path | None:
    periods = result.get("idle_periods") or []
    if not periods:
        return None
    by_head: dict[str, float] = {}
    for p in periods:
        by_head[p["head_id"]] = by_head.get(p["head_id"], 0.0) + p["duration_seconds"]
    heads = sorted(by_head)
    hours = [by_head[h] / 3600 for h in heads]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.bar(heads, hours, color=WARN_COLOUR, width=0.7)
    _style(ax, f"Idle time per head (stretches over "
               f"{result['threshold_seconds']:.0f}s)", "", "hours")
    ax.tick_params(axis="x", rotation=90)
    return _save(fig, out_dir, "idle_per_head")


def _plot_head_detail(result, out_dir) -> Path | None:
    rate = result.get("success_rate")
    median = result.get("fleet_median_success_rate")
    if rate is None or median is None:
        return None
    fig, ax = plt.subplots(figsize=(9, 2.4))
    colour = BAD_COLOUR if result["is_worst_head"] else OK_COLOUR
    ax.barh([result["head_id"]], [rate * 100], color=colour, height=0.5)
    ax.axvline(median * 100, color=NEUTRAL, linestyle="--", linewidth=1.4)
    ax.annotate(f"fleet median {median * 100:.3f}%", (median * 100, 0),
                textcoords="offset points", xytext=(6, 18),
                fontsize=8, color=NEUTRAL)
    lo = min(rate, median) * 100
    ax.set_xlim(max(0, lo - (100 - lo) * 0.6), 100.02)
    _style(ax, f"{result['head_id']} against the fleet "
               f"(rank {result['rank_worst_first']} of {result['n_heads']}, "
               f"worst first)", "%")
    return _save(fig, out_dir, f"head_{result['head_id']}")


PLOTTERS = {
    "success_rate": _plot_success_rate,
    "success_rate_per_head": _plot_success_rate_per_head,
    "throughput": _plot_throughput,
    "idle_periods": _plot_idle_periods,
    "head_detail": _plot_head_detail,
}


def render(results, out_dir) -> list[tuple[str, Path]]:
    """Draw whatever the successful tools support. Never raises.

    A plotting failure must not cost the user their report, so a broken
    figure is skipped and the text still ships.
    """
    out_dir = Path(out_dir)
    made: list[tuple[str, Path]] = []
    for name, result in results:
        if not result.get("ok"):
            continue
        plotter = PLOTTERS.get(name)
        if plotter is None:
            continue
        try:
            path = plotter(result["result"], out_dir)
        except Exception:
            continue
        if path is not None:
            made.append((name, path))
    return made
