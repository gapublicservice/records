"""Collect meeting agendas from the Commission calendar.

    python -m harvester.agendas [--back 60] [--ahead 45]

Each event on the Commission calendar has its own page, and the Commission
attaches the agenda there as a Word file (sometimes a PDF) under
/site/assets/files/. Agendas appear a few days before a meeting and are
sometimes amended, so every night we re-read the pages of events from 60 days
back to 45 days ahead, keep the address of each agenda file, and read the file
for the docket numbers it lists and the line that names each one.

Writes data/index/agendas.json. Entries outside the window are kept as they are.
For each file we keep its text, line by line, so the records site can show the
agenda as a page with every docket linked, and the docket numbers it lists with
the line that names each one. The Commission's file stays the one to cite.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import io
import re
import shutil
import subprocess
import tempfile
import zipfile

from .calendar import BASE, EASTERN, OUT as CALENDAR
from .psc import Fetcher
from .run import DATA, save_json

OUT = DATA / "index" / "agendas.json"
MAX_BYTES = 15 * 1024 * 1024

_FILE = re.compile(r'<a\b[^>]*href="((?:https://psc\.ga\.gov)?/site/assets/files/\d+/([^"/?#]+\.(?:docx?|pdf)))"',
                   re.I)
_DOCKET_CTX = re.compile(r"docket\s*(?:nos?\.?|numbers?|#)?\s*:?\s*((?:\d{4,5}(?:\s*-\s*[A-Z])?[\s,;&]*(?:and\s*)?)+)", re.I)
_NUM = re.compile(r"(?<!\d)(\d{4,5})(?!\d)")  # older dockets have four digits


def agenda_files(page: str) -> list[dict]:
    """Agenda files linked from one event page, in page order, no repeats."""
    seen, out = set(), []
    for href, name in _FILE.findall(page):
        url = href if href.startswith("http") else BASE + href
        if url in seen:
            continue
        seen.add(url)
        out.append({"name": html.unescape(name), "url": url})
    return out


def label_for(name: str) -> str:
    """A short plain label from the file name: 'Energy committee', 'Administrative session'."""
    n = name.lower()
    amended = "amend" in n
    for key, label in (("energy", "Energy committee"), ("telecom", "Telecommunications committee"),
                       ("facilit", "Facilities Protection committee"), ("admin_affairs", "Administrative Affairs committee"),
                       ("admin affairs", "Administrative Affairs committee"), ("admin", "Administrative session")):
        if key in n:
            return f"Amended {label[0].lower()}{label[1:]}" if amended else label
    return "Amended agenda" if amended else "Agenda"


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def _tool_text(cmd: list[str], data: bytes, suffix: str) -> str | None:
    if not shutil.which(cmd[0]):
        return None
    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(data)
        f.flush()
        try:
            r = subprocess.run(cmd + [f.name] + (["-"] if cmd[0] == "pdftotext" else []),
                               capture_output=True, timeout=60)
        except Exception:  # noqa: BLE001
            return None
    out = r.stdout.decode("utf-8", "replace")
    return out if r.returncode == 0 and out.strip() else None


def _crude_text(data: bytes) -> str:
    """Last resort for old Word files: printable runs from the raw bytes."""
    parts = []
    for enc in ("utf-16le", "latin-1"):
        t = data.decode(enc, "replace")
        parts += re.findall(r"[ -~\t\r\n]{6,}", t)
    return "\n".join(parts)


def text_of(name: str, data: bytes) -> str:
    n = name.lower()
    if n.endswith(".docx") or data[:2] == b"PK":
        try:
            return _docx_text(data)
        except Exception:  # noqa: BLE001
            pass
    if n.endswith(".pdf") or data[:4] == b"%PDF":
        return _tool_text(["pdftotext", "-layout"], data, ".pdf") or ""
    return (_tool_text(["antiword", "-w", "0"], data, ".doc")
            or _tool_text(["catdoc", "-w"], data, ".doc")
            or _crude_text(data))


def dockets_in(text: str) -> list[dict]:
    """Docket numbers named after the word 'docket', each with the line it sits on."""
    items: dict[int, str] = {}
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.replace("\r", "\n").split("\n")]
    for i, line in enumerate(lines):
        for m in _DOCKET_CTX.finditer(line):
            for num in _NUM.findall(m.group(1)):
                d = int(num)
                if 1000 <= d <= 99999 and not 1990 <= d <= 2039 and d not in items:
                    # the item often runs onto the next line; keep up to 240 characters
                    nxt = lines[i + 1] if i + 1 < len(lines) else ""
                    joins = (len(line) <= 100 or line.endswith(":")) and nxt and not re.match(r"\(?(\d+|[A-Za-z]|[ivx]+)[.)]\s|[A-Z]{1,2}-?\d{1,2}\.\s|docket", nxt, re.I)
                    ctx = f"{line} {nxt}" if joins else line
                    items[d] = ctx[:240].rstrip()
    return [{"docket": d, "line": items[d]} for d in sorted(items)]


def text_lines(text: str, limit: int = 1500) -> list[str]:
    """The agenda's lines, spaces tidied, runs of blank lines kept to one."""
    out = []
    for raw in text.replace("\r", "\n").replace("\f", "\n").split("\n"):
        line = re.sub(r"[ \t\u00a0]+", " ", raw).strip()
        line = "".join(ch for ch in line if ch >= " " or ch == "\t")
        if not line:
            if out and out[-1]:
                out.append("")
            continue
        out.append(line[:1200])
        if len(out) >= limit:
            break
    while out and not out[-1]:
        out.pop()
    return out


def collect(events: list[dict], old: dict, fetch: Fetcher, today: dt.date,
            back: int = 60, ahead: int = 45) -> tuple[dict, int, int]:
    lo, hi = (today - dt.timedelta(days=back)).isoformat(), (today + dt.timedelta(days=ahead)).isoformat()
    out = dict(old)
    pages = files_read = 0
    for ev in events:
        if not (lo <= ev["date"] <= hi):
            continue
        try:
            page = fetch.get(ev["url"]).decode("utf-8", "replace")
        except Exception as err:  # noqa: BLE001
            print(f"could not read {ev['url']}: {err}")
            continue
        pages += 1
        found = agenda_files(page)
        if not found:
            continue
        prev = {f["url"]: f for f in (old.get(ev["url"]) or {}).get("files", [])}
        files = []
        for f in found:
            rec = {"name": f["name"], "url": f["url"], "label": label_for(f["name"])}
            try:
                data = fetch.get(f["url"], max_bytes=MAX_BYTES)
                text = text_of(f["name"], data)
                rec["items"] = dockets_in(text)
                rec["text"] = text_lines(text)
                files_read += 1
            except Exception as err:  # noqa: BLE001
                print(f"could not read {f['url']}: {err}")
                rec["items"] = prev.get(f["url"], {}).get("items", [])
                if prev.get(f["url"], {}).get("text"):
                    rec["text"] = prev[f["url"]]["text"]
            files.append(rec)
        out[ev["url"]] = {"date": ev["date"], "time": ev["time"], "title": ev["title"], "kind": ev["kind"],
                          "files": files, "read": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                          "dockets": sorted({i["docket"] for f in files for i in f["items"]})}
    return out, pages, files_read


def load() -> dict:
    import json
    return json.loads(OUT.read_text()).get("events", {}) if OUT.exists() else {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--back", type=int, default=60)
    ap.add_argument("--ahead", type=int, default=45)
    a = ap.parse_args(argv)
    import json
    if not CALENDAR.exists():
        print("No calendar yet; run harvester.calendar first.")
        return 0
    events = json.loads(CALENDAR.read_text()).get("events", [])
    today = dt.datetime.now(EASTERN).date()
    out, pages, files_read = collect(events, load(), Fetcher(), today, a.back, a.ahead)
    save_json(OUT, {"source": BASE + "/agendas-calendars/commission-calendar/",
                    "checked": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    "events": dict(sorted(out.items(), key=lambda kv: kv[1]["date"]))})
    with_agenda = sum(1 for v in out.values() if v["files"])
    print(f"read {pages} event pages and {files_read} agenda files; {with_agenda} meetings with agendas on record")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
