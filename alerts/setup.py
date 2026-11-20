"""One-off Ghost setup for Follow a docket, run by hand from GitHub Actions.

  python -m alerts.setup newsletter   add the "Docket alerts" newsletter if it
                                      isn't there. Existing members are not
                                      subscribed to it, and new sign-ups aren't
                                      either: following a docket adds it.
  python -m alerts.setup page --api URL [--publish]
                                      add or update the page at /follow/ with
                                      the follow page from follow/follow-page.html
  python -m alerts.setup darklogo [--apply]
                                      show the theme's "Logo for dark mode"
                                      setting; with --apply, upload the white
                                      logo and set it there (only if it's empty)

Prints ids and the admin host only, never the key or member addresses.
"""
from __future__ import annotations

import argparse
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from alerts.ghost import API, Ghost, token

NAME = "Docket alerts"
DESCRIPTION = ("A short email the morning after new filings land in a docket you follow "
               "on Public Service.")
PAGE_SLUG = "follow"
PAGE_TITLE = "Follow a docket"
PAGE_FILE = Path(__file__).resolve().parent.parent / "follow" / "follow-page.html"
DARK_KEY = "logo_for_dark_mode"
DARK_LOGO = Path(__file__).resolve().parent.parent / "site" / "brand" / "public-service-logo-white-1200.png"


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


def upload_image(g: Ghost, path: Path) -> str:
    boundary = uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
        b"Content-Type: image/png\r\n\r\n", path.read_bytes(), b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="purpose"\r\n\r\nimage\r\n',
        f"--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(f"{g.url}{API}/images/upload/", method="POST", data=body, headers={
        "Authorization": f"Ghost {token(g.key)}", "Accept-Version": "v6.0",
        "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            import json
            return json.loads(r.read())["images"][0]["url"]
    except urllib.error.HTTPError as err:
        raise SystemExit(f"Ghost said {err.code} to the image upload: {err.read().decode(errors='replace')[:300]}")


def darklogo(g: Ghost, apply: bool) -> None:
    settings = g.call("GET", "/custom_theme_settings/")["custom_theme_settings"]
    have = next((x for x in settings if x["key"] == DARK_KEY), None)
    if have is None:
        raise SystemExit(f"the active theme has no '{DARK_KEY}' setting")
    print(f"{DARK_KEY} now: {have.get('value')!r}")
    if not apply:
        return
    if have.get("value") and DARK_LOGO.stem not in have["value"]:
        raise SystemExit("already set to another image; left as it is")
    url = upload_image(g, DARK_LOGO)
    print(f"uploaded: {url}")
    out = [{"key": x["key"], "value": (url if x["key"] == DARK_KEY else x.get("value"))} for x in settings]
    done = g.call("PUT", "/custom_theme_settings/", {"custom_theme_settings": out})["custom_theme_settings"]
    print(f"{DARK_KEY} set: {next(x for x in done if x['key'] == DARK_KEY).get('value')!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["newsletter", "page", "darklogo"])
    ap.add_argument("--api", default="")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    g = Ghost()
    if a.what == "newsletter":
        newsletter(g)
    elif a.what == "darklogo":
        darklogo(g, a.apply)
    else:
        page(g, a.api, a.publish)


if __name__ == "__main__":
    main()
