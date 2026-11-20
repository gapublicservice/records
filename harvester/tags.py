"""Tag every filing with the PSC staff unit and committee that handle it, the
places it names, and whether it carries a disagreement.

    python -m harvester.tags        # writes data/index/filings.jsonl and data/index/dockets.json

Unit and committee names are the PSC's own, from its 2025 annual report:
committees Energy, Telecommunications, Facilities Protection and Administrative
Affairs; Utilities Division units Electric, Natural Gas, Telecommunications,
Energy Efficiency and Renewable Energy, and Facilities Protection.

Every tag is a rule applied to what the PSC published (filer, description,
docket, and the filing's text where stored). Each tag carries the rule that
set it, so a reader can see why it is there. Nothing here is a judgment about
who is right.
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from .run import DATA, ROOT, save_json

INDEX = DATA / "index"
TEXT_SCAN_BYTES = 200_000

ELECTRIC, GAS, TELECOM, EERE, FP = (
    "Electric", "Natural Gas", "Telecommunications",
    "Energy Efficiency and Renewable Energy", "Facilities Protection")

COMMITTEE = {
    ELECTRIC: "Energy", GAS: "Energy", EERE: "Energy",
    TELECOM: "Telecommunications", FP: "Facilities Protection",
}

# Dockets the annual report names under a unit.
DOCKET_UNITS = {
    56002: {ELECTRIC, EERE}, 56003: {EERE}, 56298: {ELECTRIC}, 56310: {ELECTRIC},
    55931: {ELECTRIC}, 15326: {GAS}, 12897: {GAS}, 42315: {GAS}, 42959: {GAS},
    56709: {GAS}, 10473: {GAS}, 14675: {GAS}, 18638: {GAS},
}

UNIT_RULES: list[tuple[str, re.Pattern]] = [
    (FP, re.compile(r"pipeline safety|\bGUFPA\b|underground facilit|call before you dig|"
                    r"\bNOPV\b|probable violation|inspection report|damage prevention", re.I)),
    (TELECOM, re.compile(r"telephone|telecom|wireless|broadband|fiber|\bETC\b|lifeline|"
                         r"universal access fund|interconnection|numbering resources|slamming|"
                         r"long distance|\bCLEC\b|hearing aid|communications|\bIXC\b|reseller|\bADAD\b|telcom|"
                         r"Verizon|check sheets?|cross-subsidi|\bVoIP\b|\b911\b|ILEC|CLEC", re.I)),
    (EERE, re.compile(r"renewable|\bDSM\b|demand[- ]side|energy efficiency|solar|\bRFP\b|"
                      r"battery|\bBESS\b|energy storage|distributed generation|net meter|"
                      r"\bPPA\b|power purchase|\bREC\b", re.I)),
    (GAS, re.compile(r"natural gas|\bgas\b|\bLNG\b|marketer|\bGRAM\b|pricing (form|report)|"
                     r"price offer|universal service fund|hedging|Atlanta Gas Light|"
                     r"Liberty Utilities|SCANA|SouthStar|Gas South", re.I)),
    (ELECTRIC, re.compile(r"Georgia Power|Southern Power|\bEMC\b|electric|Oglethorpe Power|"
                          r"\bMEAG\b|territorial|integrated resource plan|\bIRP\b|fuel cost|"
                          r"\bco-?gen|Yates|Vogtle|Plant [A-Z]|certification of", re.I)),
]

# Words in a filing's title that mean one party is contesting another's
# position. Kept to titles: a party's own word for what it is filing.
DISAGREEMENT_RULES: list[tuple[str, re.Pattern]] = [
    ("objection", re.compile(r"\bobjection|\bobjects?\b", re.I)),
    ("opposition", re.compile(r"\bopposition\b|\bopposes?\b|\bin opposition\b", re.I)),
    ("rehearing or reconsideration", re.compile(r"rehearing|reconsideration", re.I)),
    ("complaint", re.compile(r"\bcomplaint\b", re.I)),
    ("protest", re.compile(r"\bprotest\b", re.I)),
    ("exceptions", re.compile(r"\bexceptions?\b to", re.I)),
    ("appeal", re.compile(r"\bappeal\b|petition for (judicial )?review", re.I)),
    ("motion to compel, dismiss or strike", re.compile(r"motion to (compel|dismiss|strike|quash|exclude)", re.I)),
    ("response to another party's motion", re.compile(r"response (to|in) .{0,80}motion", re.I)),
]
# Routine complaint reports are counts, not a party contesting a position.
# The Commission itself rules on disagreements rather than taking a side.
NOT_A_PARTY = {"GPSC"}
NOT_DISAGREEMENT = re.compile(r"slamming complaint|complaint (log|report|summary)|quarterly complaint", re.I)

COUNTIES = """Appling Atkinson Bacon Baker Baldwin Banks Barrow Bartow Ben_Hill Berrien Bibb
Bleckley Brantley Brooks Bryan Bulloch Burke Butts Calhoun Camden Candler Carroll Catoosa
Charlton Chatham Chattahoochee Chattooga Cherokee Clarke Clay Clayton Clinch Cobb Coffee
Colquitt Columbia Cook Coweta Crawford Crisp Dade Dawson Decatur DeKalb Dodge Dooly Dougherty
Douglas Early Echols Effingham Elbert Emanuel Evans Fannin Fayette Floyd Forsyth Franklin Fulton
Gilmer Glascock Glynn Gordon Grady Greene Gwinnett Habersham Hall Hancock Haralson Harris Hart
Heard Henry Houston Irwin Jackson Jasper Jeff_Davis Jefferson Jenkins Johnson Jones Lamar Lanier
Laurens Lee Liberty Lincoln Long Lowndes Lumpkin McDuffie McIntosh Macon Madison Marion
Meriwether Miller Mitchell Monroe Montgomery Morgan Murray Muscogee Newton Oconee Oglethorpe
Paulding Peach Pickens Pierce Pike Polk Pulaski Putnam Quitman Rabun Randolph Richmond Rockdale
Schley Screven Seminole Spalding Stephens Stewart Sumter Talbot Taliaferro Tattnall Taylor
Telfair Terrell Thomas Tift Toombs Towns Treutlen Troup Turner Twiggs Union Upson Walker Walton
Ware Warren Washington Wayne Webster Wheeler White Whitfield Wilcox Wilkes Wilkinson Worth"""
COUNTIES = [c.replace("_", " ") for c in COUNTIES.split()]
assert len(set(COUNTIES)) == 159
COUNTY_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in sorted(COUNTIES, key=len, reverse=True))
                       + r")\s+Count(?:y|ies)\b", re.I)
_CANON = {c.lower(): c for c in COUNTIES}
CITY_FILER_RE = re.compile(r"^(?:City|Town) of ([A-Z][A-Za-z .'-]+?)(?:,|$)")


def counties_in(text: str) -> set[str]:
    return {_CANON[m.group(1).lower()] for m in COUNTY_RE.finditer(text or "")}


def read_text(rec: dict) -> str:
    parts = []
    for att in rec.get("attachments", []):
        tf = att.get("text_file")
        if tf:
            p = ROOT / tf
            if p.exists():
                parts.append(p.read_text(errors="replace")[:TEXT_SCAN_BYTES])
    return "\n".join(parts)


def own_units(rec: dict) -> dict[str, str]:
    """Units this filing's own filer, title or docket points to, with the reason."""
    out: dict[str, str] = {}
    for d in rec.get("dockets", []):
        for u in DOCKET_UNITS.get(d, ()):
            out.setdefault(u, f"docket {d} is listed under this unit in the PSC's 2025 annual report")
    hay = f"{rec.get('company') or ''} | {rec.get('description') or ''}"
    for unit, rx in UNIT_RULES:
        m = rx.search(hay)
        if m and unit not in out:
            out[unit] = f"filer or title says \"{m.group(0)}\""
    if rec.get("company") in ("GUFPA",):
        out.setdefault(FP, "filed under GUFPA")
    return out


def disagreement(rec: dict) -> list[str]:
    title = rec.get("description") or ""
    if NOT_DISAGREEMENT.search(title):
        return []
    return [name for name, rx in DISAGREEMENT_RULES if rx.search(title)]


def places(rec: dict, text: str) -> dict:
    title = f"{rec.get('company') or ''} {rec.get('description') or ''}"
    out = {"counties_in_title": sorted(counties_in(title)),
           "counties_in_text": sorted(counties_in(text) - counties_in(title))}
    m = CITY_FILER_RE.match(rec.get("company") or "")
    if m:
        out["city_filer"] = m.group(1).strip()
    return out


def build() -> tuple[list[dict], dict]:
    recs = []
    for p in sorted((DATA / "filings").glob("*/*.json")):
        try:
            recs.append(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue

    rows = []
    docket_votes: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in recs:
        units = own_units(r)
        if r.get("company") not in ("GPSC", "Staff", None):
            for d in r.get("dockets", []):
                for u in units:
                    docket_votes[d][u] += 1
        rows.append((r, units))

    docket_units: dict[int, list[str]] = {}
    for d, votes in docket_votes.items():
        total = sum(votes.values())
        # A unit counts for the docket when at least a third of its tagged filings point there.
        docket_units[d] = sorted(u for u, n in votes.items() if n * 3 >= total)

    index, dockets = [], collections.defaultdict(lambda: {
        "filings": 0, "disagreement_filings": 0, "disagreeing_filers": set(),
        "counties": collections.Counter(), "units": [], "first": None, "last": None})
    for r, units in rows:
        tags = {u: why for u, why in units.items()}
        if not tags:
            for d in r.get("dockets", []):
                for u in docket_units.get(d, []):
                    tags.setdefault(u, f"most filings on docket {d} are this unit's")
        text = read_text(r)
        dis = disagreement(r)
        pl = places(r, text)
        row = {
            "document_id": r["document_id"], "filed_date": r.get("filed_date"),
            "company": r.get("company"), "dockets": r.get("dockets", []),
            "description": r.get("description"), "url": r.get("url"),
            "units": sorted(tags), "unit_reasons": tags,
            "committees": sorted({COMMITTEE[u] for u in tags if u in COMMITTEE}),
            "disagreement": dis, **pl,
        }
        index.append(row)
        for d in row["dockets"]:
            k = dockets[d]
            k["filings"] += 1
            k["units"] = docket_units.get(d, [])
            if dis:
                k["disagreement_filings"] += 1
                if r.get("company") and r["company"] not in NOT_A_PARTY and not r["company"].startswith("Hearing Officer"):
                    k["disagreeing_filers"].add(r["company"])
            for c in pl["counties_in_title"] + pl["counties_in_text"]:
                k["counties"][c] += 1
            fd = r.get("filed_date")
            if fd and fd >= "1990":
                k["first"] = min(filter(None, [k["first"], fd]))
                k["last"] = max(filter(None, [k["last"], fd]))

    out = {}
    for d, k in sorted(dockets.items()):
        out[str(d)] = {
            "filings": k["filings"], "first_filed": k["first"], "last_filed": k["last"],
            "units": k["units"], "committees": sorted({COMMITTEE[u] for u in k["units"]}),
            "disagreement_filings": k["disagreement_filings"],
            "disagreeing_filers": sorted(k["disagreeing_filers"]),
            # Contested: two or more different filers have each filed a disagreement.
            "contested": len(k["disagreeing_filers"]) >= 2,
            "counties": dict(k["counties"].most_common(15)),
        }
    return index, out


def main() -> int:
    index, dockets = build()
    INDEX.mkdir(parents=True, exist_ok=True)
    with (INDEX / "filings.jsonl").open("w") as fh:
        for row in sorted(index, key=lambda r: r["document_id"]):
            fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    save_json(INDEX / "dockets.json", dockets)
    print(f"{len(index)} filings, {len(dockets)} dockets tagged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
