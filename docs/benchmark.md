# Scaling benchmark

Q3 objective 5. Two implementations of the same question over the same real telemetry; the numbers are asserted identical at every size, so this is a comparison rather than a straw man.

| day-files | events | monolith s | agent s | speedup | monolith MB | agent MB |
|---|---|---|---|---|---|---|
| 1 | 765,711 | 14.586 | 1.017 | 14.3x | 54.5 | 54.5 |
| 2 | 1,764,631 | 29.118 | 1.456 | 20.0x | 62.1 | 56.8 |
| 4 | 2,813,193 | 80.464 | 3.898 | 20.6x | 62.1 | 56.8 |

## Five questions instead of one

A monolith computes one fixed answer, so a second question costs a second full pass. The pipeline reshapes once and answers from the event table.

| day-files | monolith x5 | agent, 1 reshape + 5 tools |
|---|---|---|
| 1 | 72.93s | 1.322s |
| 2 | 145.592s | 2.078s |
| 4 | 402.319s | 5.681s |
