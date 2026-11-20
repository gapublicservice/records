"""Save a copy of each public source an expert view quotes, so the quote can be
checked against it and anyone can confirm the copy matches the original.

    python -m legis.sources save <https url> --id <short id>

data/legislature/sources/<id>.txt   the source's text
data/legislature/sources/<id>.json  address, when fetched, SHA-256 of the bytes fetched
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys

from . import store, textdiff
from .run import fetch
from .views import SOURCES


def html_text(raw: bytes) -> str:
    s = raw.decode("utf-8", "replace")
    s = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", s)).strip() + "\n"


def save(url: str, sid: str) -> dict:
    if not url.startswith("https://"):
        raise SystemExit("A cited source must be a public https address.")
    data = fetch(url)
    text = textdiff.pdf_text(data) if data[:5] == b"%PDF-" else html_text(data)
    SOURCES.mkdir(parents=True, exist_ok=True)
    (SOURCES / f"{sid}.txt").write_text(text)
    meta = {"id": sid, "url": url, "fetched": store.now(), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "kind": "pdf" if data[:5] == b"%PDF-" else "html"}
    store.write_json(SOURCES / f"{sid}.json", meta)
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save"); s.add_argument("url"); s.add_argument("--id", required=True)
    a = ap.parse_args(argv)
    print(json.dumps(save(a.url, a.id), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
