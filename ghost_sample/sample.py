"""Sample copy for the gapublicservice.org home page, run by hand from Actions.

  python -m ghost_sample.sample apply    add the "Start here" lead post with the
                                         Public Service banner, six sample posts
                                         (internal tag #sample), the About excerpt,
                                         and set Ghost's "Coming soon" post to draft
  python -m ghost_sample.sample remove   delete the sample posts and put the
                                         "Coming soon" post and About excerpt back

Nothing here sends email: posts are published without a newsletter, so Ghost
emails no one. Prints ids, slugs and image addresses only, never the key.
Every sample post says it is a sample; none states a position or names anyone.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import mimetypes
import urllib.request
import uuid
from pathlib import Path

from alerts.ghost import API, Ghost, token

HERE = Path(__file__).resolve().parent
RECORDS = "https://records.gapublicservice.org"
SITE = "https://www.gapublicservice.org"
SAMPLE_TAG = {"name": "#sample"}
NOTE = ("<p><em>This is a sample post, here so the home page shows its real layout. "
        "It is not a published story and comes down before launch.</em></p>")
ABOUT_EXCERPT = ("The Georgia Public Service Commission, on the record: sessions, dockets, "
                 "votes and the filings behind them.")


def card(html: str) -> str:
    return f"<!--kg-card-begin: html-->\n{html}\n<!--kg-card-end: html-->"


START_HTML = card(f"""<p><em>Placeholder text. Paul writes this page before launch.</em></p>
<p>Public Service keeps a record of the Georgia Public Service Commission. Here is what is on the site today.</p>
<ul>
<li><a href="{RECORDS}/" target="_blank" rel="noopener">Records</a>: every docket, with filings copied from the Commission's site each night.</li>
<li><a href="{RECORDS}/calendar.html" target="_blank" rel="noopener">Calendar</a>: upcoming sessions, committees and hearings, with agendas and add-to-calendar buttons.</li>
<li><a href="{SITE}/follow/">Follow a docket</a>: an email the morning after anything new is filed in a docket you pick.</li>
<li><a href="#/portal/signup">Subscribe</a>: session records and explainers by email.</li>
</ul>
<p>Public Service is an independent project. It is not a product or publication of the Georgia Public Service Commission.</p>""")

SAMPLES = [
    ("sample-session-record", "Sample session record: how each write-up is laid out", "Sessions", f"""{NOTE}
<p><strong>Session:</strong> [type] · <strong>Dockets:</strong> [numbers] · <strong>Votes:</strong> [count] · <strong>Next:</strong> [date]</p>
<blockquote>[The short version: what the Commission voted on, in two sentences.]</blockquote>
<h3>Votes</h3><p>[A table of each item, the result and who voted against.]</p>
<h3>Dates ahead</h3><p>[Deadlines and hearings in the dockets that came up.]</p>
<h3>Record</h3><p>[Links to the docket pages, the Commission's calendar page and the session video.]</p>"""),
    ("sample-docket-explainer", "Sample docket explainer: what a docket page holds", "Dockets", f"""{NOTE}
<p>[What the docket is about, in plain words.]</p><h3>Where it stands</h3><p>[The latest filing and the next date.]</p>
<h3>Key filings</h3><p>[Links into the <a href="{RECORDS}/" target="_blank" rel="noopener">records site</a>.]</p>"""),
    ("sample-reading-an-agenda", "Sample explainer: how to read a Commission agenda", "Explainers", f"""{NOTE}
<p>[What each part of an agenda means and where to find the documents behind each item.]</p>"""),
    ("sample-records-release", "Sample records release: this week's new filings", "Records", f"""{NOTE}
<p>[A short list of the week's notable filings, each linked to its docket page.] The full list is on the <a href="{RECORDS}/" target="_blank" rel="noopener">records site</a>.</p>"""),
    ("sample-docket-calendar", "Sample: the docket calendar, December to January", "Dockets", f"""{NOTE}
<p>[Hearings and deadlines over the next two months.] The live version is the <a href="{RECORDS}/calendar.html" target="_blank" rel="noopener">calendar</a>.</p>"""),
    ("sample-glossary", "Sample glossary: terms you'll see in filings", "Explainers", f"""{NOTE}
<p>[Short definitions of terms that come up in Commission filings.]</p>"""),
]


def upload(g: Ghost, path: Path) -> str:
    g.call("GET", "/site/")  # settle on the admin host before a multipart post
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode() + path.read_bytes() + (
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nimage"
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"ref\"\r\n\r\n{path.name}"
            f"\r\n--{boundary}--\r\n").encode()
    req = urllib.request.Request(f"{g.url}{API}/images/upload/", method="POST", data=body, headers={
        "Authorization": f"Ghost {token(g.key)}", "Accept-Version": "v6.0",
        "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        url = json.loads(r.read())["images"][0]["url"]
    print(f"image: {path.name} -> {url}")
    return url


def find(g: Ghost, kind: str, slug: str) -> dict | None:
    got = g.call("GET", f"/{kind}/", filter=f"slug:{slug}")[kind]
    return got[0] if got else None


def put(g: Ghost, kind: str, slug: str, fields: dict) -> None:
    have = find(g, kind, slug)
    body = dict(fields, slug=slug)
    if have:
        body["updated_at"] = have["updated_at"]
        out = g.call("PUT", f"/{kind}/{have['id']}/", {kind: [body]}, source="html")[kind][0]
    else:
        out = g.call("POST", f"/{kind}/", {kind: [body]}, source="html")[kind][0]
    print(f"{kind[:-1]}: slug={out['slug']} status={out['status']} featured={out.get('featured')}")


def edit(g: Ghost, kind: str, slug: str, fields: dict) -> None:
    have = find(g, kind, slug)
    if not have:
        print(f"{kind[:-1]} {slug}: not found, skipped")
        return
    out = g.call("PUT", f"/{kind}/{have['id']}/", {kind: [dict(fields, updated_at=have["updated_at"])]})[kind][0]
    print(f"{kind[:-1]}: slug={out['slug']} status={out['status']}")


def apply(g: Ghost) -> None:
    light = upload(g, HERE / "public-service-lead-light.png")
    upload(g, HERE / "public-service-lead-dark.png")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    for i, (slug, title, tag, html) in enumerate(SAMPLES):
        put(g, "posts", slug, {"title": title, "html": card(html), "status": "published",
                               "published_at": (now - dt.timedelta(hours=i + 1)).isoformat().replace("+00:00", "Z"),
                               "custom_excerpt": "Sample post to show the layout. Not a published story.",
                               "tags": [{"name": tag}, SAMPLE_TAG]})
    put(g, "posts", "start-here", {
        "title": "Start here", "html": START_HTML, "status": "published", "featured": True,
        "published_at": now.isoformat().replace("+00:00", "Z"),
        "custom_excerpt": "How to use Public Service: session records, the docket library, the calendar and docket alerts.",
        "feature_image": light,
        "feature_image_alt": "Public Service wordmark with a grain sun above it",
        "tags": [SAMPLE_TAG]})
    edit(g, "posts", "coming-soon", {"status": "draft"})
    edit(g, "pages", "about", {"custom_excerpt": ABOUT_EXCERPT})


def remove(g: Ghost) -> None:
    for slug in [s[0] for s in SAMPLES] + ["start-here"]:
        have = find(g, "posts", slug)
        if have:
            g.call("DELETE", f"/posts/{have['id']}/")
            print(f"deleted post: {slug}")
    edit(g, "posts", "coming-soon", {"status": "published"})
    edit(g, "pages", "about", {"custom_excerpt": None})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["apply", "remove"])
    a = ap.parse_args()
    g = Ghost()
    apply(g) if a.what == "apply" else remove(g)


if __name__ == "__main__":
    main()
