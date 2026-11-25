"""Ghost's primary menu, for the bar at the top of every Records page.

Ghost is the one list: the Records build reads the menu from Ghost's Admin
API each time it runs, so a change in Ghost Admin > Settings > Navigation
shows up on Records at the next build. If Ghost can't be read (no key, an
error), the copy last saved in the repo is used instead.

    python -m alerts.nav            # fetch and write data/reference/ghost-nav.json

Only labels and links are kept. The key comes from GHOST_ADMIN_KEY and is
never printed.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.parse
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "reference" / "ghost-nav.json"
SITE = "https://www.gapublicservice.org"


def clean(items: list, site: str = SITE) -> list[dict]:
    """Labels and absolute https links only; anything else is dropped."""
    out = []
    for it in items or []:
        label = " ".join(str(it.get("label") or "").split())[:40]
        url = str(it.get("url") or "").strip()
        # The theme shows an item whose label starts with "-" as a dropdown
        # entry under the item before it.
        child = label.startswith("-")
        label = label.lstrip("- ").strip()
        if not label or not url:
            continue
        if url.startswith("/"):
            url = site + url
        u = urllib.parse.urlsplit(url)
        if u.scheme != "https" or not u.hostname:
            continue
        out.append({"label": label, "url": url, **({"child": True} if child else {})})
    return out


def from_settings(settings: list[dict]) -> dict:
    vals = {s.get("key"): s.get("value") for s in settings}

    def menu(key: str) -> list:
        v = vals.get(key)
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                v = []
        return v or []

    site = (vals.get("url") or SITE).rstrip("/")
    if not site.startswith("https://"):
        site = SITE
    return {"site": site,
            "title": " ".join(str(vals.get("title") or "Public Service").split()),
            "primary": clean(menu("navigation"), site),
            "secondary": clean(menu("secondary_navigation"), site)}


def main() -> int:
    if not os.environ.get("GHOST_ADMIN_KEY"):
        print("No Ghost key here; keeping the saved menu.")
        return 0
    from alerts.ghost import Ghost
    got = Ghost().call("GET", "/settings/")
    nav = from_settings(got.get("settings", []))
    if not nav["primary"]:
        print("Ghost returned no primary menu; keeping the saved menu.")
        return 0
    nav["fetched"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    OUT.write_text(json.dumps(nav, indent=2) + "\n")
    print("Ghost menu:", " · ".join(f'{i["label"]} -> {i["url"]}' for i in nav["primary"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
