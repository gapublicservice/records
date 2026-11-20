"""Collect the Commission calendar: hearings, sessions and committee meetings.

    python -m harvester.calendar

The calendar page at psc.ga.gov lists every event as a link whose address ends
in ?date=<unix time>. We keep the title, the Eastern date and time, the kind of
event and any docket numbers in the title, in data/index/calendar.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import re

from .psc import Fetcher
from .run import DATA, save_json

BASE = "https://psc.ga.gov"
CALENDAR_URL = BASE + "/agendas-calendars/commission-calendar/"
OUT = DATA / "index" / "calendar.json"

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - runner without tz data
    EASTERN = dt.timezone(dt.timedelta(hours=-5))

_LINK = re.compile(
    r'<a\b[^>]*href="((?:https://psc\.ga\.gov)?/agendas-calendars/commission-calendar/'
    r'([a-z0-9.\-]+)/\?date=(\d{9,11}))"[^>]*>(.*?)</a>', re.S | re.I)
_DOCKET = re.compile(r"(?<!\d)(\d{5})(?!\d)")


def kind_of(title: str) -> str:
    t = title.lower()
    if "hearing" in t or "rule nisi" in t:
        return "hearing"
    if "administrative session" in t:
        return "session"
    if "committee" in t:
        return "committee"
    if _DOCKET.search(t):
        return "docket"
    if "forum" in t:
        return "forum"
    if "working group" in t or "dsm" in t:
        return "working group"
    return "other"


def title_from_slug(slug: str) -> str:
    s = re.sub(r"-\d{1,2}-\d{1,2}-\d{2,4}$", "", slug)
    s = re.sub(r"-\d{1,2}$", "", s)
    return s.replace("-", " ").strip().capitalize()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def parse(page: str) -> list[dict]:
    """Every event on the calendar page, one record per address."""
    events: dict[str, dict] = {}
    for href, slug, stamp, text in _LINK.findall(page):
        url = href if href.startswith("http") else BASE + href
        when = dt.datetime.fromtimestamp(int(stamp), dt.timezone.utc).astimezone(EASTERN)
        text = _clean(text)
        rec = events.get(url)
        if rec is None:
            rec = events[url] = {
                "url": url,
                "date": when.date().isoformat(),
                "time": when.strftime("%-I:%M %p"),
                "title": title_from_slug(slug),
            }
        if len(text) > 8 and (rec.get("_from_text") is None or len(text) > len(rec["title"])):
            rec["title"], rec["_from_text"] = text, True
    out = []
    for rec in events.values():
        rec.pop("_from_text", None)
        rec["kind"] = kind_of(rec["title"] + " " + rec["url"])
        rec["dockets"] = sorted({int(d) for d in _DOCKET.findall(rec["title"] + " " + rec["url"])
                                 if 10000 <= int(d) <= 99999})
        out.append(rec)
    return sorted(out, key=lambda r: (r["date"], r["time"], r["title"]))


def upcoming(events: list[dict], today: str, kinds=("hearing", "docket"), limit: int = 12) -> list[dict]:
    return [e for e in events if e["date"] >= today and e["kind"] in kinds][:limit]


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    page = Fetcher().get(CALENDAR_URL).decode("utf-8", "replace")
    events = parse(page)
    if not events:
        print("No events found on the calendar page; keeping the last copy.")
        return 0
    save_json(OUT, {"source": CALENDAR_URL,
                    "checked": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    "events": events})
    today = dt.datetime.now(EASTERN).date().isoformat()
    print(f"{len(events)} calendar events; upcoming hearings: {len(upcoming(events, today))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
