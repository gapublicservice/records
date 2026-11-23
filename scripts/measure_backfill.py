"""Measure the Commission's record from before Sept 2022, without storing any of it.

    python scripts/measure_backfill.py --docs 900 --sizes 250 --pdfs 90 --dockets 400 --pause 2

Runs from the manual "Measure backfill" workflow. One request at a time with a
pause between, so it goes easy on the Commission's site. It samples filing
numbers and docket numbers at random, one from each equal slice of the range,
and reports estimates. Files read to check for a text layer go to a temporary
folder and are deleted. Nothing is written to the repository.

Filing numbers below FIRST_KEPT (191500, the first filing in the record, Sept
15, 2022) and docket numbers below FIRST_DOCKET (44643, the first docket dated
Sept 2022 or later) count as "before Sept 2022".
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harvester.psc import DOCKET_URL, USER_AGENT, Fetcher, parse_filing, FILING_URL  # noqa: E402
from harvester.dockets import parse_docket  # noqa: E402

FIRST_KEPT = 191500
FIRST_DOCKET = 44643
MAX_PDF = 25 * 1024 * 1024


def strata(lo: int, hi: int, n: int, rng: random.Random) -> list[int]:
    width = (hi - lo + 1) / n
    out = []
    for i in range(n):
        a = lo + int(i * width)
        b = max(a, lo + int((i + 1) * width) - 1)
        out.append(rng.randint(a, b))
    return sorted(set(out))


def decade(date: str | None) -> str:
    if not date or not re.match(r"\d{4}-", date):
        return "no date"
    y = int(date[:4])
    if y < 1950:
        return "no date"  # 1900-01-01 placeholders
    return f"{y // 10 * 10}s"


def est(hits: int, n: int, span: int) -> tuple[int, int]:
    p = hits / n if n else 0
    half = 1.96 * math.sqrt(p * (1 - p) / n) * span if n else 0
    return round(p * span), round(half)


def size_of(url: str, pause: float) -> int | None:
    time.sleep(pause)
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                n = r.headers.get("Content-Length")
                if n:
                    return int(n)
                if method == "GET":
                    total = 0
                    while chunk := r.read(1 << 20):
                        total += len(chunk)
                        if total > 500 * 1024 * 1024:
                            break
                    return total
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (403, 405, 501):
                time.sleep(pause)
                continue
            return None
        except Exception:
            return None
    return None


def pdf_check(url: str, pause: float) -> dict | None:
    time.sleep(pause)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read(MAX_PDF + 1)
    except Exception:
        return None
    if len(data) > MAX_PDF or not data.startswith(b"%PDF"):
        return None
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "f.pdf")
        with open(p, "wb") as f:
            f.write(data)
        info = subprocess.run(["pdfinfo", p], capture_output=True, text=True, timeout=60).stdout
        m = re.search(r"Pages:\s+(\d+)", info)
        pages = int(m.group(1)) if m else 0
        text = subprocess.run(["pdftotext", "-enc", "UTF-8", p, "-"], capture_output=True, timeout=300).stdout
    chars = len(re.sub(rb"\s", b"", text))
    per = chars / pages if pages else 0
    kind = "scanned" if per < 100 else ("partly" if per < 500 else "text")
    return {"pages": pages, "chars_per_page": round(per), "kind": kind}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", type=int, default=900)
    ap.add_argument("--sizes", type=int, default=250)
    ap.add_argument("--pdfs", type=int, default=90)
    ap.add_argument("--dockets", type=int, default=400)
    ap.add_argument("--pause", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default="measure.json")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    fetch = Fetcher(pause=a.pause)
    t0 = time.time()

    # 1. Filings: sample numbers 1..FIRST_KEPT-1
    span = FIRST_KEPT - 1
    ids = strata(1, span, a.docs, rng)
    docs = []
    for i, n in enumerate(ids):
        try:
            f, _ = fetch.filing(n)
        except Exception as e:  # keep going; count as unread
            docs.append({"id": n, "error": type(e).__name__})
            continue
        if f is None:
            docs.append({"id": n, "exists": False})
        else:
            docs.append({"id": n, "exists": True, "filed": f.filed_date, "dockets": f.dockets,
                         "files": [{"att": x.attachment_id, "name": x.name, "url": x.url, "ts": x.trade_secret_marked}
                                   for x in f.attachments]})
        if i % 100 == 0:
            print(f"filings {i}/{len(ids)} after {round(time.time() - t0)}s", flush=True)
    read = [d for d in docs if "error" not in d]
    hits = [d for d in read if d.get("exists")]

    # 2. File sizes and 3. text layer, on random public files from the hits
    pool = [(d, x) for d in hits for x in d["files"] if not x["ts"]]
    rng.shuffle(pool)
    sized = []
    for d, x in pool[:a.sizes]:
        s = size_of(x["url"], a.pause)
        ext = os.path.splitext(x["name"] or "")[1].lower() or "(none)"
        sized.append({"id": d["id"], "decade": decade(d["filed"]), "ext": ext, "bytes": s})
    pdfs = []
    for d, x in pool:
        if len(pdfs) >= a.pdfs:
            break
        if not (x["name"] or "").lower().endswith(".pdf"):
            continue
        r = pdf_check(x["url"], a.pause)
        if r:
            r.update({"id": d["id"], "decade": decade(d["filed"])})
            pdfs.append(r)
    print(f"files done after {round(time.time() - t0)}s", flush=True)

    # 4. Dockets: sample numbers 1..FIRST_DOCKET-1
    dspan = FIRST_DOCKET - 1
    dk = []
    for n in strata(1, dspan, a.dockets, rng):
        try:
            page = fetch.get(DOCKET_URL.format(id=n)).decode("utf-8", "replace")
            rec = parse_docket(n, page)
        except urllib.error.HTTPError as e:
            rec = None if e.code == 404 else {"error": e.code}
        except Exception as e:
            rec = {"error": type(e).__name__}
        dk.append({"id": n, **(rec or {"exists": False})})
    print(f"dockets done after {round(time.time() - t0)}s", flush=True)

    # Summary
    res: dict = {"sample": {"filing_numbers": len(ids), "read": len(read), "errors": len(docs) - len(read),
                            "with_filing": len(hits), "docket_numbers": len(dk), "seconds": round(time.time() - t0),
                            "pause": a.pause}}
    total, half = est(len(hits), len(read), span)
    res["filings_total"] = {"estimate": total, "plus_minus": half}
    by = collections.Counter(decade(d["filed"]) for d in hits)
    res["filings_by_decade"] = {k: dict(zip(("estimate", "plus_minus"), est(v, len(read), span)), sample=v)
                                for k, v in sorted(by.items())}
    years = sorted(d["filed"] for d in hits if decade(d["filed"]) != "no date")
    res["oldest_filed_in_sample"] = years[:3]
    nfiles = [len(d["files"]) for d in hits]
    ts = sum(1 for d in hits for x in d["files"] if x["ts"])
    res["files_per_filing"] = round(statistics.mean(nfiles), 2) if nfiles else 0
    res["filings_with_no_file"] = sum(1 for n in nfiles if n == 0)
    res["trade_secret_named_files_in_sample"] = ts
    got = [s for s in sized if s["bytes"]]
    b = [s["bytes"] for s in got]
    res["file_sizes"] = {"sized": len(got), "of": len(sized), "mean_bytes": round(statistics.mean(b)) if b else None,
                         "median_bytes": round(statistics.median(b)) if b else None, "max_bytes": max(b) if b else None,
                         "over_100MB": sum(1 for x in b if x > 100 * 1024 * 1024),
                         "by_ext": dict(collections.Counter(s["ext"] for s in sized).most_common(8))}
    if b:
        files_est = total * res["files_per_filing"]
        res["originals_estimate_GB"] = round(files_est * statistics.mean(b) / 1e9, 1)
    res["text_layer"] = {"checked": len(pdfs), "by_kind": dict(collections.Counter(p["kind"] for p in pdfs)),
                         "by_decade": {k: dict(collections.Counter(p["kind"] for p in pdfs if p["decade"] == k))
                                       for k in sorted({p["decade"] for p in pdfs})},
                         "pages_checked": sum(p["pages"] for p in pdfs)}
    dread = [d for d in dk if "error" not in d]
    dhits = [d for d in dread if d.get("title")]
    dt, dh = est(len(dhits), len(dread), dspan)
    res["dockets_total"] = {"estimate": dt, "plus_minus": dh, "sample_found": len(dhits), "sample_read": len(dread)}
    res["dockets_by_decade_of_date_field"] = dict(collections.Counter(decade(d.get("date")) for d in dhits))
    res["docket_industries"] = dict(collections.Counter(d.get("industry") or "?" for d in dhits).most_common(8))
    res["docket_status"] = dict(collections.Counter(d.get("status") or "?" for d in dhits).most_common(5))
    print(json.dumps(res, indent=1))
    with open(a.out, "w") as f:
        json.dump({"summary": res, "docs": docs, "sizes": sized, "pdfs": pdfs, "dockets": dk}, f)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("## Backfill measurement\n\n```json\n" + json.dumps(res, indent=1) + "\n```\n")


if __name__ == "__main__":
    main()
