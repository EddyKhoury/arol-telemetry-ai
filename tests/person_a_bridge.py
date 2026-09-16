"""Run Person A's pipeline in a subprocess and hand back a Parquet file.

Both repos name their top-level package `src`, so his modules cannot be
imported into this process: `src` is already bound to ours, and his
event_table_polars imports `src.ingestion.closure_detection_polars`, which
would resolve into OUR package and fail. No sys.path ordering fixes that.

A subprocess with cwd set to his repo gives each `src` its own interpreter,
and the handoff is a Parquet file - which is what the real integration looks
like anyway, since his pipeline already ships write_event_table_parquet.

Nothing here writes to his repo. It reads his source and the shared telemetry
archive, and writes only into a temp directory owned by the caller.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PERSON_A_REPO = Path(__file__).resolve().parents[2] / "person-a"

_SCRIPT = '''
import io, sys, zipfile
import polars as pl
from src.ingestion.event_table_polars import build_event_table

archive, month, out_path, machine_id = sys.argv[1:5]

outer = zipfile.ZipFile(archive)
inner = zipfile.ZipFile(io.BytesIO(outer.read(month)))
names = sorted(i.filename for i in inner.infolist() if i.filename.endswith(".csv"))
raw = pl.read_csv(io.BytesIO(inner.read(names[0])), try_parse_dates=True)

events = build_event_table(raw, machine_id=machine_id)
events.write_parquet(out_path)
print(f"{events.height} events, columns={list(events.columns)}")
'''


def available() -> bool:
    return (PERSON_A_REPO / "src" / "ingestion" / "event_table_polars.py").exists()


def build_event_table(archive: Path, month: str, out_path: Path,
                      machine_id: str = "MCC777-01") -> str:
    """Run his build_event_table on the first day-file of `month`.

    Returns his stdout line. Raises CalledProcessError if his pipeline fails,
    which is the correct outcome: a broken upstream must not look like a skip.
    """
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, str(Path(archive).resolve()), month,
         str(Path(out_path).resolve()), machine_id],
        cwd=str(PERSON_A_REPO), capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Person A's pipeline failed (exit {result.returncode}):\n"
            f"{result.stderr[-2000:]}")
    return result.stdout.strip()
