"""Second look at a measure.json from the Measure backfill run. Reads only that file."""
import bisect, collections, json, statistics, sys

d = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "measure.json"))
docs = [x for x in d["docs"] if x.get("exists")]

def dec(s):
    return f"{int(s[:4]) // 10 * 10}s" if s and s[:4].isdigit() and int(s[:4]) >= 1950 else "no date"

# Files per filing and filings with no file, by decade
by = collections.defaultdict(list)
for x in docs:
    by[dec(x["filed"])].append(len(x["files"]))
print("files per filing by decade:", {k: (len(v), round(statistics.mean(v), 2), sum(1 for n in v if n == 0)) for k, v in sorted(by.items())})
ext = collections.defaultdict(collections.Counter)
for x in docs:
    for f in x["files"]:
        n = (f["name"] or "").lower()
        ext[dec(x["filed"])][n.rsplit(".", 1)[-1] if "." in n else "none"] += 1
print("file types by decade:", {k: dict(v.most_common(5)) for k, v in sorted(ext.items())})
s = [x for x in d["sizes"] if x["bytes"]]
print("size by decade (n, mean, median):", {k: (len(v), round(statistics.mean(v)), round(statistics.median(v)))
      for k, v in sorted(collections.defaultdict(list, {k: [y["bytes"] for y in s if y["decade"] == k] for k in {y["decade"] for y in s}}).items())})
p = d["pdfs"]
print("pdf pages: mean", round(statistics.mean(x["pages"] for x in p), 1), "median", statistics.median(x["pages"] for x in p))

# Dockets: date a docket by the earliest sampled filing that names it
first = {}
for x in docs:
    if dec(x["filed"]) == "no date":
        continue
    for k in x["dockets"]:
        if k < 44643 and (k not in first or x["filed"] < first[k]):
            first[k] = x["filed"]
pairs = sorted(first.items())
ids = [k for k, _ in pairs]
found = [x for x in d["dockets"] if x.get("title")]
cnt = collections.Counter()
for x in found:
    i = bisect.bisect_left(ids, x["id"])
    near = min((j for j in (i - 1, i) if 0 <= j < len(ids)), key=lambda j: abs(ids[j] - x["id"]), default=None)
    cnt[dec(pairs[near][1]) if near is not None else "?"] += 1
print("dockets dated by nearest sampled filing:", dict(cnt), "of", len(found), "; filing-docket pairs used:", len(pairs))
for decade in ("1990s", "2000s", "2010s", "2020s"):
    ks = [k for k, v in pairs if dec(v) == decade]
    if ks:
        print(decade, "docket numbers seen: min", min(ks), "median", int(statistics.median(ks)), "max", max(ks), "n", len(ks))
