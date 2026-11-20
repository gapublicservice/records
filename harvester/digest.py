"""Write the daily digest: what came in, what needs a person, and on Fridays
five random records to check against the PSC's own pages.

    python -m harvester.digest            # today's digest
    python -m harvester.digest --date 2026-11-20 --friday

The digest goes to data/digests/YYYY-MM-DD.md, so it is part of the public
record and anyone can see what was checked and what was flagged.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
from pathlib import Path

from .run import DATA, ROOT, today

DIGESTS = DATA / "digests"
SPOT_CHECK_COUNT = 5
EARLIEST_PLAUSIBLE = "1990-01-01"


def all_filings():
    for p in sorted((DATA / "filings").glob("*/*.json")):
        try:
            yield json.loads(p.read_text())
        except json.JSONDecodeError:
            yield {"document_id": int(p.stem), "_broken": True}


def flags_for(rec: dict, day: str) -> list[str]:
    """Plain-language reasons a person should look at this record."""
    out = []
    if rec.get("_broken"):
        return ["stored file can't be read"]
    fd = rec.get("filed_date") or ""
    if not fd:
        out.append("no filed date")
    elif fd < EARLIEST_PLAUSIBLE:
        out.append(f"filed date {fd} looks like a placeholder")
    elif fd > day:
        out.append(f"filed date {fd} is in the future")
    if not rec.get("company"):
        out.append("no filer named")
    if not rec.get("dockets"):
        out.append("no docket number")
    for att in rec.get("attachments", []):
        if att.get("trade_secret_marked"):
            out.append(f"attachment {att['attachment_id']} marked trade secret, not stored")
        if att.get("review"):
            out.append(f"attachment {att['attachment_id']}: {att['review']}")
        if str(att.get("text", "")).startswith("download failed"):
            out.append(f"attachment {att['attachment_id']}: {att['text']}")
    return out


def spot_check(recs: list[dict], day: str) -> list[dict]:
    # Seeded by the date, so anyone can rerun the pick and get the same five.
    pool = [r for r in recs if not r.get("_broken")]
    rng = random.Random(day)
    return rng.sample(pool, min(SPOT_CHECK_COUNT, len(pool)))


def line(rec: dict) -> str:
    dockets = ", ".join(str(d) for d in rec.get("dockets", [])) or "none"
    return (f"[{rec['document_id']}]({rec.get('url', '')}) · {rec.get('filed_date', '?')} · "
            f"docket {dockets} · {rec.get('company') or 'no filer'} · "
            f"{(rec.get('description') or '').strip()[:140]}")


def build(day: str, friday: bool) -> str:
    recs = list(all_filings())
    log = DATA / "daily" / f"{day}.json"
    new_ids = set(json.loads(log.read_text())) if log.exists() else set()
    new = [r for r in recs if r.get("document_id") in new_ids]
    archived = sum(1 for r in recs if r.get("harvested") == day and r.get("document_id") not in new_ids)
    flagged = [(r, flags_for(r, day)) for r in recs]
    flagged = [(r, f) for r, f in flagged if f]
    new_flagged = [(r, f) for r, f in flagged if r.get("document_id") in new_ids]

    out = [f"# Public Service record digest, {day}", ""]
    out.append(f"{len(recs):,} filings in the record. {len(new)} new filings found tonight. "
               f"{len(flagged):,} carry a flag for a person to look at.")
    if archived:
        out.append(f"The backfill also archived {archived:,} older filings today.")
    out += ["", "## New filings", ""]
    out += [f"- {line(r)}" for r in sorted(new, key=lambda r: r["document_id"])] or ["- None."]

    out += ["", "## New flags", ""]
    if new_flagged:
        for r, f in new_flagged:
            out.append(f"- {line(r)}")
            out += [f"  - {x}" for x in f]
    else:
        out.append("- None today.")

    counts: dict[str, int] = {}
    for _, f in flagged:
        for x in f:
            key = x.split(":")[0] if x.startswith("attachment") else x
            key = "placeholder filed date" if "placeholder" in key else key
            key = "trade-secret attachment not stored" if "trade secret" in key else key
            counts[key] = counts.get(key, 0) + 1
    out += ["", "## All open flags by kind", ""]
    out += [f"- {k}: {v:,}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])] or ["- None."]

    if friday:
        out += ["", "## Friday spot check", "",
                "Open each PSC link and confirm the stored record matches the PSC page: "
                "filer, date, docket and description. Where a fingerprint is listed, "
                "download the file and compare its SHA-256. Tick the box and note any mismatch.", ""]
        for r in spot_check(recs, day):
            out.append(f"- [ ] {line(r)}")
            for att in r.get("attachments", []):
                fp = att.get("sha256")
                out.append(f"  - {att.get('name')}: "
                           + (f"SHA-256 `{fp}`" if fp else f"no fingerprint ({att.get('text')})"))
    out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="digest")
    ap.add_argument("--date", default=today())
    ap.add_argument("--friday", action="store_true", help="include the spot check on any day")
    a = ap.parse_args(argv)
    is_friday = dt.date.fromisoformat(a.date).weekday() == 4
    text = build(a.date, a.friday or is_friday)
    DIGESTS.mkdir(parents=True, exist_ok=True)
    p = DIGESTS / f"{a.date}.md"
    p.write_text(text)
    print(p.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
