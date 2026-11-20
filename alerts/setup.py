"""One-off Ghost setup for Follow a docket, run by hand from GitHub Actions.

  python -m alerts.setup newsletter   add the "Docket alerts" newsletter if it
                                      isn't there. Existing members are not
                                      subscribed to it, and new sign-ups aren't
                                      either: following a docket adds it.
  python -m alerts.setup page --api URL [--publish]
                                      add or update the page at /follow/ with
                                      the follow page from follow/follow-page.html

Prints ids and the admin host only, never the key or member addresses.
"""
from __future__ import annotations

import argparse
import re
import urllib.parse
from pathlib import Path

from alerts.ghost import Ghost

NAME = "Docket alerts"
DESCRIPTION = ("A short email the morning after new filings land in a docket you follow "
               "on Public Service.")
PAGE_SLUG = "follow"
PAGE_TITLE = "Follow a docket"
PAGE_FILE = Path(__file__).resolve().parent.parent / "follow" / "follow-page.html"


def newsletter(g: Ghost) -> None:
    found = g.call("GET", "/newsletters/", limit="all", filter="status:active")["newsletters"]
    for n in found:
        print(f"newsletter: {n['name']} id={n['id']} status={n['status']}")
    have = next((n for n in found if n["name"].strip().lower() == NAME.lower()), None)
    if have:
        print(f"'{NAME}' already exists: id={have['id']}")
    else:
        made = g.call("POST", "/newsletters/", {"newsletters": [{
            "name": NAME, "description": DESCRIPTION, "status": "active",
            "subscribe_on_signup": False, "visibility": "members",
        }]}, opt_in_existing="false")["newsletters"][0]
        print(f"made '{NAME}': id={made['id']}")
    print(f"admin host: {urllib.parse.urlsplit(g.url).hostname}")


def page_html(api: str) -> str:
    html = PAGE_FILE.read_text()
    html = re.sub(r"<!--.*?-->\s*", "", html, count=1, flags=re.S)  # drop the build note
    html, n = re.subn(r'var API = "";', f'var API = "{api}";', html)
    if n != 1:
        raise SystemExit("could not set the service address in the page")
    return f"<!--kg-card-begin: html-->\n{html}\n<!--kg-card-end: html-->"


def page(g: Ghost, api: str, publish: bool) -> None:
    if not re.fullmatch(r"https://[a-z0-9.-]+\.netlify\.app/follow", api):
        raise SystemExit("the service address must be the Netlify follow address")
    body = {"title": PAGE_TITLE, "slug": PAGE_SLUG, "html": page_html(api),
            "status": "published" if publish else "draft",
            "custom_excerpt": "Get an email when anything new is filed in a Commission docket."}
    found = g.call("GET", "/pages/", filter=f"slug:{PAGE_SLUG}", formats="html")["pages"]
    if found:
        body["updated_at"] = found[0]["updated_at"]
        out = g.call("PUT", f"/pages/{found[0]['id']}/", {"pages": [body]}, source="html")["pages"][0]
    else:
        out = g.call("POST", "/pages/", {"pages": [body]}, source="html")["pages"][0]
    print(f"page: id={out['id']} slug={out['slug']} status={out['status']} url={out.get('url')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["newsletter", "page"])
    ap.add_argument("--api", default="")
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args()
    g = Ghost()
    if a.what == "newsletter":
        newsletter(g)
    else:
        page(g, a.api, a.publish)


if __name__ == "__main__":
    main()
