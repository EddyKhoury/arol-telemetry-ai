"""Regenerate the Person A event-table cache the `person_a` data source reads.

Runs Person A's OWN pipeline over the shared telemetry archive and writes the
Parquet his `write_event_table_parquet` would write, into cache/. Nothing is
written to his repository.

    python scripts/refresh_person_a_cache.py
    python scripts/refresh_person_a_cache.py --pool feb --files 4

Then point config.local.yaml at it:

    data:
      source: person_a

Why this exists: without it, `data.source: person_a` depends on a Parquet file
somebody happened to produce once. cache/ is gitignored (the files are large
and derived), so a fresh clone would find the source configured and the data
missing. This makes the real-data path reproducible in one command.

Requires Person A's repo checked out beside this one, as ../person-a.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import polars as pl  # noqa: E402

from src.common import schema  # noqa: E402
from src.ingestion import adapter  # noqa: E402
from src.testing import benchmark  # noqa: E402
from tests import person_a_bridge  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", default="feb", help="pool name to write")
    parser.add_argument("--archive", default=benchmark.ARCHIVE)
    parser.add_argument("--month", default=benchmark.MONTH)
    parser.add_argument("--out", default=None,
                        help="default: cache/person_a_<pool>.parquet")
    args = parser.parse_args(argv)

    if not person_a_bridge.available():
        print(f"error: Person A's repo not found at "
              f"{person_a_bridge.PERSON_A_REPO}", file=sys.stderr)
        return 2

    archive = Path(args.archive)
    if not archive.exists():
        print(f"error: telemetry archive {archive} not found", file=sys.stderr)
        return 2

    out = Path(args.out or f"cache/person_a_{args.pool}.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"running Person A's pipeline over {archive} ...")
    print(" ", person_a_bridge.build_event_table(archive, args.month, out))

    # Prove it satisfies the contract before anyone relies on it.
    events, notes = adapter.adapt(pl.read_parquet(out), pool_id=args.pool)
    problems = schema.validate_events(events, strict=False)
    if problems:
        print("error: adapted frame does not conform:", file=sys.stderr)
        for problem in problems:
            print("  -", problem, file=sys.stderr)
        return 1

    print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB, "
          f"{events.height:,} events, conforms)")
    for note in notes:
        print("  note:", note)
    print("\nTo use it, put this in config.local.yaml:\n"
          "\n    data:\n      source: person_a\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
