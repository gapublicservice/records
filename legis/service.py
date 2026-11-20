"""Read Georgia General Assembly legislation from its public web service.

The General Assembly publishes an older SOAP web service at
http://webservices.legis.ga.gov/GGAServices/<Service>/Service.svc?wsdl
(Legislation, Votes, Members). It needs no login. Its WSDL still answered on
Nov 20, 2026, and the Open States project's Georgia scraper still calls it.
The site's newer JSON service needs a token built from the site's own code;
this harvester leaves that alone.

Every call goes one at a time, with a pause, and backs off on errors.

The service's array wrappers come back as {"SomeListing": [...]} once
serialized, so _items() unwraps any one-key dict or list. Field names follow
the WSDL and the Open States scraper; the first live run checks them against
real responses (see tests/legis/README.md).
"""

from __future__ import annotations

import time
from typing import Any, Iterable

SERVICE_URL = "http://webservices.legis.ga.gov/GGAServices/{name}/Service.svc?wsdl"
BILL_PAGE = "https://www.legis.ga.gov/legislation/{id}"
DOC_URL = "https://www.legis.ga.gov/api/legislation/document/{library}/{doc_id}"

# Session ids from the site's session list (Open States keeps the same table).
# 2027-2028 is not listed yet; discover_session() finds it when it appears.
KNOWN_SESSIONS = {
    "2025_26": {"id": 1033, "library": "20252026", "label": "2025-2026 Regular Session"},
    "2026_ss": {"id": 1034, "library": "2026EX", "label": "2026 Special Session"},
}

PAUSE_SECONDS = 1.0


def _items(x: Any) -> list:
    """Unwrap a serialized SOAP array: None -> [], list -> list, {"X": [..]} -> [..]."""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        if len(x) == 1:
            (v,) = x.values()
            return _items(v) if isinstance(v, (list, dict)) or v is None else [v]
        return [x]
    return [x]


class Service:
    """Thin wrapper over the three SOAP services, using zeep."""

    def __init__(self, pause: float = PAUSE_SECONDS):
        import zeep  # imported here so tests run without it
        from zeep.transports import Transport

        self._zeep = zeep
        transport = Transport(timeout=60, operation_timeout=120)
        self.clients = {n: zeep.Client(SERVICE_URL.format(name=n), transport=transport)
                        for n in ("Legislation", "Votes", "Members")}
        self.pause = pause

    def _call(self, service: str, op: str, *args):
        last = None
        for attempt in range(5):
            time.sleep(self.pause)
            try:
                res = getattr(self.clients[service].service, op)(*args)
                return self._zeep.helpers.serialize_object(res, dict)
            except Exception as e:  # network, fault, timeout
                if "is not published" in str(e):
                    return None
                last = e
                time.sleep((attempt + 1) * 15)
        raise RuntimeError(f"{service}.{op}{args} failed after 5 tries: {last}")

    def index(self, session_id: int) -> list[dict]:
        """Every measure in a session: Id, DocumentType, Number, Suffix, Caption..."""
        return _items(self._call("Legislation", "GetLegislationForSession", session_id))

    def detail(self, legislation_id: int) -> dict:
        return self._call("Legislation", "GetLegislationDetail", legislation_id) or {}

    def vote(self, vote_id: int) -> dict | None:
        return self._call("Votes", "GetVote", vote_id)


def bill_key(raw: dict) -> str:
    """'HB 7', 'SB 10', 'HR 3', with a suffix such as 'EX' for special sessions."""
    key = f'{raw.get("DocumentType")} {raw.get("Number")}'
    if raw.get("Suffix"):
        key += str(raw["Suffix"])
    return key


def slug(key: str) -> str:
    return key.replace(" ", "").lower()


def _iso(d: Any) -> str | None:
    if d is None:
        return None
    if hasattr(d, "isoformat"):
        return d.isoformat()
    return str(d)


def _sponsors(raw: dict) -> list[dict]:
    out = []
    for kind in ("Authors", "Sponsors"):
        for s in _items(raw.get(kind)):
            if not isinstance(s, dict):
                continue
            out.append({
                "member_id": s.get("MemberId"),
                "name": (s.get("MemberDescription") or "").strip(),
                "role": "author" if "Author" in str(s.get("Type") or kind) else "sponsor",
                "type": s.get("Type"),
                "order": s.get("Sequence"),
            })
    out.sort(key=lambda s: (s["role"] != "author", s["order"] if s["order"] is not None else 999))
    return out


def normalize(raw: dict, session: str, votes: Iterable[dict] = ()) -> dict:
    """One bill record in our own shape, from a GetLegislationDetail response."""
    sess = KNOWN_SESSIONS.get(session, {})
    history = []
    for h in _items(raw.get("StatusHistory")):
        history.append({"date": _iso(h.get("Date")), "code": h.get("Code"),
                        "action": (h.get("Description") or "").strip(), "id": h.get("Id")})
    history.sort(key=lambda h: h["date"] or "")
    committees = [{"chamber": c.get("Type"), "name": (c.get("Name") or "").strip(),
                   "id": c.get("Id")} for c in _items(raw.get("Committees")) if isinstance(c, dict)]
    versions = []
    for v in _items(raw.get("Versions")):
        doc_id = v.get("Id")
        url = v.get("Url") or ""
        # The service's own Url pattern is stale for some sessions; the site serves
        # every version at /api/legislation/document/<library>/<doc id>.
        if doc_id and sess.get("library"):
            url = DOC_URL.format(library=sess["library"], doc_id=doc_id)
        versions.append({"doc_id": doc_id, "label": (v.get("Description") or "").strip(),
                         "version": v.get("Version"), "url": url})
    key = bill_key(raw)
    return {
        "key": key,
        "slug": slug(key),
        "session": session,
        "legislation_id": raw.get("Id"),
        "page": BILL_PAGE.format(id=raw.get("Id")),
        "document_type": raw.get("DocumentType"),
        "number": raw.get("Number"),
        "legislation_type": raw.get("LegislationType"),
        "caption": (raw.get("Caption") or "").strip(),
        "summary": (raw.get("Summary") or "").strip(),
        "sponsors": _sponsors(raw),
        "committees": committees,
        "status_history": history,
        "versions": versions,
        "votes": [normalize_vote(v) for v in votes if v],
        "act_veto_number": raw.get("ActVetoNumber"),
    }


def normalize_vote(v: dict) -> dict:
    members = []
    for m in _items(v.get("Votes")):
        who = m.get("Member") or {}
        if (who.get("Name") or "").upper() == "VACANT":
            continue
        members.append({"name": who.get("Name"), "member_id": who.get("Id"),
                        "vote": m.get("MemberVoted")})
    return {
        "vote_id": v.get("VoteId"),
        "chamber": v.get("Branch"),
        "date": _iso(v.get("Date")),
        "roll_call": (v.get("Description") or "").strip(),
        "motion": (v.get("Caption") or "").strip(),
        "yea": v.get("Yeas"), "nay": v.get("Nays"),
        "not_voting": v.get("NotVoting"), "excused": v.get("Excused"),
        "members": members,
    }


def vote_ids(raw: dict) -> list[int]:
    return [v.get("VoteId") for v in _items(raw.get("Votes")) if isinstance(v, dict) and v.get("VoteId")]
