"""Calendar files for the records site: one feed to subscribe to, one file per meeting.

The Commission's own calendar has no feed and no add-to-calendar link, so we
build both from data/index/calendar.json (and the agenda files we found):

    _site/calendar.ics        every meeting, refreshed each night (subscribe to this)
    _site/cal/<id>.ics        one meeting, for an "Add" button

Events that are not the Commission's own can be listed by hand in
data/reference/other-events.json. Each is marked "Not a Commission event"
wherever it appears. Format: a list of
    {"date": "2026-12-03", "time": "6:00 PM", "title": "...", "url": "https://...",
     "minutes": 90, "where": "..."}
Only date and title are required.

The Commission lists start times only, so every meeting is given two hours. Times
are Georgia time (America/New_York).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import urllib.parse
from pathlib import Path

from .run import DATA

HOST = "records.gapublicservice.org"
SITE = f"https://{HOST}"
FEED = f"{SITE}/calendar.ics"
OTHER = DATA / "reference" / "other-events.json"
DEFAULT_MINUTES = 120
NOT_PSC = "Not a Commission event."

KIND = {"hearing": "Hearing", "docket": "Hearing", "session": "Administrative session",
        "committee": "Committee meeting", "forum": "Public forum",
        "working group": "Working group", "other": "Meeting"}

VTIMEZONE = """BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE"""

_TIME = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?\s*[Mm]\.?\s*$")


def parse_time(text: str | None) -> tuple[int, int] | None:
    m = _TIME.match(text or "")
    if not m:
        return None
    h, mi = int(m.group(1)) % 12, int(m.group(2) or 0)
    if m.group(3).lower() == "p":
        h += 12
    return h, mi


def uid_for(ev: dict) -> str:
    """A short id that stays the same for the same meeting from night to night."""
    key = ev.get("url") or f'{ev["date"]}|{ev["title"]}'
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def clean_title(ev: dict) -> str:
    t = re.sub(r"\s*\d{1,2}-\d{1,2}(-\d{2,4})?$", "", ev.get("title") or "").strip()
    return re.sub(r"(?<=[a-z])\?s\b", "’s", t)


def summary_for(ev: dict) -> str:
    if ev.get("other"):
        return clean_title(ev)
    kind = KIND.get(ev.get("kind"), "Meeting")
    title = clean_title(ev)
    plain = ev.get("kind") in ("session", "committee") or title.lower() == kind.lower()
    return f"PSC {kind}" if plain else f"PSC {kind}: {title}"


def times(ev: dict) -> tuple[dt.datetime, dt.datetime] | tuple[dt.date, dt.date]:
    day = dt.date.fromisoformat(ev["date"])
    hm = parse_time(ev.get("time"))
    if not hm:
        return day, day + dt.timedelta(days=1)
    start = dt.datetime(day.year, day.month, day.day, *hm)
    return start, start + dt.timedelta(minutes=int(ev.get("minutes") or DEFAULT_MINUTES))


def details_for(ev: dict, agendas: dict, known: set[str] | None = None) -> str:
    """Plain text for the event's description: what it is, agendas, dockets, the source page."""
    lines = []
    if ev.get("other"):
        lines.append(NOT_PSC + (f" {ev['note']}" if ev.get("note") else ""))
    else:
        lines.append(clean_title(ev))
    files = (agendas.get(ev.get("url")) or {}).get("files") or []
    for f in files:
        lines.append(f'{f.get("label") or "Agenda"}: {f["url"]}')
    dockets = sorted({int(d) for d in ev.get("dockets") or []}
                     | {int(d) for d in (agendas.get(ev.get("url")) or {}).get("dockets") or []})
    for d in dockets:
        if known is None or str(d) in known:
            lines.append(f"Docket {d}: {SITE}/docket/{d}/")
    if ev.get("url"):
        lines.append(("Details: " if ev.get("other") else "Commission page: ") + ev["url"])
    if not ev.get("other"):
        lines.append("Times are the Commission's start times; the two-hour length is our estimate. "
                     "Check the Commission's page for changes.")
    return "\n".join(lines)


def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\n").replace("\n", "\\n"))


def _fold(line: str) -> str:
    """Fold at 75 octets, as the calendar format asks."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode()
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode())
            cur = b""
        cur += b
    out.append(cur.decode())
    return "\r\n ".join(out)


def vevent(ev: dict, agendas: dict, stamp: str, known: set[str] | None = None) -> str:
    a, b = times(ev)
    if isinstance(a, dt.datetime):
        when = [f"DTSTART;TZID=America/New_York:{a:%Y%m%dT%H%M%S}",
                f"DTEND;TZID=America/New_York:{b:%Y%m%dT%H%M%S}"]
    else:
        when = [f"DTSTART;VALUE=DATE:{a:%Y%m%d}", f"DTEND;VALUE=DATE:{b:%Y%m%d}"]
    lines = ["BEGIN:VEVENT", f"UID:{uid_for(ev)}@{HOST}", f"DTSTAMP:{stamp}", *when,
             f"SUMMARY:{_esc(summary_for(ev))}", f"DESCRIPTION:{_esc(details_for(ev, agendas, known))}"]
    if ev.get("url"):
        lines.append(f"URL:{ev['url']}")
    if ev.get("where"):
        lines.append(f"LOCATION:{_esc(ev['where'])}")
    if ev.get("other"):
        lines.append("CATEGORIES:Not a Commission event")
    lines.append("END:VEVENT")
    return "\r\n".join(_fold(l) for l in lines)


def calendar(events: list[dict], agendas: dict, name: str, known: set[str] | None = None,
             now: dt.datetime | None = None) -> str:
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    head = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Public Service//records//EN", "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(name)}", "X-WR-TIMEZONE:America/New_York",
            _fold("X-WR-CALDESC:" + _esc("Georgia Public Service Commission meetings, copied each night from "
                                         "psc.ga.gov by Public Service, an independent project. Not a product "
                                         "of the Commission.")),
            "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H"]
    body = [vevent(ev, agendas, stamp, known) for ev in events]
    return "\r\n".join(head + [VTIMEZONE.replace("\n", "\r\n")] + body + ["END:VCALENDAR"]) + "\r\n"


def google_link(ev: dict, agendas: dict, known: set[str] | None = None) -> str:
    a, b = times(ev)
    fmt = "%Y%m%dT%H%M%S" if isinstance(a, dt.datetime) else "%Y%m%d"
    q = {"action": "TEMPLATE", "text": summary_for(ev), "dates": f"{a:{fmt}}/{b:{fmt}}",
         "ctz": "America/New_York", "details": details_for(ev, agendas, known)}
    if ev.get("where"):
        q["location"] = ev["where"]
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)


def subscribe_links() -> dict:
    webcal = "webcal://" + FEED.split("://", 1)[1]
    return {"feed": FEED, "webcal": webcal,
            "google": "https://calendar.google.com/calendar/render?cid=" + urllib.parse.quote(webcal, safe=""),
            "outlook": "https://outlook.live.com/calendar/0/addfromweb?url=" + urllib.parse.quote(FEED, safe="")
                       + "&name=" + urllib.parse.quote("Georgia PSC meetings")}


def load_other(path: Path = OTHER) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for x in json.loads(path.read_text() or "[]"):
        if not x.get("date") or not x.get("title"):
            continue
        out.append({**x, "other": True, "kind": "other", "dockets": x.get("dockets") or []})
    return out


def write(out_dir: Path, events: list[dict], agendas: dict, today: str, known: set[str] | None = None) -> list[dict]:
    """Write the feed and one file per meeting from today on. Returns every event, sorted."""
    allev = sorted(events + load_other(), key=lambda x: (x["date"], parse_time(x.get("time")) or (0, 0)))
    (out_dir / "calendar.ics").write_text(calendar(allev, agendas, "Georgia PSC meetings", known), newline="")
    cal = out_dir / "cal"
    cal.mkdir(parents=True, exist_ok=True)
    for ev in allev:
        if ev["date"] >= today:
            (cal / f"{uid_for(ev)}.ics").write_text(
                calendar([ev], agendas, summary_for(ev), known), newline="")
    return allev
