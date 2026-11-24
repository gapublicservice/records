"""Law tags: which Georgia utility laws and Commission rules a filing cites, and
what kind of proceeding a docket is.

Both are rules applied to what the Commission published. A law tag is set only
when a filing's title or stored text cites a section of the Official Code of
Georgia (O.C.G.A.) or a Commission rule by number, and the tag carries the
section that set it. A proceeding tag is set from the docket's own title on the
Commission's site. Neither says what a filing argues or whether it is right.

Procedural citations (Staff discovery, intervention, trade-secret handling,
notice, contested-case procedure, open records) appear in so many filings that
they would tag almost everything, so they are counted as procedural and not
shown as tags.

Corrections Paul makes in his weekly check go in
data/reference/legal_tag_fixes.json and win over the rules.
"""

from __future__ import annotations

import json
import re

from .run import DATA

FIXES = DATA / "reference" / "legal_tag_fixes.json"

# Free text of the Code. Section pages are linked, never copied.
CODE_BASE = "https://law.justia.com/codes/georgia/title-46/"

# An O.C.G.A. section anywhere in the text: title 46 (utilities) on its own,
# other titles only next to a citation marker. Phone numbers, docket numbers
# and dates don't take this shape.
_SEC = r"(?<![\w.-])((?:46|50|10)-\d{1,2}[A-Z]?-\d{1,3}(?:\.\d{1,2})?)(?![\w-]|\.\d)"
SECTION = re.compile(_SEC)
MARKER = re.compile(r"O\.?\s?C\.?\s?G\.?\s?A\.?|§|Code Section|Ga\.? Code", re.I)
# Commission rules: 515-3-4-.04, sometimes written 515-3-4.04 or 515-3-4-04 is
# not accepted (too close to phone numbers).
RULE = re.compile(r"(?<![\w.-])515-(\d{1,2})-(\d{1,2})-?\.(\d{2})(?!\d)")

PROCEDURAL_SECTIONS = {"46-2-57", "46-2-59", "46-2-33", "10-1-760"}
PROCEDURAL_PREFIXES = ("50-13-", "50-18-")
PROCEDURAL_RULES = {"515-3-1-.11", "515-1-1-.02"}
PROCEDURAL_RULE_PREFIXES = ("515-2-1-",)


def _sec_parts(s: str) -> tuple[str, str, str]:
    t, c, n = s.split("-", 2)
    return t, c, n


def _num(n: str) -> float:
    try:
        return float(n)
    except ValueError:
        return -1


# (tag, test on a normalized citation). Each group is a law or rule set the
# record cites often enough to be worth a tag.
LAWS: list[tuple[str, callable]] = [
    ("Integrated Resource Planning Act", lambda s: s.startswith("46-3A-")),
    ("IRP and RFP rules", lambda s: s.startswith("515-3-4-")),
    ("Territorial Electric Service Act",
     lambda s: s.startswith("46-3-") and 1 <= _num(s.split("-")[2]) <= 15),
    ("Cogeneration and Distributed Generation Act",
     lambda s: s.startswith("46-3-") and 50 <= _num(s.split("-")[2]) < 60),
    ("Fuel cost recovery law", lambda s: s == "46-2-26"),
    ("Rate-setting law", lambda s: s in {"46-2-25", "46-2-26.1"}),
    ("Commission powers", lambda s: s in {"46-2-20", "46-2-21", "46-2-23"}),
    ("Penalties", lambda s: s == "46-2-91"),
    ("Automatic dialing permits", lambda s: s == "46-5-23"),
    # Chapters of the Commission's rules, named as the record's own docket
    # titles name them (gas, telecommunications, facility protection).
    ("Gas rules", lambda s: s.startswith("515-7-")),
    ("Telecommunications rules", lambda s: s.startswith("515-12-")),
    ("Facility protection rules", lambda s: s.startswith("515-9-")),
]
LAW_NAMES = [n for n, _ in LAWS]

# Proceeding types, from the docket's own title.
PROCEEDINGS: list[tuple[str, re.Pattern]] = [
    ("Rate case", re.compile(r"rate case|general rate|alternate rate plan", re.I)),
    ("Fuel cost recovery", re.compile(r"fuel cost recovery", re.I)),
    ("Integrated resource plan", re.compile(r"integrated resource plan|\bIRP\b", re.I)),
    ("Request for proposals", re.compile(r"request for proposals?|\bRFPs?\b", re.I)),
    ("Certification", re.compile(r"\bcertification\b|\bdecertification\b", re.I)),
    ("Certificate of convenience", re.compile(r"certificate of public convenience", re.I)),
    ("Certificate of authority", re.compile(r"certificate of authority", re.I)),
    ("Territorial", re.compile(r"territor", re.I)),
    ("Demand-side management", re.compile(r"demand[- ]side|\bDSM\b", re.I)),
    ("Rulemaking", re.compile(r"rulemaking", re.I)),
    ("Merger or transfer", re.compile(r"\bmerger\b|transfer of control|\bacquisition of\b", re.I)),
    ("Complaint", re.compile(r"\bcomplaint\b", re.I)),
]
PROCEEDING_NAMES = [n for n, _ in PROCEEDINGS]


def is_procedural(cite: str) -> bool:
    if cite.startswith("515-"):
        return cite in PROCEDURAL_RULES or cite.startswith(PROCEDURAL_RULE_PREFIXES)
    return cite in PROCEDURAL_SECTIONS or cite.startswith(PROCEDURAL_PREFIXES)


def citations(text: str) -> list[str]:
    """Every Code section and Commission rule cited, normalized, in order of first use."""
    if not text:
        return []
    found: dict[str, None] = {}
    for m in RULE.finditer(text):
        found[f"515-{m.group(1)}-{m.group(2)}-.{m.group(3)}"] = None
    markers = [m.start() for m in MARKER.finditer(text)]
    mi = 0
    for m in SECTION.finditer(text):
        s = m.group(1)
        if not s.startswith("46-"):
            # Other titles count only within a short list after a marker.
            while mi < len(markers) and markers[mi] < m.start() - 160:
                mi += 1
            if not (mi < len(markers) and markers[mi] < m.start()):
                continue
        found[s] = None
    return list(found)


def law_of(cite: str) -> str | None:
    for name, test in LAWS:
        if test(cite):
            return name
    return None


def code_url(cite: str) -> str | None:
    """The free text of a Commission rule's subject on the Secretary of State's
    site, or of a Code section on Justia, for the parts of the Code
    whose page addresses were checked by hand (Nov 24, 2026). None for
    sections outside those parts, which are shown
    without a link rather than with a guessed one."""
    if cite.startswith("515-"):
        # The Secretary of State's official rules site, at the rule's subject.
        return "https://rules.sos.ga.gov/gac/" + cite.rsplit("-", 1)[0]
    t, c, n = _sec_parts(cite)
    x = _num(n)
    if t != "46":
        return None
    if c == "2" and 20 <= x < 35:
        path = "chapter-2/article-2"
    elif c == "2" and 90 <= x <= 95:
        path = "chapter-2/article-5"
    elif c == "3A":
        path = "chapter-3a"
    elif c == "3" and 1 <= x <= 15:
        path = "chapter-3/article-1/part-1"
    elif c == "3" and 50 <= x <= 56:
        path = "chapter-3/article-1/part-3"
    elif c == "5" and 23 <= x <= 27:
        path = "chapter-5/article-2/part-1"
    else:
        return None
    return f"{CODE_BASE}{path}/section-{cite.lower().replace('.', '-')}/"


def _fixes() -> set[tuple[str, str]]:
    if not FIXES.exists():
        return set()
    try:
        data = json.loads(FIXES.read_text())
    except json.JSONDecodeError:
        return set()
    return {(str(x["document_id"]), x["tag"]) for x in data.get("remove", [])}


_FIXES: set[tuple[str, str]] | None = None


def legal_hooks(rec: dict, text: str) -> dict:
    """Law tags for one filing: {"legal": [...], "legal_reasons": {tag: why},
    "laws_cited": [...substantive sections...], "procedural_cites": n}."""
    global _FIXES
    if _FIXES is None:
        _FIXES = _fixes()
    title = rec.get("description") or ""
    in_title = citations(title)
    in_text = [c for c in citations(text) if c not in in_title]
    reasons: dict[str, str] = {}
    cited: list[str] = []
    procedural = 0
    for where, cites in (("title", in_title), ("text", in_text)):
        for c in cites:
            if is_procedural(c):
                procedural += 1
                continue
            cited.append(c)
            name = law_of(c)
            if name and name not in reasons:
                ref = f"Rule {c}" if c.startswith("515-") else f"O.C.G.A. § {c}"
                reasons[name] = f"the filing's {where} cites {ref}"
    doc = str(rec.get("document_id"))
    for name in list(reasons):
        if (doc, name) in _FIXES:
            del reasons[name]
    return {"legal": sorted(reasons, key=LAW_NAMES.index), "legal_reasons": reasons,
            "laws_cited": cited, "procedural_cites": procedural}


def proceedings(title: str) -> dict[str, str]:
    """Proceeding types for a docket from its own title: {tag: why}."""
    out = {}
    for name, rx in PROCEEDINGS:
        m = rx.search(title or "")
        if m:
            out[name] = f'the docket\'s title says "{m.group(0)}"'
    # "Certification" inside a request for proposals docket is the RFP's own
    # certification; both tags stay, which is what the title says.
    return out
