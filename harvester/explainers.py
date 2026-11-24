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


# The "not reviewed" line for dockets with no approved explainer. Off until approved.
AUTO_ON = False
AUTO_NOTE = "From the Commission's docket listing, not reviewed."
_RULES = [("Rate case", r"\brate case\b|general rate|base rate"),
          ("Fuel", r"fuel|gas supply|capacity supply|purchased gas|\bpga\b"),
          ("Integrated resource plan", r"integrated resource|\birp\b|integrated capacity and delivery"),
          ("Request for proposals", r"request for proposals|\brfps?\b|solicitation"),
          ("Certification", r"certif|certificate of authority"),
          ("Complaint or petition", r"complaint|petition|declaratory|\bv\.? "),
          ("Tariff or rule change", r"tariff|\brules?\b|rulemaking|rider|rate schedule"),
          ("Reports and compliance", r"report|monitoring|surveillance|compliance|audit")]


def auto_category(title: str, industry: str) -> str:
    import re
    ind = (industry or "").lower()
    if "gufpa" in ind:
        return "Utility facility protection"
    if ind.startswith("pipeline safety"):
        return "Pipeline safety"
    if ind.startswith("telecommunications"):
        return "Telecommunications"
    t = (title or "").lower()
    return next((c for c, r in _RULES if re.search(r, t)), "Other")


# Opened dates the Commission's listing gives to hundreds of dockets at once (431, 72 and 73 dockets),
# which look like the dates records moved into its system, not when a case began. Left out.
BULK_DATES = {"2011-12-18", "2013-05-07", "2019-06-29"}
FILER = {"GPSC": "the Commission", "Staff": "Commission Staff"}


def _date(iso: str) -> str:
    import datetime as dt
    try:
        d = dt.date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return f"{d:%b} {d.day}, {d.year}"


def auto_block(meta: dict | None, first: dict | None) -> str:
    """One labeled line built only from the Commission's own listing and our first stored filing."""
    if not AUTO_ON or not meta:
        return ""
    cat = auto_category(meta.get("title") or "", meta.get("industry") or "")
    bits = []
    if meta.get("date") and meta["date"] not in BULK_DATES:
        bits.append(f"Opened {_date(meta['date'])}")
    if meta.get("status"):
        bits.append(f"status {meta['status'].lower()} on the Commission's site")
    line = (", ".join(bits) + ".") if bits else ""
    line = line[:1].upper() + line[1:]
    if first and first.get("company"):
        who = FILER.get(first["company"].strip(), first["company"].strip())
        when = _date(first["filed_date"]) if first.get("filed_date") else "date not given"
        line += f" Earliest filing in this record: {who}, {when}."
    return (f'<section class="ps-exp ps-auto"><div class="kicker">{e(cat)}</div><p>{e(line.strip())}</p>'
            f'<p class="muted">{e(AUTO_NOTE)}</p></section>')


STYLE = ('<style>.ps-exp{border-left:3px solid #E8A317;padding:2px 0 2px 14px;margin:18px 0 24px}'
         '.ps-exp p{margin:6px 0}.ps-auto{border-left-color:#bbb}</style>')


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
