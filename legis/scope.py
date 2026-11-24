"""The public tracker's scope rule.

Which bills the public tracker covers is set by this published, neutral rule,
never by anyone's watchlist, so the list of bills signals no position.

A bill is in scope when any of these is true:
  1. it amends Title 46 of the Official Code of Georgia (public utilities);
  2. it names the Public Service Commission;
  3. it is referred to the House Energy, Utilities and Telecommunications
     committee, or to Senate Regulated Industries and Utilities and its
     caption or summary is about utilities (that Senate committee also hears
     professional licensing, alcohol and other business bills);
  4. it changes statewide election law (amends Title 21 and is not a local act).

Local acts (one county or city) are left out unless they amend Title 46.
Honorary and commending resolutions are left out.
"""

from __future__ import annotations

import re

from .textdiff import code_titles

HOUSE_UTILITY_COMMITTEES = (
    "energy, utilities", "energy, utilities & telecommunications",
    "energy, utilities and telecommunications",
)
SENATE_SHARED_COMMITTEE = "regulated industries and utilities"
UTILITY_COMMITTEES = HOUSE_UTILITY_COMMITTEES + (SENATE_SHARED_COMMITTEE,)
UTILITY_TOPIC = re.compile(
    r"\b(utilit\w*|electric\w*|energy|power|natural gas|gas (?:service|pipeline|utilit\w*)|"
    r"telecommunications?|broadband|9-1-1|solar|nuclear|water service|sewer|pipeline|"
    r"data cent\w*|ratepayer\w*|franchise fee\w*)\b", re.I)
PSC = re.compile(r"\bPublic Service Commission\b|\bPublic Service Commissioners?\b", re.I)
HONORARY = re.compile(r"\b(commend|recogniz|honor|congratulat|condolence|dedicat|"
                      r"designat\w+ .{0,40}\b(day|week|month)\b)", re.I)
LOCAL_HINT = re.compile(r"\b(Ga\.\s*L\.\s*\d{4}|for the City of|of the City of|"
                        r"\b[A-Z][a-z]+ County\b(?!.*statewide))")

RULES = {
    "title46": "Amends Title 46 of the Georgia Code (public utilities)",
    "psc": "Names the Public Service Commission",
    "utility_committee": "Referred to a utilities committee",
    "election_law": "Changes statewide election law (Title 21)",
}

# Short forms for the bill page's "Why it's tracked" line (Paul, Nov 24).
RULES_SHORT = {
    "title46": "Title 46 (utilities)",
    "psc": "names the PSC",
    "utility_committee": "utilities committee",
    "election_law": "Title 21 (elections)",
}


def is_local(bill: dict) -> bool:
    lt = str(bill.get("legislation_type") or "").upper()
    if lt in ("LOC", "LOCAL"):
        return True
    if lt in ("GEN", "GENERAL", "CA"):
        return False
    return bool(LOCAL_HINT.search(bill.get("caption") or ""))


def is_honorary(bill: dict) -> bool:
    return str(bill.get("document_type") or "").endswith("R") and bool(
        HONORARY.search(bill.get("caption") or ""))


def reasons(bill: dict, text: str = "") -> list[str]:
    """Which scope rules a bill meets, as keys of RULES. Empty means out of scope."""
    if is_honorary(bill):
        return []
    blob = " ".join([bill.get("caption") or "", bill.get("summary") or ""])
    titles = set(code_titles(blob)) | set(code_titles(text[:20000]))
    local = is_local(bill)
    out = []
    if 46 in titles:
        out.append("title46")
    if local and not out:
        return []
    if PSC.search(blob) or PSC.search(text[:50000]):
        out.append("psc")
    names = [(c.get("name") or "").lower() for c in bill.get("committees", [])]
    house = any(h in n for n in names for h in HOUSE_UTILITY_COMMITTEES)
    senate = any(SENATE_SHARED_COMMITTEE in n for n in names) and bool(UTILITY_TOPIC.search(blob))
    if house or senate:
        out.append("utility_committee")
    if 21 in titles and not local:
        out.append("election_law")
    return out
