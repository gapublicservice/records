"""Merge two copies of data/state.json when two runs saved at once.

The nightly run owns the recheck list (empty, gaps, last_nightly). A backfill
run owns its own cursor and the backfill empty list. highest_found is the larger
of the two. Usage:

    python -m harvester.merge_state THEIRS OURS --owner backfill --cursor 198000-205999
    python -m harvester.merge_state THEIRS OURS --owner nightly
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
NIGHTLY_KEYS = ("empty", "gaps", "last_nightly")


def filing_exists(doc_id: int) -> bool:
    return (DATA / "filings" / str(doc_id // 1000) / f"{doc_id}.json").exists()


def merge(theirs: dict, ours: dict, owner: str, cursor: str | None = None,
          exists=filing_exists) -> dict:
    out = dict(theirs)
    if owner == "nightly":
        for key in NIGHTLY_KEYS:
            if key in ours:
                out[key] = ours[key]
    else:
        cursors = dict(theirs.get("backfill_cursor", {}))
        if cursor:
            if cursor in ours.get("backfill_cursor", {}):
                cursors[cursor] = ours["backfill_cursor"][cursor]
            else:
                cursors.pop(cursor, None)
        out["backfill_cursor"] = cursors
    empty = set(theirs.get("backfill_empty", [])) | set(ours.get("backfill_empty", []))
    out["backfill_empty"] = sorted(n for n in empty if not exists(n))
    out["highest_found"] = max(theirs.get("highest_found") or 0, ours.get("highest_found") or 0)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("theirs")
    p.add_argument("ours")
    p.add_argument("--owner", choices=["backfill", "nightly"], required=True)
    p.add_argument("--cursor")
    a = p.parse_args(argv)
    theirs = json.loads(Path(a.theirs).read_text())
    ours = json.loads(Path(a.ours).read_text())
    json.dump(merge(theirs, ours, a.owner, a.cursor), sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
