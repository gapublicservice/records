"""Harvest Georgia PSC filings into data/.

    python -m harvester.run nightly
    python -m harvester.run backfill --start 219000 --end 229500
    python -m harvester.run one 229480

Nightly walks forward from the highest filing number seen, stops for the night
after 25 empty numbers in a row, and rechecks each empty number nightly for 30
days, because a number can be skipped and filled later.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

from . import extract
from .psc import Fetcher, Filing, TooLarge

ROOT = Path(os.environ.get("RECORDS_ROOT", Path(__file__).resolve().parent.parent))
DATA = ROOT / "data"
STATE = DATA / "state.json"

EMPTY_RUN_LIMIT = 25
RECHECK_DAYS = 30
MAX_ATTACHMENT_BYTES = 60_000_000

# Dockets whose older filings get full text in a backfill. New filings on
# every docket get full text nightly.
# 56368 is the 2032-33 all-source RFP (an earlier list had 56189, which shows no filings).
PRIORITY_DOCKETS = {57171, 57243, 56765, 44280, 56002, 56003, 56298, 56310, 56368, 55378}


def today() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def filing_path(doc_id: int) -> Path:
    return DATA / "filings" / str(doc_id // 1000) / f"{doc_id}.json"


def text_path(doc_id: int, att_id: int) -> Path:
    return DATA / "text" / str(doc_id // 1000) / str(doc_id) / f"{att_id}.txt"


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"highest_found": None, "empty": {}, "backfill_empty": []}


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def store(fetcher: Fetcher, f: Filing, with_text: bool) -> dict:
    rec = f.to_dict()
    rec["harvested"] = today()
    for att in rec["attachments"]:
        if att["trade_secret_marked"]:
            att["text"] = "not stored: trade-secret marker in file name"
            continue
        if not with_text:
            att["text"] = "not read yet"
            continue
        try:
            data = fetcher.get(att["url"], max_bytes=MAX_ATTACHMENT_BYTES)
        except TooLarge:
            att["text"] = "not read: file too large"
            continue
        except Exception as e:
            att["text"] = f"download failed: {type(e).__name__}"
            continue
        att["bytes"] = len(data)
        text, how = extract.text_for(att["name"], data)
        att["text"] = how
        if text and text.strip():
            p = text_path(f.document_id, att["attachment_id"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(extract.clean(text))
            att["text_file"] = str(p.relative_to(ROOT))
    save_json(filing_path(f.document_id), rec)
    return rec


def log_day(new_ids: list[int]) -> None:
    if not new_ids:
        return
    p = DATA / "daily" / f"{today()}.json"
    existing = json.loads(p.read_text()) if p.exists() else []
    save_json(p, sorted(set(existing) | set(new_ids)))


def nightly(args) -> int:
    fetcher = Fetcher(pause=args.pause)
    state = load_state()
    start = state.get("highest_found") or args.seed
    if not start:
        print("No starting number: pass --seed the latest known filing number.", file=sys.stderr)
        return 2
    new_ids: list[int] = []

    # 1. Recheck recent empty numbers.
    cutoff = (dt.date.fromisoformat(today()) - dt.timedelta(days=RECHECK_DAYS)).isoformat()
    for key, first in sorted(state["empty"].items()):
        doc_id = int(key)
        if first < cutoff:
            state.setdefault("gaps", []).append(doc_id)  # never appeared
            del state["empty"][key]
            continue
        f, _ = fetcher.filing(doc_id)
        if f:
            store(fetcher, f, with_text=True)
            new_ids.append(doc_id)
            del state["empty"][key]

    # 2. Walk forward.
    doc_id = start if not filing_path(start).exists() else start + 1
    empties, deadline = 0, time.monotonic() + args.max_minutes * 60
    while empties < EMPTY_RUN_LIMIT and time.monotonic() < deadline:
        f, _ = fetcher.filing(doc_id)
        if f:
            store(fetcher, f, with_text=True)
            new_ids.append(doc_id)
            # Numbers skipped just below a hit go on the recheck list.
            for gap in range(doc_id - empties, doc_id):
                state["empty"].setdefault(str(gap), today())
            state["highest_found"] = max(state.get("highest_found") or 0, doc_id)
            empties = 0
        else:
            empties += 1
        doc_id += 1
    # Trailing empties above the highest hit are simply tried again tomorrow.

    state["gaps"] = sorted(set(state.get("gaps", [])))
    state["last_nightly"] = today()
    save_json(STATE, state)
    log_day(new_ids)
    print(f"nightly: {len(new_ids)} new filings; highest {state['highest_found']}; "
          f"{len(state['empty'])} numbers on the recheck list")
    return 0


def backfill(args) -> int:
    fetcher = Fetcher(pause=args.pause)
    state = load_state()
    cursor_key = f"{args.start}-{args.end}"
    cursors = state.setdefault("backfill_cursor", {})
    doc_id = cursors.get(cursor_key, args.start)
    deadline = time.monotonic() + args.max_minutes * 60
    found = 0
    empty = set(state.get("backfill_empty", []))
    while doc_id <= args.end and time.monotonic() < deadline:
        if filing_path(doc_id).exists() and not args.refresh:
            doc_id += 1
            continue
        f, _ = fetcher.filing(doc_id)
        if f:
            with_text = args.all_text or bool(PRIORITY_DOCKETS & set(f.dockets))
            store(fetcher, f, with_text=with_text)
            empty.discard(doc_id)
            found += 1
            state["highest_found"] = max(state.get("highest_found") or 0, doc_id)
        else:
            empty.add(doc_id)
        doc_id += 1
        if found and found % 200 == 0:
            cursors[cursor_key] = doc_id
            state["backfill_empty"] = sorted(empty)
            save_json(STATE, state)
    if doc_id > args.end:
        cursors.pop(cursor_key, None)
    else:
        cursors[cursor_key] = doc_id
    state["backfill_empty"] = sorted(empty)
    save_json(STATE, state)
    done = "done" if doc_id > args.end else f"stopped at {doc_id}, resumes there next run"
    print(f"backfill {cursor_key}: {found} filings stored; {done}")
    return 0


def retext(args) -> int:
    """Fetch full text for stored filings on the given dockets that lack it."""
    from .psc import Attachment
    fetcher = Fetcher(pause=args.pause)
    dockets = set(args.dockets)
    done = 0
    for path in sorted((DATA / "filings").glob("*/*.json")):
        rec = json.loads(path.read_text())
        if not dockets & set(rec.get("dockets", [])):
            continue
        if not any(a.get("text") == "not read yet" for a in rec["attachments"]):
            continue
        f = Filing(**{k: rec[k] for k in ("document_id", "url", "company", "description",
                                          "filed_date", "received_date", "dockets")})
        f.attachments = [Attachment(**{k: a[k] for k in ("attachment_id", "name", "url",
                                                         "trade_secret_marked")})
                         for a in rec["attachments"]]
        store(fetcher, f, with_text=True)
        done += 1
    print(f"retext: {done} filings given full text")
    return 0


def one(args) -> int:
    fetcher = Fetcher(pause=args.pause)
    f, page = fetcher.filing(args.id)
    if args.save_html:
        Path(args.save_html).write_text(page)
    if not f:
        print(f"{args.id}: no filing")
        return 1
    rec = store(fetcher, f, with_text=True) if args.store else f.to_dict()
    print(json.dumps(rec, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harvester")
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between requests")
    sub = ap.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("nightly")
    n.add_argument("--seed", type=int, help="latest known filing number, first run only")
    n.add_argument("--max-minutes", type=float, default=90)
    n.set_defaults(func=nightly)

    b = sub.add_parser("backfill")
    b.add_argument("--start", type=int, required=True)
    b.add_argument("--end", type=int, required=True)
    b.add_argument("--max-minutes", type=float, default=330)
    b.add_argument("--all-text", action="store_true", help="full text for every docket")
    b.add_argument("--refresh", action="store_true", help="refetch filings already stored")
    b.set_defaults(func=backfill)

    r = sub.add_parser("retext")
    r.add_argument("dockets", type=int, nargs="+")
    r.set_defaults(func=retext)

    o = sub.add_parser("one")
    o.add_argument("id", type=int)
    o.add_argument("--store", action="store_true")
    o.add_argument("--save-html")
    o.set_defaults(func=one)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
