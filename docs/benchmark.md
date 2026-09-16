# Scaling benchmark

Q3 objective 5. Two implementations of the same question over the same real telemetry. The results are asserted identical at every size, so this is a comparison and not a straw man.

## Method

Each timing is the **median of 5 runs**, taken with no profiler attached.

An earlier version of this harness timed both implementations WHILE tracemalloc was running. tracemalloc traces every allocation, so it costs the monolith - a Python loop allocating per closure - about 31x, and the agent path - Polars, allocating in Rust where tracemalloc cannot reach - about 1.2x. It reported a 25x speedup that was mostly the profiler. The real figure is in the table below.

A single run was also not enough: with honest timing, the four-file agent measurement varied between 1.56s and 3.61s across three runs, which is wider than the effect being measured. Hence the median, and the published spread.

| day-files | events | monolith s | agent s | speedup |
|---|---|---|---|---|
| 1 | 765,711 | 0.559 | 0.417 | 1.3x |
| 2 | 1,764,631 | 2.043 | 0.918 | 2.2x |
| 4 | 2,813,193 | 3.131 | 1.621 | 1.9x |

Spread across runs (min-max), so the noise is visible:

| day-files | monolith | agent |
|---|---|---|
| 1 | 0.522-0.849s | 0.353-0.421s |
| 2 | 1.64-2.529s | 0.864-0.974s |
| 4 | 2.998-3.422s | 1.575-1.809s |

## What the numbers say

Single-question speedup across sizes: **1.3x -> 2.2x -> 1.9x**.
That is **not a trend** - it is not monotonic, and the spread above overlaps between sizes. The honest reading is a modest and noisy 1.3x to 2.2x, with no reliable direction over this range. More sizes and more repeats would be needed to claim one.

Either way the single-question figure is the WEAK claim. Building the whole event table costs roughly what answering one question from it saves, so a pipeline is not a dramatically faster way to compute one number. It is a way to make the *second* question nearly free - see below.

## Five questions instead of one

A monolith computes one fixed answer, so a second question costs a second full pass. The pipeline reshapes once and answers from the event table.

| day-files | monolith x5 | agent, 1 reshape + 5 tools | speedup |
|---|---|---|---|
| 1 | 2.795s | 0.619s | 4.5x |
| 2 | 10.214s | 1.468s | 7.0x |
| 4 | 15.653s | 2.552s | 6.1x |

| day-files | monolith, 5q vs 1q | agent, 5q vs 1q |
|---|---|---|
| 1 | 5.00x | 1.48x |
| 2 | 5.00x | 1.60x |
| 4 | 5.00x | 1.57x |

The monolith costs **exactly 5.00x** for five questions at every size - perfectly linear in the number of questions, because there is nothing to reuse between them. The agent costs 1.48x to 1.60x, because the reshape happens once and each further question is milliseconds of columnar aggregation.

**That is the objective-5 result.** It is an architectural property rather than a tuning one: an interactive agent is asked many questions of one dataset, and that is the regime where a monolithic script degrades fastest. The single-question speedup is the weaker claim and the one most sensitive to measurement error - which is exactly how the first version of this harness went wrong.

## Memory is not reported here

Peak memory is measured only with `--memory`, and it is off by default for two reasons. It costs a whole extra run under tracemalloc (~31x for the monolith, minutes at four day-files). More importantly, tracemalloc counts PYTHON allocations only, and Polars allocates its frames in Rust where tracemalloc cannot see them - so the agent's figure would be a floor rather than a total, and the two columns would not be measuring the same thing. A real comparison needs peak RSS per process, which is not built here. Publishing a number we have already said is untrustworthy would be worse than publishing none.
