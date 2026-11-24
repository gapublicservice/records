"""What each docket is: a short explainer at the top of its docket page.

    python -m harvester.explainers --check    # list entries and whether each is shown

Entries live in data/reference/explainers.json, in our own words, each with the
filings it rests on. An entry is shown only once it carries "approved": true and
the date it was approved, so nothing goes on the site before a person has read it.
An explainer says what the proceeding is and what it covers. It is not a judgment
about any party's position.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "data" / "reference" / "explainers.json"
PSC_DOC = "https://psc.ga.gov/search/facts-document/?documentId="
e = html.escape

CATEGORIES = ("Rate case", "Fuel", "Integrated resource plan", "Certification", "Request for proposals",
              "Tariff or rule change", "Complaint or petition", "Reports and compliance", "Telecommunications",
              "Utility facility protection", "Pipeline safety", "Other")

NOTE = ("Written by Public Service Records from the docket's own filings and orders. "
        "The Commission's record is the one to rely on.")


def load(path: Path = FILE) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("explainers", [])


def shown(x: dict) -> bool:
    return bool(x.get("approved") and x.get("approved_on") and x.get("text"))


def for_docket(d, entries: list[dict] | None = None) -> dict | None:
    entries = load() if entries is None else entries
    return next((x for x in entries if str(d) in {str(k) for k in x.get("dockets", [])} and shown(x)), None)


def block(d, entries: list[dict] | None = None) -> str:
    """The explainer section for a docket page, or "" if none is approved."""
    x = for_docket(d, entries)
    if not x:
        return ""
    cat = x.get("category") or "Other"
    parts = [f'<section class="ps-exp"><div class="kicker">{e(cat)}</div><p>{e(x["text"])}</p>']
    if x.get("scope_contested"):
        parts.append(f'<p>{e(x["scope_contested"])}</p>')
    src = x.get("sources") or []
    if src:
        links = ", ".join(f'<a href="{PSC_DOC}{int(s["document_id"])}" target="_blank" rel="noopener">'
                          f'{e(s.get("label") or str(s["document_id"]))}</a>' for s in src)
        parts.append(f'<p class="muted">Sources: {links}.</p>')
    parts.append(f'<p class="muted">{e(NOTE)} Checked {e(x["approved_on"])}.</p></section>')
    return "".join(parts)


STYLE = ('<style>.ps-exp{border-left:3px solid #E8A317;padding:2px 0 2px 14px;margin:18px 0 24px}'
         '.ps-exp p{margin:6px 0}</style>')


def main(argv: list[str]) -> int:
    if "--check" in argv:
        for x in load():
            print(", ".join(map(str, x.get("dockets", []))), "|", x.get("category"), "|",
                  "shown" if shown(x) else "held")
            if x.get("category") not in CATEGORIES:
                print("  unknown category:", x.get("category"))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
