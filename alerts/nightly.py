"""Nightly docket alerts: email each followed docket's new filings to its followers.

    python -m alerts.nightly             # tonight's new filings
    python -m alerts.nightly --dry-run   # count what would go out, send nothing

Runs at the end of the nightly harvest. It sends only when a docket has new
filings tonight and at least one follower. On a night with no new filings,
or none in a docket you follow, nobody gets an email.

How a follow works: the Follow button adds the Ghost label "Docket NNNNN" to the
member and subscribes them to the "Docket alerts" newsletter. Each docket with
new filings gets one email-only post sent to that label, so a member who
follows three busy dockets gets three short emails that morning.

A post with the same title already published (a rerun of the same night) is not
sent again. The log prints docket numbers and counts only, never addresses.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = "https://records.gapublicservice.org"
NEWSLETTER = "Docket alerts"
MAX_LISTED = 25

# Set to False to stop every alert without touching the workflow.
ENABLED = True


def new_filings(day: str) -> list[dict]:
    log = DATA / "daily" / f"{day}.json"
    if not log.exists():
        return []
    out = []
    for doc in json.loads(log.read_text()):
        for p in (DATA / "filings").glob(f"*/{doc}.json"):
            out.append(json.loads(p.read_text()))
    return out


def by_docket(filings: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for f in filings:
        for d in f.get("dockets") or []:
            groups[str(d)].append(f)
    for v in groups.values():
        v.sort(key=lambda r: r.get("document_id") or 0)
    return dict(groups)


def docket_name(docket: str) -> str | None:
    p = DATA / "dockets" / f"{docket}.json"
    if not p.exists():
        return None
    return (json.loads(p.read_text()).get("title") or "").strip() or None


def nice_day(day: str) -> str:
    d = dt.date.fromisoformat(day)
    return f"{d:%B} {d.day}, {d.year}"


def title_for(docket: str, n: int, day: str) -> str:
    return f"Docket {docket}: {n} new filing{'s' if n != 1 else ''}, {nice_day(day)}"


def email_html(docket: str, filings: list[dict], name: str | None) -> str:
    e = html.escape
    page = f"{SITE}/docket/{docket}/"
    head = f"<p><strong>Docket {e(docket)}</strong>" + (f": {e(name)}" if name else "") + "</p>"
    items = []
    for f in filings[:MAX_LISTED]:
        who = (f.get("company") or "").strip()
        what = (f.get("description") or "Filing").strip()
        link = f.get("url") or f"https://psc.ga.gov/search/facts-document/?documentId={f.get('document_id')}"
        items.append(f'<li><a href="{e(link)}">{e(what)}</a>'
                     + (f"<br>{e(who)}" if who and who not in what else "")
                     + (f" · filed {e(f['filed_date'])}" if f.get("filed_date") else "") + "</li>")
    more = len(filings) - MAX_LISTED
    tail = f'<p>And {more} more on the <a href="{page}">docket page</a>.</p>' if more > 0 else ""
    return (f"{head}<p>New at the Commission since yesterday:</p><ul>{''.join(items)}</ul>{tail}"
            f'<p><a href="{page}">See every filing in this docket on the record</a></p>'
            "<p>We copy the Commission's site each night at about 3 AM Eastern, so this lists what "
            "the Commission posted by then. The Commission's own page is the one to rely on.</p>"
            f'<p>You get this because you follow this docket. To stop, press Following · stop on '
            f'<a href="https://www.gapublicservice.org/follow/?docket={e(docket)}">this docket\'s Follow page</a>, '
            'or unsubscribe from Docket alerts below.</p>'
            "<p>Public Service is an independent project, not a product of the Georgia Public "
            "Service Commission.</p>")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.datetime.now(dt.timezone.utc).date().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not ENABLED:
        print("Docket alerts are switched off (ENABLED = False). Nothing sent.")
        return
    groups = by_docket(new_filings(a.date))
    if not groups:
        print(f"No new filings for {a.date}. No alerts sent.")
        return
    print(f"{sum(len(v) for v in groups.values())} filing-docket pairs in {len(groups)} dockets tonight")

    from .ghost import Ghost
    g = Ghost()
    nl = next((n for n in g.call("GET", "/newsletters/", limit="all", filter="status:active")["newsletters"]
               if n["name"].strip().lower() == NEWSLETTER.lower()), None)
    if not nl:
        sys.exit(f"No active '{NEWSLETTER}' newsletter in Ghost. Nothing sent.")
    sent_titles = {p["title"] for p in g.call("GET", "/posts/", filter="status:published", order="published_at desc",
                                               limit=200, fields="id,title")["posts"]}
    sent = skipped = 0
    for docket, filings in sorted(groups.items()):
        slug = f"docket-{docket}"
        reach = g.call("GET", "/members/", filter=f"label:{slug}+newsletters.id:'{nl['id']}'+email_disabled:0",
                       limit=1)["meta"]["pagination"]["total"]
        if not reach:
            continue
        title = title_for(docket, len(filings), a.date)
        if title in sent_titles:
            print(f"Docket {docket}: already sent tonight, skipped")
            skipped += 1
            continue
        if a.dry_run:
            print(f"Docket {docket}: would email {reach} follower(s) about {len(filings)} filing(s)")
            continue
        post = g.call("POST", "/posts/", {"posts": [{"title": title, "status": "draft", "email_only": True,
                                                     "html": email_html(docket, filings, docket_name(docket))}]},
                      source="html")["posts"][0]
        g.call("PUT", f"/posts/{post['id']}/", {"posts": [{"status": "published", "updated_at": post["updated_at"]}]},
               newsletter=nl["slug"], email_segment=f"label:{slug}")
        status = "pending"
        for _ in range(8):
            em = g.call("GET", f"/posts/{post['id']}/", include="email")["posts"][0].get("email") or {}
            status = em.get("status") or status
            if status in ("submitted", "failed"):
                break
            time.sleep(15)
        print(f"Docket {docket}: {len(filings)} filing(s) to {reach} follower(s); email status {status}")
        sent += 1
    print(f"Done: {sent} alert email(s) sent, {skipped} already sent. Dockets with no followers got none.")


if __name__ == "__main__":
    main()
