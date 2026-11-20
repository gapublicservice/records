"""Read-only probe: save a few Commission agenda pages and list their agenda links.

    python scripts/probe_agendas.py OUTDIR URL [URL ...]
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harvester.psc import Fetcher  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
f = Fetcher()
for i, url in enumerate(sys.argv[2:]):
    try:
        page = f.get(url).decode("utf-8", "replace")
    except Exception as err:  # noqa: BLE001
        print(f"== {url}\n   failed: {err}"); continue
    (out / f"page{i}.html").write_text(page)
    print(f"== {url} ({len(page)} bytes)")
    for href, text in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S | re.I):
        t = re.sub(r"<[^>]+>|\s+", " ", text).strip()
        if re.search(r"agenda|\.pdf|minutes|recap|video|webcast|\.ics|ical|webcal|export|feed|rss|subscribe|google\.com/calendar|outlook|add to", href + " " + t, re.I):
            print(f"   {t[:70]!r} -> {href[:160]}")
    for m in re.finditer(r"(BEGIN:VCALENDAR|text/calendar|\.ics\b|webcal:|data-ical|addtocalendar|add-to-calendar)", page, re.I):
        print(f"   marker: {page[max(0, m.start()-80):m.end()+80]!r}")
