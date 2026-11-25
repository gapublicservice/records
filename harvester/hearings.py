"""One Records page for each hearing on the Commission's calendar.

    python -m harvester.hearings --check DIR   # write the private weekly check list into DIR

A hearing page builds on the docket timeline. It holds:

1. Where it stands: one line, set automatically each night from the titles of
   the docket's filings by the written rules below. Every line names the filing
   it rests on, so anyone can check it. Paul spot-checks these lines weekly.
2. The latest filings, each with a one-line summary: the kind of filing (from
   its title, by rule) and, where the filing's own text has one, the sentence
   that says what it asks for or orders, quoted exactly.
3. What parties of record have said about the hearing, quoted exactly from
   their filings, each with its filing number. Nothing is characterized.
4. The Commission's own calendar page and docket page, as the official source.

Records makes no claims of its own here beyond the stage line. Trade-secret and
confidential filings are never quoted, and nothing is quoted from a certificate
of service or from any line that holds an email address or phone number.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path

from .run import ROOT

e = html.escape
PSC_DOC = "https://psc.ga.gov/search/facts-document/?documentId="
PSC_DOCKET = "https://psc.ga.gov/search/facts-docket/?docketId="
HEARING_KINDS = ("hearing", "docket")
LATEST_N = 6
STATEMENTS_N = 8
# Filers that are the Commission itself, not parties.
_BENCH = ("GPSC", "Hearing Officer")


# ---------------------------------------------------------------- which events

def is_hearing(ev: dict) -> bool:
    return (ev.get("kind") in HEARING_KINDS and bool(ev.get("dockets")) and not ev.get("other")
            and "psc.ga.gov/agendas-calendars/commission-calendar/" in (ev.get("url") or ""))


def slug(ev: dict) -> str:
    m = re.search(r"/commission-calendar/([a-z0-9.\-]+)/", ev.get("url") or "")
    base = m.group(1) if m else re.sub(r"[^a-z0-9]+", "-", (ev.get("title") or "hearing").lower()).strip("-")
    # Several days of one hearing can share an address; the date keeps each day its own page.
    return base if ev["date"] in _date_bits(base) else f'{base}-{ev["date"]}'


def _date_bits(s: str) -> str:
    """The slug with any m-d-yyyy in it rewritten as yyyy-mm-dd, so a date check can match."""
    out = s
    for m in re.finditer(r"(\d{1,2})-(\d{1,2})-(\d{4})", s):
        out += f" {m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return out


def href(ev: dict, up: str = "") -> str:
    return f"{up}hearing/{slug(ev)}/"


def hearing_events(allev: list[dict]) -> list[dict]:
    seen, out = set(), []
    for ev in allev:
        if is_hearing(ev) and slug(ev) not in seen:
            seen.add(slug(ev))
            out.append(ev)
    return out


# ---------------------------------------------------------------- filing kinds

def is_order(r: dict) -> bool:
    desc = (r.get("description") or "").strip()
    co = r.get("company") or ""
    if not re.search(r"\border\b|\bruling\b", desc, re.I):
        return False
    if re.search(r"\bproposed\b|\bresponse\b|\bmotion\b(?!.*\border on\b)|\bbrief\b|\bappeal\b|\bobjection\b|\breply\b|"
                 r"\brequest\b|\bpetition\b(?!.*\border on\b)|\bexception", desc, re.I) and not re.match(r"\s*order\b", desc, re.I):
        return False
    return co.startswith(_BENCH) or co == "Staff" or re.match(r"\s*(order|chairman)", desc, re.I) is not None


def is_party(r: dict) -> bool:
    """A party of record speaking for itself: anyone but the Commission and its hearing
    officers, and not an order or notice the Commission issued under its Staff's name."""
    co = r.get("company") or ""
    if co.startswith(_BENCH) or is_order(r):
        return False
    if co == "Staff" and re.search(r"notice of hearing|scheduling", r.get("description") or "", re.I):
        return False
    return True


# Kind of filing, from its title. First match wins. Each label is plain and says
# only what the title itself says.
KINDS = [
    (r"\btranscript", "Hearing transcript"),
    (r"notice of hearing|scheduling order|procedural (and scheduling )?order", "Scheduling order or notice of hearing"),
    (r"surrebuttal testimony", "Surrebuttal testimony"),
    (r"rebuttal testimony", "Rebuttal testimony"),
    (r"direct testimony|\btestimony\b", "Testimony"),
    (r"^\s*initial decision", "Hearing Officer's initial decision"),
    (r"post[- ]?hearing brief|proposed order", "Post-hearing brief or proposed order"),
    (r"data request responses?|responses? to .*data request|supplemental responses", "Answers to data requests"),
    (r"data request", "Data request"),
    (r"\b(response|responses|opposition|reply|objection)\b", "Response"),
    (r"application .*for (full )?commission review|emergency appeal|\bappeal\b", "Appeal or request for full Commission review"),
    (r"\bmotion\b", "Motion"),
    (r"\bbrief\b", "Brief"),
    (r"(intervene|intervention)", "Request to intervene"),
    (r"witness list|exhibits? list|proposed stipulations", "Witness, exhibit or proposed stipulation list"),
    (r"\bstipulation\b", "Stipulation"),
    (r"return of service", "Return of service"),
    (r"subpoena", "Subpoena request"),
    (r"\bpetition\b|\bapplication\b|\bcomplaint\b", "Petition or application"),
    (r"\banswer\b", "Answer"),
    (r"entry of appearance|notice of appearance", "Entry of appearance"),
    (r"\bnotice\b", "Notice"),
    (r"\bcomments?\b", "Comments"),
    (r"\bletter\b", "Letter"),
]


def kind_of(r: dict) -> str:
    desc = r.get("description") or ""
    if re.search(KINDS[1][0], desc, re.I):
        return KINDS[1][1]  # a scheduling order is its own stage, not just "an order"
    if is_order(r):
        return "Order"
    for rx, label in KINDS:
        if re.search(rx, desc, re.I):
            return label
    return "Filing"


# ---------------------------------------------------------------- stored text

def _attachments(doc_id: int) -> list[dict]:
    p = ROOT / "data" / "filings" / str(doc_id // 1000) / f"{doc_id}.json"
    try:
        return json.loads(p.read_text()).get("attachments") or []
    except (OSError, ValueError):
        return []


_COS = re.compile(r"\bcos\b|certificate[\s_-]*of[\s_-]*service|service[\s_-]*list", re.I)
_CONTACT = re.compile(r"@|\(\d{3}\)\s*\d{3}|\b\d{3}[-.]\d{3}[-.]\d{4}\b|https?://|www\.", re.I)
_TS_TEXT = re.compile(r"trade\s*secret\s*(begins|ends|\]|\[)|\[\s*(begin|end)\s+trade|\*\*\*", re.I)


def texts(r: dict) -> list[tuple[int, str]]:
    """The public text of a filing's main attachments: never a trade-secret copy, never a
    certificate of service, never a file the trade-secret guard marked."""
    if (r.get("files") or {}).get("state") != "available":
        return []
    out = []
    for a in _attachments(r["document_id"]):
        if a.get("trade_secret_marked") or a.get("held_back") or not a.get("text_file") or _COS.search(a.get("name") or ""):
            continue
        p = ROOT / a["text_file"]
        try:
            out.append((a["attachment_id"], p.read_text(errors="replace")))
        except OSError:
            continue
    return out


def _sentences(text: str) -> list[str]:
    # Join the lines pdftotext breaks, then cut into sentences.
    t = text.replace("­", "")
    t = re.sub(r"-\n\s*", "", t)
    t = re.sub(r"\s+", " ", t)
    parts = re.split(r"(?:(?<=[.!?])|(?<=[.!?][\"”’)]))\s+(?=[A-Z“\"(])", t)
    return [p.strip() for p in parts if p.strip()]


_LEAD = re.compile(r"^(?:[A-Z][A-Z’'.,&\-]+\s+|[IVX]+\.\s*|§\s*){2,}(?=[A-Z][a-z])|^(?:Dear\s+)?(?:(?:Mr|Ms|Mrs|Dr)\.\s+)?[A-Z][a-z]+:\s+")


def _strip_lead(s: str) -> str:
    """Drop a heading in capitals or a salutation glued to the start of a sentence."""
    return _LEAD.sub("", s, count=1).strip()


def _clean_ok(s: str, lo: int = 50, hi: int = 420) -> bool:
    if re.search(r"\bTO:|GREETINGS|\bRE:", s):
        return False
    if not s or not s[0].isupper() or s[-1] not in ".!?”\"’)" or "•" in s or "¶" in s:
        return False
    if s.count("(") != s.count(")") or s.count("“") != s.count("”"):
        return False
    if re.search(r"\.\s?\d{1,3}\s+[A-Za-z]|\b\d{1,3}\s*$", s[:-1]):
        return False  # a footnote number joined into the sentence
    if not (lo <= len(s) <= hi) or _CONTACT.search(s) or _TS_TEXT.search(s):
        return False
    letters = sum(c.isalpha() for c in s)
    if letters < 0.6 * len(s):
        return False  # tables, captions, lists of dates
    if s.count(")") > 4 or re.search(r"\s{2,}|_{3,}|\.{4,}", s):
        return False
    words = s.split()
    caps = sum(1 for w in words if w.isupper() and len(w) > 2)
    return caps <= len(words) * 0.4


_ASK = re.compile(
    r"\b(respectfully (request|move|ask|submit|urge|pray)s?|hereby (move|request|petition)s?|"
    r"moves? (the commission|for|to)|requests? that the (commission|hearing officer)|"
    r"asks? the (commission|hearing officer)|urges? the commission|"
    r"it is hereby ordered|it is (further )?ordered|ordered that|is hereby (granted|denied|stayed)|"
    r"hereby (grants?|denies|stays|orders|amends))\b", re.I)


def ask_line(r: dict) -> tuple[str, int] | None:
    """The filing's own sentence that says what it asks for or orders, if one is found."""
    for att, text in texts(r):
        for s in _sentences(text)[:400]:
            s = _strip_lead(s)
            if _ASK.search(s) and _clean_ok(s, 40, 360):
                return s, att
    return None


_HEARING = re.compile(r"\bhearings?\b(?!\s+officer)", re.I)
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def _date_words(iso: str) -> re.Pattern:
    d = dt.date.fromisoformat(iso)
    return re.compile(rf"\b{d:%B}\s+{d.day}\b|\b{d.month}/{d.day}/(?:{d.year}|{d.year % 100})\b", re.I)


# Forms and lists, not a party speaking: never quoted as a statement.
NOT_STATEMENTS = ("Subpoena request", "Return of service", "Entry of appearance", "Data request",
                  "Answers to data requests", "Hearing transcript")


def statements(fs: list[dict], ev: dict, today: str) -> list[dict]:
    """Sentences parties of record wrote about the hearing, quoted from their own filings.
    Sentences naming the hearing's date come first, then the newest; one per filing."""
    hd = ev["date"]
    since = (dt.date.fromisoformat(hd) - dt.timedelta(days=150)).isoformat()
    until = (dt.date.fromisoformat(hd) + dt.timedelta(days=45)).isoformat()
    on_day = _date_words(hd)
    found = []
    for r in fs:
        fd = r.get("filed_date") or ""
        if not (since <= fd <= min(until, today)) or not is_party(r) or kind_of(r) in NOT_STATEMENTS:
            continue
        best = None
        for att, text in texts(r):
            for s in _sentences(text)[:1500]:
                s = _strip_lead(s)
                if not _HEARING.search(s) or not _clean_ok(s):
                    continue
                score = 2 if on_day.search(s) else (1 if re.search(r"(evidentiary hearing|the hearing|this hearing|hearing (is|was|will be) (set|scheduled|held))(?!\s+officer)", s, re.I) else 0)
                if best is None or score > best[0]:
                    best = (score, s, att)
            if best and best[0] == 2:
                break
        if best and best[0] > 0:
            found.append({"score": best[0], "quote": best[1], "attachment_id": best[2], "document_id": r["document_id"],
                          "filed_date": fd, "company": r.get("company") or "No filer named",
                          "description": (r.get("description") or "").strip()})
    found.sort(key=lambda x: (x["score"], x["filed_date"], x["document_id"]), reverse=True)
    return found[:STATEMENTS_N]


# ---------------------------------------------------------------- stage line

def _day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def _cite(r: dict) -> dict:
    return {"document_id": r["document_id"], "filed_date": r.get("filed_date") or "",
            "company": r.get("company") or "No filer named", "description": (r.get("description") or "").strip()}


# The stages, in the order a contested docket usually moves through them. The
# stage shown is the latest one any filing up to that day reaches. Post-hearing
# stages count only filings made on or after the hearing's date.
STAGES = [
    ("filed", "Petition or application filed", lambda r, hd: kind_of(r) == "Petition or application" and is_party(r), False),
    ("scheduled", "Hearing scheduled", lambda r, hd: kind_of(r) == "Scheduling order or notice of hearing", False),
    ("direct", "Testimony filed", lambda r, hd: kind_of(r) == "Testimony", False),
    ("rebuttal", "Rebuttal testimony filed", lambda r, hd: kind_of(r) in ("Rebuttal testimony", "Surrebuttal testimony"), False),
    ("transcript", "Hearing transcript filed", lambda r, hd: kind_of(r) == "Hearing transcript", True),
    ("briefs", "Post-hearing briefs or proposed orders filed", lambda r, hd: kind_of(r) == "Post-hearing brief or proposed order", True),
    ("stipulation", "Stipulation filed", lambda r, hd: kind_of(r) == "Stipulation", False),
    ("initial", "Hearing Officer's initial decision filed", lambda r, hd: kind_of(r) == "Hearing Officer's initial decision", True),
    ("order", "Order filed after the hearing", lambda r, hd: kind_of(r) == "Order", True),
]


def stage(fs: list[dict], ev: dict, as_of: str) -> dict:
    """Where the docket stands for this hearing on a given day, from filing titles alone."""
    hd = ev["date"]
    upto = [r for r in fs if (r.get("filed_date") or "") and r["filed_date"] <= as_of]
    upto.sort(key=lambda r: (r["filed_date"], r["document_id"]))
    reached = None
    for key, label, test, after in STAGES:
        hits = [r for r in upto if test(r, hd) and (not after or r["filed_date"] >= hd)]
        if hits:
            reached = {"key": key, "label": label, "filing": _cite(hits[-1])}
    orders = [r for r in upto if kind_of(r) == "Order"]
    latest_order = _cite(orders[-1]) if orders else None
    return {"as_of": as_of, "hearing_date": hd, "stage": reached, "latest_order": latest_order,
            "line": stage_line(ev, reached, latest_order, as_of)}


def stage_line(ev: dict, reached: dict | None, latest_order: dict | None, as_of: str) -> str:
    hd = ev["date"]
    bits = []
    if reached:
        f = reached["filing"]
        bits.append(f'{reached["label"]}. Latest such filing: “{_trim(f["description"])}” '
                    f'({_day(f["filed_date"])}, filing {f["document_id"]}).')
    else:
        bits.append("No filing in the record yet matches a stage rule.")
    if latest_order and (not reached or reached["key"] != "order"):
        bits.append(f'Latest order in the record: “{_trim(latest_order["description"])}” '
                    f'({_day(latest_order["filed_date"])}, filing {latest_order["document_id"]}).')
    when = f'{_day(hd)}' + (f' at {ev["time"]}' if ev.get("time") else "")
    if hd >= as_of:
        bits.append(f"The Commission's calendar lists the hearing for {when}.")
    else:
        bits.append(f"The Commission's calendar listed the hearing for {when}.")
    return " ".join(bits)


def _trim(s: str, n: int = 140) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def week_of_lines(fs: list[dict], ev: dict, today: str, days: int = 7) -> list[dict]:
    """The stage line on each of the last `days` days, keeping only the days it changed."""
    out, last = [], None
    start = dt.date.fromisoformat(today) - dt.timedelta(days=days)
    for i in range(days + 1):
        d = (start + dt.timedelta(days=i)).isoformat()
        s = stage(fs, ev, d)
        if s["line"] != last:
            out.append(s)
            last = s["line"]
    return out


# ---------------------------------------------------------------- the page

STAGE_NOTE = ("Set automatically each night from the titles of the docket's filings, by written rules, "
              "and checked by hand each week. It says which filings are in the record, not what they argue "
              "or what the Commission will do.")


def summary(r: dict) -> dict:
    k = kind_of(r)
    a = ask_line(r)
    return {"document_id": r["document_id"], "kind": k, "company": r.get("company") or "No filer named",
            "filed_date": r.get("filed_date") or "", "description": (r.get("description") or "").strip(),
            "ask": a[0] if a else "", "attachment_id": a[1] if a else None,
            "files": r.get("files")}


def build_data(ev: dict, fs: list[dict], today: str) -> dict:
    dated = sorted((r for r in fs if r.get("filed_date")), key=lambda r: (r["filed_date"], r["document_id"]), reverse=True)
    return {"slug": slug(ev), "event": ev, "stage": stage(fs, ev, today),
            "latest": [summary(r) for r in dated[:LATEST_N]],
            "statements": statements(dated, ev, today)}


def page_body(h: dict, titles: dict, today: str, copied_note, file_marker, kind_label: dict,
              transcript_href: str = "", checked: str | None = None, agenda_href: str = "") -> str:
    ev = h["event"]
    dks = sorted({int(d) for d in ev.get("dockets") or []})
    when = f"{dt.date.fromisoformat(ev['date']):%A, %B} {dt.date.fromisoformat(ev['date']).day}, {ev['date'][:4]}"
    when += f" at {ev['time']}" if ev.get("time") else ""
    title = re.sub(r"\s*\d{1,2}-\d{1,2}-\d{2,4}$", "", ev.get("title") or "Hearing").strip()
    dk_links = " · ".join(f'<a class="mono" href="../../docket/{d}/">Docket {d} on Records</a>' for d in dks)
    official = " · ".join([f'<a href="{e(ev["url"])}">The Commission\'s calendar page for this hearing</a>']
                          + [f'<a href="{PSC_DOCKET}{d}">Docket {d} on the Commission\'s site</a>' for d in dks])
    extra = ""
    if agenda_href:
        extra += f' · <a href="{e(agenda_href)}">Agenda</a>'
    if transcript_href:
        extra += f' · <a href="{e(transcript_href)}">Unofficial transcript</a>'
    coming = "Coming up" if ev["date"] >= today else "Past hearing"
    st = h["stage"]
    sdesc = ""
    if st["stage"]:
        f = st["stage"]["filing"]
        sdesc = f'<a href="{PSC_DOC}{f["document_id"]}">{e(st["stage"]["label"])}</a>'
    stage_html = (f'<div class="hg-stage"><p class="hg-k">Where it stands, as of {e(_day(today))}</p>'
                  f'<p class="hg-line">{_linked_line(st)}</p>'
                  f'<p class="muted">{e(STAGE_NOTE)} <a href="#how">How this page is made</a>.</p></div>')
    rows = []
    for s in h["latest"]:
        ask = (f'<br><span class="hg-ask">It says: “{e(s["ask"])}”</span>' if s["ask"] else "")
        rows.append(f'<tr><td class="mono">{e(s["filed_date"])}</td><td>{e(s["company"])}</td>'
                    f'<td><b>{e(s["kind"])}.</b> <a href="{PSC_DOC}{s["document_id"]}">{e(s["description"] or "(no description)")}</a> '
                    f'<span class="mono muted">#{s["document_id"]}</span>{ask}<br>{file_marker(s["document_id"], s.get("files"))}</td></tr>')
    latest = (f'<table class="wide"><thead><tr><th>Filed</th><th>Filer</th><th>Filing</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
              if rows else '<p class="muted">No filings in the record for this docket yet.</p>')
    sts = []
    short_day = f'{dt.date.fromisoformat(ev["date"]):%b} {dt.date.fromisoformat(ev["date"]).day}'
    for q in h["statements"]:
        names = (f'<span class="tag">Names the {e(short_day)} hearing</span> ' if q["score"] == 2 else "")
        sts.append(f'<li>{names}<blockquote>“{e(q["quote"])}”</blockquote>'
                   f'<p class="hg-src">{e(q["company"])}, <a href="{PSC_DOC}{q["document_id"]}">{e(_trim(q["description"], 160))}</a>, '
                   f'filed {e(_day(q["filed_date"]))}, filing <span class="mono">{q["document_id"]}</span></p></li>')
    stmt = (f'<ol class="hg-quotes">{"".join(sts)}</ol>' if sts else
            '<p class="muted">We found no sentence about the hearing in the stored text of the parties\' filings. '
            'Text is stored only for the dockets the record follows most closely, and scanned filings have none.</p>')
    return f"""<div class="kicker"><a href="../../calendar.html">Commission calendar</a> · {e(kind_label.get(ev.get("kind"), "Hearing"))} · {e(coming)}</div>
<h1>{e(title)}</h1>
<p class="lede">{e(when)}. {dk_links}{extra}</p>
<div class="note hg-official"><b>The official record:</b> {official}. The Commission's pages are the ones to rely on, and the Commission can move or cancel a hearing at any time.</div>
{copied_note("This page is built from copies of the Commission's calendar and filings.", checked)}
{stage_html}
<h2>Latest filings</h2>
<p class="muted">The newest filings in the docket. The kind of filing is read from its title by rule. Where the filing's own text has a sentence saying what it asks for or orders, that sentence is quoted exactly; the filing is the record.</p>
{latest}
<h2>What parties have said on the record about hearings in this docket</h2>
<p class="muted">Sentences about a hearing from filings by parties of record, those that name this hearing's date first, quoted exactly as the Commission posted them, with the filing each comes from. Orders and notices from the Commission and its hearing officers are not counted as party statements. We add nothing to them and don't say who is right. Text is copied by machine from each filing and can drop or join words; the filing is the record.</p>
{stmt}
<h2 id="how">How this page is made</h2>
<p class="muted">Each night after the harvest, this page is rebuilt from the record: the Commission's calendar entry, the docket's filings and their stored public text. The stage line uses written rules on filing titles (for example, a title with “rebuttal testimony” counts as rebuttal testimony), and stages after the hearing count only filings made on or after the hearing date. Trade-secret and confidential filings are never quoted, and nothing is taken from certificates of service. The <a href="../../docket/{dks[0] if dks else ""}/#timeline">docket timeline</a> has every milestone.</p>"""


def _linked_line(st: dict) -> str:
    """The stage line with each filing number linked to the Commission's page for it."""
    line = e(st["line"])
    return re.sub(r"filing (\d{5,7})", lambda m: f'filing <a class="mono" href="{PSC_DOC}{m.group(1)}">{m.group(1)}</a>', line)


# ---------------------------------------------------------------- weekly check list

def check_list(pages: list[dict], fs_by_docket: dict, today: str, days: int = 7) -> str:
    """A private list of every stage line shown in the past week, for the weekly spot check."""
    lines = [f"# Hearing stage lines, week to {today}", "",
             "Private. For Paul's weekly spot check. Each line is what the hearing page showed; a line is listed "
             "again on each day it changed. Check the named filing on the Commission's site, then mark it.", ""]
    window = (dt.date.fromisoformat(today) - dt.timedelta(days=60)).isoformat()
    for h in pages:
        ev = h["event"]
        if ev["date"] < window:
            continue
        fs = [r for d in ev.get("dockets") or [] for r in fs_by_docket.get(int(d), [])]
        hist = week_of_lines(fs, ev, today, days)
        lines.append(f'## {ev["date"]}: {_trim(ev.get("title") or "", 110)}')
        lines.append(f'Page: https://records.gapublicservice.org/hearing/{h["slug"]}/')
        for s in hist:
            f = (s.get("stage") or {}).get("filing") or {}
            src = f' Source: {PSC_DOC}{f["document_id"]}' if f else ""
            lines.append(f'- [ ] Shown from {s["as_of"]}: {s["line"]}{src}')
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- the private check

def claims(pages: list[dict]) -> list[dict]:
    """Every claim the hearing pages make, for the private claims ledger: each stage
    line, each filing summary and each quoted statement, with what it rests on."""
    out, seen = [], set()
    for h in pages:
        st = h["stage"]
        f = (st.get("stage") or {}).get("filing")
        srcs = [x for x in (f, st.get("latest_order")) if x]
        out.append({"id": f'records-hearing-{h["slug"]}-stage', "kind": "stage line",
                    "where": f'Records hearing page hearing/{h["slug"]}/, Where it stands',
                    "claim": st["line"], "rests_on": [x["document_id"] for x in srcs]})
        for s in h["latest"]:
            k = ("summary", s["document_id"])
            if k in seen:
                continue
            seen.add(k)
            text = f'{s["kind"]}.' + (f' It says: “{s["ask"]}”' if s["ask"] else "")
            out.append({"id": f'records-filing-{s["document_id"]}-summary', "kind": "filing summary",
                        "where": "Records hearing pages, Latest filings", "claim": text,
                        "title": s["description"], "quote": s["ask"], "rests_on": [s["document_id"]],
                        "attachment_id": s["attachment_id"]})
        for q in h["statements"]:
            k = ("quote", q["document_id"], q["quote"])
            if k in seen:
                continue
            seen.add(k)
            out.append({"id": f'records-filing-{q["document_id"]}-quote-{__import__("hashlib").sha1(q["quote"].encode()).hexdigest()[:8]}',
                        "kind": "party statement", "where": "Records hearing pages, What parties have said",
                        "claim": f'{q["company"]} wrote: “{q["quote"]}”', "quote": q["quote"],
                        "rests_on": [q["document_id"]], "attachment_id": q["attachment_id"]})
    return out


def main(argv=None) -> int:
    import argparse
    import collections
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", metavar="DIR", required=True, help="write the private check list and claims here")
    ap.add_argument("--today")
    a = ap.parse_args(argv)
    today = a.today or dt.datetime.now(dt.timezone(dt.timedelta(hours=-5))).date().isoformat()
    rows = [json.loads(l) for l in (ROOT / "data" / "index" / "filings.jsonl").open()]
    by = collections.defaultdict(list)
    for r in rows:
        for d in r["dockets"]:
            by[int(d)].append(r)
    cal = json.loads((ROOT / "data" / "index" / "calendar.json").read_text()).get("events", [])
    pages = [build_data(ev, [r for d in ev["dockets"] for r in by.get(int(d), [])], today) for ev in hearing_events(cal)]
    out = Path(a.check)
    out.mkdir(parents=True, exist_ok=True)
    (out / "hearing-stage-check.md").write_text(check_list(pages, by, today))
    (out / "hearing-claims.json").write_text(json.dumps({"built": today, "claims": claims(pages)}, indent=1, ensure_ascii=False))
    print(f"{len(pages)} hearing pages; check list and claims written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
