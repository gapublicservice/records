"""Bills and disconnections: what households pay and how many lose service.

    python -m harvester.household collect    # parse stored Docket 42516 reports
    python -m harvester.household fetch      # rate survey and gas pricing index from psc.ga.gov
    python -m harvester.household site       # write the page (or a preview, until it is live)

Every figure comes from a Commission filing or a Commission page and carries
where it came from. Sources:

- Georgia Power's monthly bad debt report, filed in Docket 42516. The public
  version of each report is read by the nightly harvest; this module turns its
  text into numbers per month. When two reports give a month different
  figures, the later report is used and the change is recorded.
- The Commission's Residential Rate Survey (electric), at 1,000 kWh.
- The Commission's Marketers Pricing Index (natural gas, Atlanta Gas Light area).
- Bill changes the Commission approved, from its orders, in
  data/reference/bill-changes.json (entered by hand, each with its quote).

The page states figures and where they come from. It does not say why they
are high or low or who is responsible: any such line is Paul's to write.
Until data/reference/household.json says "live": true, the page is written
to _preview/ and is not published.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

from .run import DATA, ROOT, save_json

e = html.escape
OUT_DIR = DATA / "household"
REFERENCE = ROOT / "data" / "reference"
REPORT_DOCKET = 42516
PAGE = "bills-and-disconnections.html"

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]

# Row labels in the report, as the company words them, and the key each one
# is stored under. Count and dollar rows share the age-bucket labels; a row
# with dollar signs gets "_usd" added. Longest label wins.
ROWS = {
    "number of customers": "customers",
    "dollar amount billed": "billed",
    "total receipts": "receipts",
    "number of customers charged a security deposit": "deposits_new",
    "dollar value of security deposits charged for a new account": "deposits_new",
    "number accounts that transferred a security deposit to a new premise": "deposits_transferred",
    "dollar value of security deposits transferred to a new premise": "deposits_transferred",
    "total number of accounts past due": "past_due",
    "30 - 60 days past due": "past_due_30_60",
    "60 - 90 days past due": "past_due_60_90",
    "90 - 120 days past due": "past_due_90_120",
    "120+ days past due": "past_due_120_plus",
    "more than 120 days past due": "past_due_120_plus",
    "total dollar value of accounts past due": "past_due",
    "number of customers charged a late payment fee": "late_fees",
    "dollar value of late payment fees charged": "late_fees",
    "number of disconnection notices issued": "notices",
    "number of installment payment plans established": "plans_established",
    "dollars associated with installment payment plans established": "plans_established",
    "number of installment payment plans successfully completed": "plans_completed",
    "number of failed installment payment plans": "plans_failed",
    "number of disconnections for nonpayment": "disconnections",
    "number of service reconnections after disconnection for nonpayment": "reconnections",
    "gross number of all accounts written off as uncollectible": "written_off",
    "gross number of accounts written off as uncollectible": "written_off",
    "net dollar value of accounts written off as uncollectible": "written_off",
    "number of accounts from prepay to post pay": "prepay_to_postpay",
    "number of accounts from post pay to prepay": "postpay_to_prepay",
}
# Rows whose own label says dollars, even where a figure is written "-".
DOLLAR_LABELS = ("dollar", "receipts", "net dollar")
SECTIONS = (("all customer classes", "all"), ("residential class only", "residential"))
SECTION_END = re.compile(r"bad debt budget|risk factor|incremental bad debt\s*$", re.I)

_NUM = re.compile(r"^\(?-?\$?[\d,]+(?:\.\d+)?\)?%?$")


def _norm(s: str) -> str:
    s = s.lower().replace("–", "-").replace("—", "-")
    s = re.sub(r"\s*-\s*", " - ", s)
    return re.sub(r"\s+", " ", s).strip()


def _value(tok: str):
    if tok == "-":
        return 0
    if tok.upper() == "REDACTED":
        return None
    neg = tok.startswith("(") and tok.endswith(")") or tok.startswith("-") and len(tok) > 1
    t = tok.strip("()$%").lstrip("-").replace(",", "")
    v = float(t) if "." in t else int(t)
    return -v if neg else v


def split_row(line: str) -> tuple[str, list, bool]:
    """'Label words  1,234  $ 5,678  -' -> ('Label words', [1234, 5678, 0], has_dollars)."""
    toks = line.split()
    vals, dollars = [], False
    while toks:
        t = toks[-1]
        if t == "$":
            dollars = True
        elif t in ("-", "REDACTED", "Redacted", "redacted") or _NUM.match(t):
            if "$" in t:
                dollars = True
            vals.append(_value(t))
        else:
            break
        toks.pop()
    return " ".join(toks), list(reversed(vals)), dollars


def match_label(text: str) -> str | None:
    n = _norm(text)
    best = None
    for label in ROWS:
        if n.startswith(label) and (best is None or len(label) > len(best)):
            best = label
    if best is None and len(n) >= 24:
        # A label cut short where the page wrapped it: take it only if one label fits.
        fits = {ROWS[label] for label in ROWS if label.startswith(n)}
        if len(fits) == 1:
            best = next(label for label in ROWS if label.startswith(n))
    return best


def _months_in(line: str) -> list[tuple[int, int | None]]:
    """Month columns in a header line: [(month, year or None), ...]."""
    out = []
    for tok in re.findall(r"[A-Za-z]+(?:[-\s'’]\d{2,4})?", line):
        m = re.match(r"([A-Za-z]+)(?:[-\s'’](\d{2,4}))?$", tok)
        word = m.group(1).lower()
        if word[:3] in MONTHS and (len(word) <= 3 or word in [n.lower() for n in MONTH_NAMES] or word == "sept"):
            y = m.group(2)
            year = None if not y else (int(y) + 2000 if len(y) == 2 else int(y))
            out.append((MONTHS[word[:3]], year))
    return out


def _years_in(line: str) -> list[int]:
    toks = line.split()
    if toks and all(re.fullmatch(r"20\d\d|2,0\d\d", t) for t in toks):
        return [int(t.replace(",", "")) for t in toks]
    return []


def _backward(months: list[int], last: tuple[int, int]) -> list[tuple[int, int]]:
    """Give years to a run of months that ends at the report's own month."""
    y, out = last[0], []
    prev = None
    for m in reversed(months):
        if prev is not None and m >= prev:
            y -= 1
        out.append((y, m))
        prev = m
    return list(reversed(out))


def report_month(*names: str) -> tuple[int, int] | None:
    """(year, month) a report covers, from its file name or its title."""
    for s in names:
        s = (s or "").lower()
        m = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s_.-]+(20\d\d)", s)
        if m:
            return int(m.group(2)), MONTHS[m.group(1)]
    return None


def parse_bad_debt(text: str, month: tuple[int, int] | None) -> dict:
    """Numbers by section, month and row from one report's text.

    Returns {"sections": {"all"|"residential": {"YYYY-MM": {key: value}}}, "problems": [...]}.
    A value of None means the figure is redacted in the public version.
    Rows whose count of figures doesn't match the month columns are left out
    and listed in problems, so a misread never becomes a number on the page.
    """
    lines = text.replace("\r", "").split("\n")
    sections: dict[str, dict[str, dict]] = {}
    problems: list[str] = []
    sec, cols, pending = None, None, ""
    seen: set[str] = set()
    years_line: list[int] = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        low = _norm(line)
        hit = next((k for t, k in SECTIONS if t in low), None)
        if hit:
            sec, pending = hit, ""
            title = next(t for t, k in SECTIONS if k == hit)
            months = _months_in(re.split(re.escape(title), line, maxsplit=1, flags=re.I)[-1])
            j = i + 1
            while not months and j < len(lines) and j <= i + 3:
                months = _months_in(lines[j])
                j += 1
            if not months:
                problems.append(f"{hit}: no month columns found")
                sec = None
                continue
            if all(y for _, y in months):
                cols = [(y, m) for m, y in months]
            elif years_line and len(years_line) == len(months):
                cols = [(y, m) for (m, _), y in zip(months, years_line)]
            elif month and months[-1][0] == month[1]:
                # No years printed: count back from the report's own month,
                # but only when the last column is that month.
                cols = _backward([m for m, _ in months], month)
            else:
                problems.append(f"{hit}: no years for the month columns")
                sec = None
                continue
            sections.setdefault(hit, {})
            seen = set()
            continue
        yrs = _years_in(line)
        if yrs:
            years_line = yrs
            continue
        if sec and SECTION_END.search(line):
            sec = None
            continue
        if not sec:
            continue
        label, vals, dollars = split_row(line)
        if not vals:
            pending = (pending + " " + label).strip() if label and not re.match(r"page \d", low) else ""
            continue
        key = match_label(label) or (match_label(pending + " " + label) if pending else None)
        pending = ""
        if not key:
            continue
        name = ROWS[key]
        if dollars or any(w in key for w in DOLLAR_LABELS) or name in seen:
            # The age buckets come twice, counts then dollars; a spreadsheet
            # copy has no dollar signs, so the second time means dollars.
            name += "_usd"
        seen.add(name)
        if len(vals) != len(cols):
            problems.append(f"{sec}: {key}: {len(vals)} figures for {len(cols)} months")
            continue
        for (y, m), v in zip(cols, vals):
            sections[sec].setdefault(f"{y}-{m:02d}", {})[name] = v
    return {"sections": sections, "problems": problems}


def _reports() -> list[dict]:
    """Stored Docket 42516 bad debt reports with text, oldest first."""
    out = []
    for path in sorted((DATA / "filings").glob("*/*.json")):
        try:
            rec = json.loads(path.read_text())
        except ValueError:
            continue
        if not rec or REPORT_DOCKET not in (rec.get("dockets") or []):
            continue
        if "bad debt" not in (rec.get("description") or "").lower():
            continue
        out.append(rec)
    return sorted(out, key=lambda r: (r.get("filed_date") or "", r["document_id"]))


def collect() -> dict:
    """Build data/household/disconnections.json from every stored report."""
    months: dict[str, dict[str, dict]] = {"all": {}, "residential": {}}
    reports, changes = [], []
    for rec in _reports():
        ym = report_month(*(a["name"] for a in rec["attachments"]), rec.get("description", ""))
        entry = {"document_id": rec["document_id"], "filed_date": rec.get("filed_date"),
                 "description": rec.get("description"),
                 "report_month": f"{ym[0]}-{ym[1]:02d}" if ym else None, "read": [], "problems": []}
        for att in rec["attachments"]:
            if att.get("trade_secret_marked") or not att.get("text_file"):
                if not att.get("trade_secret_marked") and att.get("text") not in (None,):
                    entry["read"].append({"attachment_id": att["attachment_id"], "text": att.get("text")})
                continue
            text = (ROOT / att["text_file"]).read_text()
            parsed = parse_bad_debt(text, ym)
            got = sum(len(v) for v in parsed["sections"].values())
            entry["read"].append({"attachment_id": att["attachment_id"], "text": att.get("text"),
                                  "months": got})
            entry["problems"] += parsed["problems"]
            for sec, by_month in parsed["sections"].items():
                for mon, row in by_month.items():
                    src = {"document_id": rec["document_id"], "attachment_id": att["attachment_id"],
                           "filed_date": rec.get("filed_date")}
                    old = months[sec].get(mon)
                    if old:
                        diff = {k: [old["values"].get(k), v] for k, v in row.items()
                                if k in old["values"] and old["values"][k] != v and v is not None}
                        if diff:
                            changes.append({"section": sec, "month": mon, "from": old["source"],
                                            "to": src, "changed": diff})
                        merged = dict(old["values"])
                        merged.update({k: v for k, v in row.items() if v is not None or k not in merged})
                        months[sec][mon] = {"values": merged, "source": src,
                                            "also_in": old.get("also_in", []) + [old["source"]["document_id"]]}
                    else:
                        months[sec][mon] = {"values": row, "source": src}
        reports.append(entry)
    out = {"built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "docket": REPORT_DOCKET,
           "reports": reports,
           "months": {s: dict(sorted(v.items())) for s, v in months.items()},
           "restated": changes}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    save_json(OUT_DIR / "disconnections.json", out)
    n = sum(len(v) for v in out["months"].values())
    unread = sum(1 for r in reports if not any("months" in a for a in r["read"]))
    print(f"household: {len(reports)} reports, {n} section-months, {unread} reports with no text read yet, "
          f"{len(changes)} restated months, {sum(len(r['problems']) for r in reports)} rows not used")
    return out


# --- Commission web pages: rate survey and gas pricing index -----------------

SURVEY_URL = "https://psc.ga.gov/utilities/electric/residential-rate-survey/"
SURVEY_KWH = 1000
GAS_INDEX_URL = "https://psc.ga.gov/utilities/natural-gas/marketers-pricing-index/"


class _Tags(HTMLParser):
    """Collects tables (as rows of cell text), links, selects and forms."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.links, self.selects, self.forms = [], [], [], []
        self._row = self._cell = self._a = self._sel = self._opt = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "a" and a.get("href"):
            self._a = [a["href"], []]
        elif tag == "form":
            self.forms.append({"action": a.get("action") or "", "method": (a.get("method") or "get").lower(),
                               "id": a.get("id") or "", "fields": {}})
        elif tag == "input" and self.forms and a.get("name"):
            self.forms[-1]["fields"][a["name"]] = a.get("value") or ""
        elif tag == "select":
            self._sel = {"name": a.get("name") or a.get("id") or "", "options": []}
        elif tag == "option" and self._sel is not None:
            self._opt = {"value": a.get("value"), "selected": "selected" in a, "text": []}

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.tables[-1].append(self._row)
            self._row = None
        elif tag == "a" and self._a:
            self.links.append((self._a[0], re.sub(r"\s+", " ", "".join(self._a[1])).strip()))
            self._a = None
        elif tag == "option" and self._opt is not None:
            self._opt["text"] = re.sub(r"\s+", " ", "".join(self._opt["text"])).strip()
            if self._opt["value"] is None:
                self._opt["value"] = self._opt["text"]
            self._sel["options"].append(self._opt)
            self._opt = None
        elif tag == "select" and self._sel is not None:
            self.selects.append(self._sel)
            if self.forms:
                self.forms[-1].setdefault("selects", []).append(self._sel)
            self._sel = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        if self._a is not None:
            self._a[1].append(data)
        if self._opt is not None:
            self._opt["text"].append(data)


def parse_html(data: bytes | str) -> _Tags:
    p = _Tags()
    p.feed(data.decode("utf-8", "replace") if isinstance(data, bytes) else data)
    return p


def _money(s: str) -> float | None:
    m = re.search(r"\$\s*([\d,]+\.\d{2})", s or "")
    return float(m.group(1).replace(",", "")) if m else None


def parse_survey(page: bytes | str) -> dict | None:
    """The survey shown on one rate-survey page: its name, Georgia Power's row and the average."""
    p = parse_html(page)
    name = None
    for s in p.selects:
        chosen = [o for o in s["options"] if o["selected"]]
        if chosen and re.search(r"(summer|winter)\s+20\d\d", chosen[0]["text"], re.I):
            name = chosen[0]["text"]
    for t in p.tables:
        gp = next((r for r in t if r and r[0].lower().startswith("georgia power")), None)
        if not gp:
            continue
        avg = next((r for r in t if r and r[0].lower().startswith("average")), None)
        return {"survey": name, "georgia_power": _money(" ".join(gp[1:2]) or " ".join(gp)),
                "average": _money(" ".join(avg[1:2])) if avg else None,
                "providers": sum(1 for r in t if r and _money(" ".join(r[1:2])) is not None
                                 and not r[0].lower().startswith("average"))}
    return None


def survey_options(page: bytes | str) -> tuple[dict | None, list[dict]]:
    """The survey picker on the page: its form and the surveys it offers."""
    p = parse_html(page)
    for f in p.forms:
        for s in f.get("selects", []):
            opts = [o for o in s["options"] if re.search(r"(summer|winter)\s+20\d\d", o["text"], re.I)]
            if opts:
                return {**f, "select": s["name"]}, opts
    return None, []


def gas_month_links(page: bytes | str) -> list[tuple[str, str]]:
    """(month label, absolute url) for each monthly pricing page the index links to."""
    out, seen = [], set()
    for href, text in parse_html(page).links:
        m = re.fullmatch(r"(January|February|March|April|May|June|July|August|September|October|"
                         r"November|December)\s+(20\d\d)", text.strip())
        if not m:
            continue
        url = urllib.parse.urljoin(GAS_INDEX_URL, href)
        if url not in seen:
            seen.add(url)
            out.append((f"{m.group(2)}-{MONTH_NAMES.index(m.group(1)) + 1:02d}", url))
    return out


def parse_gas_pdf_text(text: str) -> dict:
    """AGL's base charge and the spread of typical marketer bills from one month's table."""
    base = None
    m = re.search(r"base charge[^$]{0,200}?\$\s?([\d,]+\.\d{2})", text, re.I | re.S)
    if m:
        base = float(m.group(1).replace(",", ""))
    therms = None
    m = re.search(r"(\d{2,3})\s*therms", text, re.I)
    if m:
        therms = int(m.group(1))
    bills = []
    for line in text.replace("\r", "").split("\n"):
        vals = re.findall(r"\$\s?([\d,]+\.\d{2})", line)
        name = re.split(r"\s{2,}|\$", line.strip())[0].strip()
        if vals and name and not re.search(r"base charge|note|footnote|average|^\*", name, re.I) \
                and len(name) > 2 and not name[0].isdigit():
            bills.append((name, float(vals[0].replace(",", ""))))
    out = {"agl_base_charge": base, "therms": therms, "marketers": len(bills)}
    if bills:
        lo, hi = min(bills, key=lambda b: b[1]), max(bills, key=lambda b: b[1])
        out.update({"lowest": {"marketer": lo[0], "bill": lo[1]}, "highest": {"marketer": hi[0], "bill": hi[1]}})
    return out


def fetch() -> int:
    """Read the rate survey and the gas pricing index into data/household/."""
    from . import extract
    from .psc import Fetcher
    f = Fetcher(pause=1.0)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Rate survey: the page shows the latest survey; the picker offers the others.
    path = OUT_DIR / "rate-survey.json"
    old = json.loads(path.read_text()) if path.exists() else {"surveys": {}}
    surveys, problems = old.get("surveys", {}), []
    url = f"{SURVEY_URL}?c={SURVEY_KWH}"
    try:
        page = f.get(url)
        got = parse_survey(page)
        if got and got["survey"]:
            surveys[got["survey"]] = {**got, "url": url, "read": now}
        else:
            problems.append("latest survey: table or survey name not found")
        form, opts = survey_options(page)
        if form and form["method"] == "get":
            for o in opts:
                if o["text"] in surveys or o["selected"]:
                    continue
                params = {**form["fields"], form["select"]: o["value"], "c": str(SURVEY_KWH)}
                u = urllib.parse.urljoin(SURVEY_URL, form["action"] or SURVEY_URL) + "?" + urllib.parse.urlencode(params)
                try:
                    got = parse_survey(f.get(u))
                except Exception as ex:
                    problems.append(f"{o['text']}: {type(ex).__name__}")
                    continue
                # Keep it only if the page says it is showing the survey asked for.
                if got and got["survey"] == o["text"]:
                    surveys[o["text"]] = {**got, "url": u, "read": now}
                else:
                    problems.append(f"{o['text']}: page did not show that survey")
        elif opts:
            problems.append(f"earlier surveys: picker form is {form['method'] if form else 'missing'}, not read")
    except Exception as ex:
        problems.append(f"survey page: {type(ex).__name__}")
    save_json(path, {"read": now, "kwh": SURVEY_KWH, "page": SURVEY_URL, "surveys": surveys, "problems": problems})
    print(f"household: {len(surveys)} rate surveys, {len(problems)} problems")

    # Gas pricing index: one page a month, each with the month's table as a PDF.
    path = OUT_DIR / "gas-index.json"
    old = json.loads(path.read_text()) if path.exists() else {"months": {}}
    months, problems = old.get("months", {}), []
    try:
        links = gas_month_links(f.get(GAS_INDEX_URL))
    except Exception as ex:
        links = []
        problems.append(f"index page: {type(ex).__name__}")
    for ym, murl in links:
        if ym in months and months[ym].get("pdf"):
            continue  # a month's table doesn't change once posted; read it once
        try:
            mp = parse_html(f.get(murl))
            pdf = next((urllib.parse.urljoin(murl, h) for h, _ in mp.links if h.lower().split("?")[0].endswith(".pdf")), None)
            if not pdf:
                problems.append(f"{ym}: no table file on the page")
                continue
            data = f.get(pdf, max_bytes=20_000_000)
            text, how = extract.text_for(pdf.split("/")[-1], data)
            got = parse_gas_pdf_text(text or "")
            months[ym] = {**got, "page": murl, "pdf": pdf, "read": now,
                          "sha256": __import__("hashlib").sha256(data).hexdigest()}
        except Exception as ex:
            problems.append(f"{ym}: {type(ex).__name__}")
    save_json(path, {"read": now, "page": GAS_INDEX_URL, "months": dict(sorted(months.items())),
                     "problems": problems})
    print(f"household: {len(months)} gas months, {len(problems)} problems")
    return 0


# --- The page ---------------------------------------------------------------

STYLE = ('<style>.hh h2{margin-top:44px}.hh td.num,.hh th.num{text-align:right;font-variant-numeric:tabular-nums}'
         '.hh .bars{display:flex;align-items:flex-end;gap:2px;height:140px;margin:16px 0 4px;max-width:820px}'
         '.hh .bars span{flex:1;background:var(--amber);min-height:1px}.hh .axis{display:flex;justify-content:space-between;'
         'max-width:820px;font:12px "IBM Plex Mono",monospace;color:var(--muted)}.hh .tc{color:var(--muted)}</style>')
TO_CONFIRM = '<span class="tc">[to confirm]</span>'


def _load(name: str) -> dict:
    p = OUT_DIR / name
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _n(v) -> str:
    if v is None:
        return "redacted"
    return f"{v:,.0f}" if isinstance(v, (int, float)) else e(str(v))


def _mon(ym: str) -> str:
    y, m = ym.split("-")
    return f"{MONTH_NAMES[int(m) - 1][:3]} {y}"


def _doc(site, doc: int, label: str | None = None) -> str:
    return f'<a href="{site.PSC_DOC}{doc}">{e(label or f"Document {doc}")}</a>'


def section_survey(site, data: dict) -> str:
    rows = sorted((data.get("surveys") or {}).values(), key=lambda s: _survey_key(s["survey"]), reverse=True)
    head = (f'<h2 id="bill">What a typical Georgia Power bill costs</h2>'
            f'<p>The Commission\'s Residential Rate Survey prices a month of electricity at '
            f'{SURVEY_KWH:,} kWh for each provider. Summer surveys use July rates and winter surveys use January rates.</p>')
    if not rows:
        return head + f'<p>The survey has not been read into the record yet. {TO_CONFIRM}</p>'
    trs = "".join(f'<tr><td><a href="{e(s["url"])}">{e(s["survey"])}</a></td>'
                  f'<td class="num">{"$%.2f" % s["georgia_power"] if s.get("georgia_power") is not None else TO_CONFIRM}</td>'
                  f'<td class="num">{"$%.2f" % s["average"] if s.get("average") is not None else ""}</td></tr>'
                  for s in rows)
    return head + (f'<table><thead><tr><th>Survey</th><th class="num">Georgia Power, {SURVEY_KWH:,} kWh</th>'
                   f'<th class="num">Average, all providers surveyed</th></tr></thead><tbody>{trs}</tbody></table>'
                   + site.copied_note(f"Copied from the Commission's Residential Rate Survey page ({SURVEY_URL}).",
                                      data.get("read")))


def _survey_key(name: str) -> tuple:
    m = re.search(r"(summer|winter)\s+(20\d\d)", name or "", re.I)
    return (int(m.group(2)), 1 if m.group(1).lower() == "summer" else 0) if m else (0, 0)


def load_bill_changes() -> list[dict]:
    try:
        return json.loads((REFERENCE / "bill-changes.json").read_text()).get("changes", [])
    except (OSError, ValueError):
        return []


def section_changes(site, changes: list[dict]) -> str:
    head = ('<h2 id="changes">Bill changes the Commission approved</h2>'
            '<p>Each line is a change to the typical residential bill at 1,000 kWh as the Commission\'s own order states it, '
            'with the order linked. The parts of the bill (base rates, fuel, storm recovery and other riders) rebuilt from '
            f'the tariffs are not on this page yet. {TO_CONFIRM}</p>')
    if not changes:
        return head
    trs = []
    for c in sorted(changes, key=lambda c: c["effective"], reverse=True):
        amt = c.get("change_1000kwh")
        amt_s = ("+" if amt > 0 else "−") + f"${abs(amt):.2f}" if amt is not None else TO_CONFIRM
        docs = ", ".join(_doc(site, s["document_id"], f'Order, Docket {s["docket"]}') for s in c["sources"])
        trs.append(f'<tr><td>{e(_day(c["effective"]))}</td><td class="num">{amt_s}{" (approx.)" if c.get("approx") else ""}</td>'
                   f'<td>{e(c["what"])}</td><td>{docs}</td></tr>')
    return head + ('<table class="wide"><thead><tr><th>Bills from</th><th class="num">Change a month</th><th>What changed</th>'
                   f'<th>Source</th></tr></thead><tbody>{"".join(trs)}</tbody></table>')


def _day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


SHOW = (("disconnections", "Disconnections for nonpayment"),
        ("reconnections", "Reconnections after disconnection"),
        ("notices", "Disconnection notices"),
        ("past_due", "Accounts 30+ days past due"))


def section_disconnections(site, data: dict) -> str:
    months = (data.get("months") or {}).get("residential") or {}
    head = ('<h2 id="disconnections">Georgia Power residential disconnections</h2>'
            f'<p>Georgia Power files a bad debt report with the Commission each month in '
            f'<a href="{site.PSC_DOCKET}{REPORT_DOCKET}">Docket {REPORT_DOCKET}</a>. These are its residential figures, '
            'month by month. The company\'s reports say figures can change between monthly filings; where a later report '
            'gives a month a different figure, this page uses the later one.</p>')
    if not months:
        n = len(data.get("reports") or [])
        return head + (f'<p>The reports have not been read into the record yet{f" ({n} found)" if n else ""}. {TO_CONFIRM}</p>')
    keys = [m for m in sorted(months) if months[m]["values"].get("disconnections") is not None]
    vals = [months[m]["values"]["disconnections"] for m in keys]
    chart = ""
    if vals and max(vals) > 0:
        top = max(vals)
        bars = "".join(f'<span style="height:{max(1, round(v / top * 100))}%" title="{_mon(m)}: {v:,}"></span>'
                       for m, v in zip(keys, vals))
        chart = (f'<div class="bars" role="img" aria-label="Residential disconnections for nonpayment by month, '
                 f'{_mon(keys[0])} to {_mon(keys[-1])}">{bars}</div>'
                 f'<div class="axis"><span>{_mon(keys[0])}</span><span>{_mon(keys[-1])}</span></div>')
    trs = []
    for m in sorted(months, reverse=True):
        v, src = months[m]["values"], months[m]["source"]
        cells = "".join(f'<td class="num">{_n(v.get(k)) if k in v else ""}</td>' for k, _ in SHOW)
        label = f"Report filed {_day(src['filed_date'])}" if src.get("filed_date") else None
        trs.append(f'<tr><td>{_mon(m)}</td>{cells}<td>{_doc(site, src["document_id"], label)}</td></tr>')
    restated = [c for c in data.get("restated") or [] if c["section"] == "residential"]
    rnote = (f'<p>{len(restated)} month{"s" if len(restated) != 1 else ""} had a figure changed by a later report.</p>'
             if restated else "")
    return head + chart + ('<table class="wide"><thead><tr><th>Month</th>'
                           + "".join(f'<th class="num">{e(t)}</th>' for _, t in SHOW)
                           + f'<th>Source</th></tr></thead><tbody>{"".join(trs)}</tbody></table>' + rnote
                           + site.copied_note("Figures copied from Georgia Power's monthly bad debt reports in Docket 42516.",
                                              data.get("built")))


def section_gas(site, data: dict) -> str:
    months = data.get("months") or {}
    head = ('<h2 id="gas">Natural gas bills in the Atlanta Gas Light area</h2>'
            '<p>Most Atlanta Gas Light customers buy gas from a marketer. Each month the Commission\'s Marketers Pricing Index '
            'lists what a typical customer would pay each marketer, and the Atlanta Gas Light base charge that is part of every bill.</p>')
    rows = [(m, v) for m, v in sorted(months.items(), reverse=True) if v.get("marketers")]
    if not rows:
        return head + f'<p>The pricing index has not been read into the record yet. {TO_CONFIRM}</p>'
    trs = "".join(
        f'<tr><td><a href="{e(v["page"])}">{_mon(m)}</a></td>'
        f'<td class="num">{"$%.2f" % v["agl_base_charge"] if v.get("agl_base_charge") is not None else TO_CONFIRM}</td>'
        f'<td class="num">{"$%.2f" % v["lowest"]["bill"] if v.get("lowest") else ""}</td>'
        f'<td class="num">{"$%.2f" % v["highest"]["bill"] if v.get("highest") else ""}</td>'
        f'<td class="num">{v["marketers"]}</td></tr>' for m, v in rows)
    therms = next((v["therms"] for _, v in rows if v.get("therms")), None)
    return head + ('<table><thead><tr><th>Month</th><th class="num">AGL base charge</th><th class="num">Lowest typical bill</th>'
                   f'<th class="num">Highest typical bill</th><th class="num">Marketers listed</th></tr></thead><tbody>{trs}</tbody></table>'
                   + (f'<p>The index prices a typical customer at {therms} therms a month.</p>' if therms else "")
                   + site.copied_note(f"Copied from the Commission's Marketers Pricing Index ({GAS_INDEX_URL}).", data.get("read")))


def body(site) -> str:
    return ('<div class="hh"><div class="kicker">Bills and disconnections</div>'
            '<h1>What households pay, and how many lose service</h1>'
            '<p class="lede">Georgia Power\'s typical residential bill, the bill changes the Commission approved, '
            'how many Georgia Power residential customers were disconnected for nonpayment each month, and what '
            'natural gas customers pay in the Atlanta Gas Light area. Every figure links to the Commission filing or page it comes from.</p>'
            + section_survey(site, _load("rate-survey.json"))
            + section_changes(site, load_bill_changes())
            + section_disconnections(site, _load("disconnections.json"))
            + section_gas(site, _load("gas-index.json"))
            + '</div>')


def is_live() -> bool:
    try:
        return bool(json.loads((REFERENCE / "household.json").read_text()).get("live"))
    except (OSError, ValueError):
        return False


def write_site() -> Path:
    from . import site
    state = json.loads((DATA / "state.json").read_text()) if (DATA / "state.json").exists() else {}
    site.NIGHTLY_AT, site.STALE = site.copy_status(state)
    out = site.OUT if is_live() else ROOT / "_preview"
    out.mkdir(parents=True, exist_ok=True)
    (out / PAGE).write_text(site.page("Bills and disconnections", body(site), "household", extra_head=STYLE))
    print(f"household: page written to {(out / PAGE).relative_to(ROOT)}"
          + ("" if is_live() else " (preview only: not live until data/reference/household.json says so)"))
    return out / PAGE


def main(argv=None) -> int:
    cmd = (argv or sys.argv[1:] or ["site"])[0]
    if cmd == "collect":
        collect()
    elif cmd == "fetch":
        return fetch()
    elif cmd == "site":
        write_site()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
