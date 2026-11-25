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
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from . import extract, guard
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
TS_BRACKET_RE = re.compile(r"\[\s*(begin|start)\s+(trade\s+secret|ts)\b", re.I)

# 42516 is the 2019 rate case, where Georgia Power files its monthly bad debt
# report (disconnections and arrears); harvester/household.py reads it.
PRIORITY_DOCKETS = {57171, 57243, 56765, 44280, 56002, 56003, 56298, 56310, 56368, 55378, 42516}


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
    """Write whole or not at all: a run that dies mid-write leaves the last good copy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def withhold(att: dict, reason: str) -> None:
    """List the file but keep its text, size and fingerprint out of the record."""
    att["trade_secret_marked"] = True
    att["withheld"] = reason
    att["text"] = f"not stored: {reason}"
    for k in ("bytes", "sha256", "fetched", "text_file"):
        att.pop(k, None)


def store(fetcher: Fetcher, f: Filing, with_text: bool) -> dict:
    rec = f.to_dict()
    rec["harvested"] = today()
    for att in rec["attachments"]:
        reason = guard.before_download(att["name"], rec.get("description"))
        if att["trade_secret_marked"] or reason:
            withhold(att, reason or "trade-secret marker in file name")
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
        reason = guard.metadata_reason(att["name"], data)
        if reason:
            withhold(att, reason)
            continue
        text, how = extract.text_for(att["name"], data)
        reason, review = guard.text_reason(text)
        if reason:
            withhold(att, reason)
            continue
        att["bytes"] = len(data)
        # Provenance: anyone can download the file from att["url"] and compare.
        att["sha256"] = hashlib.sha256(data).hexdigest()
        att["fetched"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        att["text"] = how
        if review:
            att["review"] = review
        elif text and TS_BRACKET_RE.search(text):
            # Public versions bracket redacted trade-secret passages. Flag them
            # so a person confirms the passage really is redacted.
            att["review"] = "trade-secret brackets in text"
        if text and text.strip():
            p = text_path(f.document_id, att["attachment_id"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(extract.clean(text))
            att["text_file"] = str(p.relative_to(ROOT))
    save_json(filing_path(f.document_id), rec)
    return rec


def guard_sweep(args) -> int:
    """Apply the trade-secret checks to filings already in the record."""
    held = flagged = 0
    for path in sorted((DATA / "filings").glob("*/*.json")):
        rec = json.loads(path.read_text())
        changed = False
        for att in rec["attachments"]:
            if att.get("trade_secret_marked"):
                continue
            reason = guard.before_download(att["name"], rec.get("description"))
            review = None
            if not reason and att.get("text_file") and (ROOT / att["text_file"]).exists():
                reason, review = guard.text_reason((ROOT / att["text_file"]).read_text(errors="replace"))
            if reason:
                if att.get("text_file"):
                    (ROOT / att["text_file"]).unlink(missing_ok=True)
                withhold(att, reason)
                held += 1
                changed = True
            elif review and att.get("review") != review:
                att["review"] = review
                flagged += 1
                changed = True
        if changed:
            save_json(path, rec)
    print(f"guard-sweep: {held} files held back, {flagged} flagged for a person")
    return 0


MIDDAY = DATA / "midday"


def log_day(new_ids: list[int], folder: Path | None = None) -> None:
    if not new_ids:
        return
    p = (folder or DATA / "daily") / f"{today()}.json"
    existing = json.loads(p.read_text()) if p.exists() else []
    save_json(p, sorted(set(existing) | set(new_ids)))


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")


def nightly(args) -> int:
    """Walk the filings. If the walk fails partway, everything stored so far is
    kept and saved, but the run is not counted as a finished copy: the site
    keeps showing the time of the last run that finished."""
    fetcher = Fetcher(pause=args.pause)
    state = load_state()
    start = state.get("highest_found") or args.seed
    if not start:
        print("No starting number: pass --seed the latest known filing number.", file=sys.stderr)
        return 2
    new_ids: list[int] = []
    midday = getattr(args, "midday", False)
    try:
        _walk(fetcher, state, start, new_ids, args)
    except Exception as err:
        state["gaps"] = sorted(set(state.get("gaps", [])))
        key = "last_midday_error" if midday else "last_nightly_error"
        state[key] = {"at": now_utc(), "error": type(err).__name__, "stored": len(new_ids)}
        save_json(STATE, state)
        log_day(new_ids, MIDDAY if midday else None)
        print(f"run stopped after {len(new_ids)} new filings: {type(err).__name__}: {err}", file=sys.stderr)
        return 1
    return _finish(state, new_ids, midday)


def _walk(fetcher: Fetcher, state: dict, start: int, new_ids: list[int], args) -> None:
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


def _finish(state: dict, new_ids: list[int], midday: bool) -> int:
    state["gaps"] = sorted(set(state.get("gaps", [])))
    if midday:
        # The midday check logs apart from the nightly log, so the morning's
        # docket alerts and "Last night" list still pick these filings up.
        state["last_midday"] = now_utc()
        state.pop("last_midday_error", None)
        save_json(STATE, state)
        log_day(new_ids, MIDDAY)
    else:
        state["last_nightly"] = today()
        state["last_nightly_at"] = now_utc()
        state.pop("last_nightly_error", None)
        save_json(STATE, state)
        yesterday = (dt.date.fromisoformat(today()) - dt.timedelta(days=1)).isoformat()
        mid = MIDDAY / f"{yesterday}.json"
        log_day(new_ids + (json.loads(mid.read_text()) if mid.exists() else []))
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


def fingerprint(args) -> int:
    """Add a SHA-256 fingerprint to attachments read before fingerprints existed."""
    fetcher = Fetcher(pause=args.pause)
    done = failed = 0
    deadline = time.monotonic() + args.max_minutes * 60
    for path in sorted((DATA / "filings").glob("*/*.json")):
        if time.monotonic() > deadline:
            break
        rec = json.loads(path.read_text())
        changed = False
        for att in rec["attachments"]:
            if att.get("trade_secret_marked") or "bytes" not in att or "sha256" in att:
                continue
            try:
                data = fetcher.get(att["url"], max_bytes=MAX_ATTACHMENT_BYTES)
            except Exception as e:
                att["fingerprint"] = f"download failed: {type(e).__name__}"
                failed += 1
                changed = True
                continue
            att["sha256"] = hashlib.sha256(data).hexdigest()
            att["fetched"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            if len(data) != att["bytes"]:
                att["review"] = f"file size changed since first read ({att['bytes']} to {len(data)} bytes)"
            done += 1
            changed = True
        if changed:
            save_json(path, rec)
    print(f"fingerprint: {done} attachments fingerprinted, {failed} failed")
    return 0


def one(args) -> int:
    fetcher = Fetcher(pause=args.pause)
    f, page = fetcher.filing(args.id)
    if args.save_html:
        Path(args.save_html).write_text(page)
    if not f:
        # An empty number is an answer, not a failure, so the run stays green.
        print(f"{args.id}: no filing at this number")
        return 0
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
    n.add_argument("--midday", action="store_true", help="the midday check: log to data/midday, leave last_nightly")
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

    fp = sub.add_parser("fingerprint")
    fp.add_argument("--max-minutes", type=float, default=330)
    fp.set_defaults(func=fingerprint)

    g = sub.add_parser("guard-sweep", help="apply the trade-secret checks to stored filings")
    g.set_defaults(func=guard_sweep)

    o = sub.add_parser("one")
    o.add_argument("id", type=int)
    o.add_argument("--store", action="store_true")
    o.add_argument("--save-html")
    o.set_defaults(func=one)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
