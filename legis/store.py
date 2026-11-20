"""Where bill records live, and the change log.

data/legislature/<session>/bills/<slug>.json      one record per bill
data/legislature/<session>/versions/<slug>/<doc>.txt   cleaned text of each version
data/legislature/<session>/compare/<slug>/<old>-<new>.json   comparisons
data/legislature/<session>/changes.jsonl          every change, with when it was first seen
data/legislature/<session>/index.json             the session's measures, short form
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("RECORDS_ROOT", Path(__file__).resolve().parent.parent))
DATA = ROOT / "data" / "legislature"

TRACKED = ("caption", "summary", "sponsors", "committees", "status_history",
           "versions", "votes", "act_veto_number")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sess_dir(session: str) -> Path:
    return DATA / session


def bill_path(session: str, slug: str) -> Path:
    return sess_dir(session) / "bills" / f"{slug}.json"


def version_path(session: str, slug: str, doc_id) -> Path:
    return sess_dir(session) / "versions" / slug / f"{doc_id}.txt"


def compare_path(session: str, slug: str, old, new) -> Path:
    return sess_dir(session) / "compare" / slug / f"{old}-{new}.json"


def load_bill(session: str, slug: str) -> dict | None:
    p = bill_path(session, slug)
    return json.loads(p.read_text()) if p.exists() else None


def write_text(p: Path, text: str) -> None:
    """Write to a .part file, then swap it in, so a run stopped midway never leaves half a file."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".part")
    tmp.write_text(text)
    os.replace(tmp, p)


def write_json(p: Path, obj) -> None:
    write_text(p, json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=False) + "\n")


def diff_fields(old: dict | None, new: dict) -> list[str]:
    if old is None:
        return ["new"]
    return [k for k in TRACKED if old.get(k) != new.get(k)]


def save_bill(new: dict) -> list[str]:
    """Write the record, keep first-seen times, and log what changed."""
    session, slug = new["session"], new["slug"]
    old = load_bill(session, slug)
    seen = (old or {}).get("first_seen", {})
    t = now()
    seen.setdefault("bill", t)
    for v in new.get("versions", []):
        seen.setdefault(f'version:{v["doc_id"]}', t)
    for h in new.get("status_history", []):
        seen.setdefault(f'status:{h.get("id") or h.get("date")}', t)
    new["first_seen"] = seen
    changed = diff_fields(old, new)
    if changed:
        new["updated"] = t
        write_json(bill_path(session, slug), new)
        log = sess_dir(session) / "changes.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as f:
            f.write(json.dumps({"at": t, "bill": new["key"], "changed": changed}) + "\n")
    return changed


def all_bills(session: str) -> list[dict]:
    d = sess_dir(session) / "bills"
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.exists() else []


def ordered_versions(bill: dict) -> list[dict]:
    """The site lists versions out of date order. Order by when each was first seen,
    then by document id, which rises with filing."""
    seen = bill.get("first_seen", {})
    return sorted(bill.get("versions", []),
                  key=lambda v: (seen.get(f'version:{v["doc_id"]}', ""), v.get("doc_id") or 0))


def is_floor_amendment(v: dict) -> bool:
    lab = (v.get("label") or "").lower()
    return "floor amend" in lab or " am " in f" {lab} " or "amendment" in lab and "substitute" not in lab
