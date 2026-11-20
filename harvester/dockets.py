"""Store each docket's own title, industry, date and status from its PSC page.

    python -m harvester.dockets                 # dockets in the index with no stored page
    python -m harvester.dockets --refresh-open  # also recheck open dockets not checked in 7 days
    python -m harvester.dockets --max 200

Writes data/dockets/{id}.json. The Commission's docket page is the source;
the fields are copied as it shows them.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.error

from .psc import DOCKET_URL, Fetcher, _Lines, _iso
from .run import DATA, save_json

OUT = DATA / "dockets"
LABELS = {"Title:": "title", "Industry:": "industry", "Date:": "date", "Status:": "status"}


def parse_docket(docket_id: int, page: str) -> dict | None:
    p = _Lines()
    p.feed(page)
    p.close()
    lines = p.lines
    out: dict = {"docket": docket_id, "url": DOCKET_URL.format(id=docket_id)}
    start = next((i for i, l in enumerate(lines) if l.startswith("Docket #")), None)
    if start is None:
        return None
    for i in range(start, min(start + 40, len(lines) - 1)):
        key = LABELS.get(lines[i])
        if key and key not in out:
            val = lines[i + 1].strip()
            if val not in LABELS:
                out[key] = val
    if "date" in out:
        out["date"] = _iso(out["date"]) or out["date"]
    return out if out.get("title") else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="dockets")
    ap.add_argument("--refresh-open", action="store_true")
    ap.add_argument("--max", type=int, default=5000)
    a = ap.parse_args(argv)
    index = json.loads((DATA / "index" / "dockets.json").read_text())
    now = dt.datetime.now(dt.timezone.utc)
    todo = []
    for d in sorted(index, key=lambda k: index[k]["last_filed"] or "", reverse=True):
        p = OUT / f"{d}.json"
        if not p.exists():
            todo.append(int(d))
        elif a.refresh_open:
            rec = json.loads(p.read_text())
            checked = dt.datetime.fromisoformat(rec.get("checked", "2000-01-01T00:00:00+00:00"))
            if (rec.get("status") or "").lower() != "closed" and (now - checked).days >= 7:
                todo.append(int(d))
    todo = todo[: a.max]
    f = Fetcher(pause=1.0)
    ok = missing = 0
    for d in todo:
        try:
            page = f.get(DOCKET_URL.format(id=d)).decode("utf-8", "replace")
        except urllib.error.HTTPError:
            missing += 1
            continue
        except Exception as ex:
            print(f"docket {d}: {ex}")
            missing += 1
            continue
        rec = parse_docket(d, page)
        if not rec:
            missing += 1
            continue
        rec["checked"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        save_json(OUT / f"{d}.json", rec)
        ok += 1
    print(f"dockets: {ok} stored, {missing} without a readable page, {len(todo)} tried")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
