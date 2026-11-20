"""Harvest Georgia bills into data/legislature/.

    python -m legis.run session 2025_26            # every measure, record only
    python -m legis.run session 2025_26 --text     # plus version text for bills in scope
    python -m legis.run one 2025_26 69287          # one bill by its page number
    python -m legis.run new 2025_26                # measures not seen before (the frequent run)
    python -m legis.run discover                   # list the sessions this harvester knows
    python -m legis.run probe 69287                # save one real response as a test fixture

Version text is pulled for every bill in the public scope, and for no other
bill. The scope is set by public rules in legis/scope.py and nothing else.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

from . import scope, store, textdiff
from .service import KNOWN_SESSIONS, Service, bill_key, normalize, slug, vote_ids

UA = "records-harvester (public record; one request at a time)"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def capture_text(bill: dict) -> list[dict]:
    """Download new versions, clean them, compare each with the one before and
    with the introduced version. Returns the comparisons made."""
    session, sl = bill["session"], bill["slug"]
    made = []
    versions = [v for v in store.ordered_versions(bill) if v.get("doc_id")]
    for v in versions:
        p = store.version_path(session, sl, v["doc_id"])
        if p.exists():
            continue
        try:
            raw = textdiff.pdf_text(fetch(v["url"]))
        except Exception as e:
            print(f'  {bill["key"]}: version {v["doc_id"]} not read ({type(e).__name__})', file=sys.stderr)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textdiff.clean(raw))
    full = [v for v in versions if not store.is_floor_amendment(v)
            and store.version_path(session, sl, v["doc_id"]).exists()]
    pairs = list(zip(full, full[1:]))
    if len(full) > 2:
        pairs.append((full[0], full[-1]))
    for a, b in pairs:
        cp = store.compare_path(session, sl, a["doc_id"], b["doc_id"])
        if cp.exists():
            continue
        old = store.version_path(session, sl, a["doc_id"]).read_text()
        new = store.version_path(session, sl, b["doc_id"]).read_text()
        c = textdiff.compare(old, new)
        rec = {"bill": bill["key"], "from": a, "to": b, "summary": c["summary"],
               "html": textdiff.to_html(c["ops"]), "made": store.now()}
        store.write_json(cp, rec)
        made.append(rec)
    return made


def harvest_one(svc: Service, session: str, legislation_id: int, text: bool) -> dict:
    raw = svc.detail(legislation_id)
    votes = [svc.vote(i) for i in vote_ids(raw)]
    bill = normalize(raw, session, votes)
    latest_text = ""
    if bill["versions"]:
        last = store.ordered_versions(bill)[-1]
        p = store.version_path(session, bill["slug"], last["doc_id"])
        latest_text = p.read_text() if p.exists() else ""
    bill["scope"] = scope.reasons(bill, latest_text)
    changed = store.save_bill(bill)
    if text and bill["scope"] and ("new" in changed or "versions" in changed):
        capture_text(store.load_bill(session, bill["slug"]))
    if changed:
        print(f'{bill["key"]}: {", ".join(changed)}')
    return bill


def write_index(session: str, rows: list[dict]) -> None:
    short = [{"id": r.get("Id"), "key": bill_key(r), "slug": slug(bill_key(r)),
              "caption": (r.get("Caption") or "").strip()} for r in rows]
    store.write_json(store.sess_dir(session) / "index.json", short)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("session"); s.add_argument("session"); s.add_argument("--text", action="store_true")
    s.add_argument("--limit", type=int)
    o = sub.add_parser("one"); o.add_argument("session"); o.add_argument("id", type=int)
    n = sub.add_parser("new"); n.add_argument("session")
    sub.add_parser("discover")
    pr = sub.add_parser("probe"); pr.add_argument("id", type=int)
    a = ap.parse_args(argv)
    svc = Service()
    if a.cmd == "probe":
        # Save one real response, so tests run against what the service sends.
        raw = svc.detail(a.id)
        fx = store.ROOT / "tests" / "legis" / "fixtures"
        fx.mkdir(parents=True, exist_ok=True)
        (fx / f"detail_{a.id}.json").write_text(json.dumps(raw, indent=1, default=str))
        ids = vote_ids(raw)
        if ids:
            (fx / f"vote_{ids[0]}.json").write_text(json.dumps(svc.vote(ids[0]), indent=1, default=str))
        print(json.dumps(normalize(raw, "2025_26"), indent=1, default=str)[:4000])
        return 0
    if a.cmd == "discover":
        print(json.dumps(KNOWN_SESSIONS, indent=1))
        return 0
    sid = KNOWN_SESSIONS[a.session]["id"]
    if a.cmd == "one":
        harvest_one(svc, a.session, a.id, True)
        return 0
    rows = svc.index(sid)
    write_index(a.session, rows)
    if a.cmd == "new":
        # New measures, plus every bill already in scope, since substitutes and
        # status changes land the same day.
        have = {b["slug"]: b for b in store.all_bills(a.session)}
        follow = {s for s, b in have.items() if b.get("scope")}
        rows = [r for r in rows if slug(bill_key(r)) not in have or slug(bill_key(r)) in follow]
    if getattr(a, "limit", None):
        rows = rows[: a.limit]
    for r in rows:
        try:
            harvest_one(svc, a.session, r["Id"], a.cmd == "new" or a.text)
        except Exception as e:  # one bad record should not stop the run
            print(f'{bill_key(r)}: failed ({type(e).__name__}: {e})', file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
