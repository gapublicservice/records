"""The wire: a short running list of what just happened at the Commission.

It holds up to MAX_ITEMS items from the last WINDOW_DAYS days. Filings go in on
their own after each harvest. Statements go in only after a person approves
them and adds them to data/reference/wire-statements.json; the public form at
send-a-quote.html only sends them in for review.

Source priority (Paul's picks, Nov 23-24): Commission orders and actions first,
then commissioners, then utilities, then Commission staff, then every other
party of record. Priority decides only which items drop off when there are more
than MAX_ITEMS; the list itself shows newest first, each item labeled by source.

Each entry in wire-statements.json, added by hand once approved:
    {"id": "s-2026-11-24-hubbard", "approved": true, "date": "2026-11-24",
     "source": "commissioner" | "commission" | "staff" | "utility" | "party",
     "who": "Name, title", "quote": "Short quote, as said", "url": "https://... full statement",
     "dockets": [57171]}

Flags go to a Netlify form for review. A flagged item stays up until it is
decided, so nothing here hides items.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATEMENTS = ROOT / "data" / "reference" / "wire-statements.json"
SITE = "https://records.gapublicservice.org"
PSC_DOC = "https://psc.ga.gov/search/facts-document/?documentId="
FORMS = "https://gapublicservice-follow.netlify.app"

MAX_ITEMS = 50
SHOWN = 10
WINDOW_DAYS = 7

COMMISSION, COMMISSIONER, UTILITY, STAFF, PARTY = range(5)
LABEL = {COMMISSION: "Commission", COMMISSIONER: "Commissioner", STAFF: "Commission staff",
         UTILITY: "Utility", PARTY: "Party"}
_COMMISSION = re.compile(r"^(GPSC|Hearing Officer|Georgia Public Service Commission|Commission)\b", re.I)
_UTILITY = re.compile(r"Georgia Power|Atlanta Gas Light|Liberty Utilities|\bEMC\b|Electric Membership|"
                      r"\bMEAG\b|Municipal Electric Authority|Georgia Transmission|Oglethorpe Power|"
                      r"Southern Company|Gas Department|Natural Gas System", re.I)
_ORDER = re.compile(r"\border\b", re.I)

e = lambda s: html.escape(str(s), quote=True)  # noqa: E731


def source_of(company: str | None) -> int:
    c = (company or "").strip()
    if _COMMISSION.match(c):
        return COMMISSION
    if c.lower() == "staff" or c.lower().startswith("commission staff"):
        return STAFF
    if _UTILITY.search(c):
        return UTILITY
    return PARTY


def filing_item(r: dict) -> dict:
    src = source_of(r.get("company"))
    kind = "Order" if src == COMMISSION and _ORDER.search(r.get("description") or "") else "Filing"
    return {"id": f"f{r['document_id']}", "date": r.get("filed_date") or "", "rank": src,
            "source": LABEL[src], "kind": kind, "who": (r.get("company") or "No filer named").strip(),
            "what": " ".join((r.get("description") or "(no description)").split()),
            "dockets": r.get("dockets") or [], "url": f"{PSC_DOC}{r['document_id']}", "order": r["document_id"]}


def load_statements() -> list[dict]:
    if not STATEMENTS.exists():
        return []
    out = []
    for i, s in enumerate(json.loads(STATEMENTS.read_text())):
        if not s.get("approved"):
            continue
        rank = {"commission": COMMISSION, "commissioner": COMMISSIONER, "staff": STAFF,
                "utility": UTILITY}.get(s.get("source"), PARTY)
        out.append({"id": s.get("id") or f"s{i}", "date": s["date"], "rank": rank, "source": LABEL[rank],
                    "kind": "Statement", "who": s["who"], "what": s["quote"], "dockets": s.get("dockets") or [],
                    "url": s["url"], "order": i})
    return out


def items(rows: list[dict], today: str, statements: list[dict] | None = None) -> list[dict]:
    """Up to MAX_ITEMS items, newest first. When more qualify, lower priority drops first."""
    since = (dt.date.fromisoformat(today) - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    pool = [filing_item(r) for r in rows if since <= (r.get("filed_date") or "") <= today]
    pool += [s for s in (load_statements() if statements is None else statements) if since <= s["date"] <= today]
    # Higher priority survives first; within a rank, newer survives.
    keep = sorted(pool, key=lambda x: (x["rank"], _neg(x["date"]), -x["order"]))[:MAX_ITEMS]
    return sorted(keep, key=lambda x: (x["date"], x["kind"] == "Statement", x["order"]), reverse=True)


def _neg(day: str) -> int:
    return -int(day.replace("-", "") or 0)


def _day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%a} {d:%b} {d.day}"


LAG = ("We copy the Commission's site each night at about 3 AM Eastern and look for new filings again "
       "at about noon on weekdays, so a filing posted in the afternoon shows up here the next morning. "
       "The Commission's own page is the one to rely on.")


def as_json(its: list[dict], note: str) -> dict:
    return {"page": f"{SITE}/wire.html", "send": f"{SITE}/send-a-quote.html", "shown": SHOWN, "note": note,
            "items": [{k: v for k, v in x.items() if k not in ("rank", "order")} |
                      {"day": _day(x["date"]), "flag": f"{SITE}/flag.html?item={x['id']}",
                       "docket_pages": [f"{SITE}/docket/{d}/" for d in x["dockets"]]} for x in its]}


def item_html(x: dict, up: str = "") -> str:
    dk = " ".join(f'<a class="mono" href="{up}docket/{d}/">{d}</a>' for d in x["dockets"])
    quote = x["kind"] == "Statement"
    what = f"“{e(x['what'])}”" if quote else e(x["what"])
    return (f'<li class="wi" id="{e(x["id"])}"><div class="wi-top mono"><span>{e(_day(x["date"]))}</span>'
            f'<span class="wi-src s{x["rank"]}">{e(x["source"])}</span>'
            f'{"<span class=wi-kind>" + e(x["kind"]) + "</span>" if x["kind"] != "Filing" else ""}{dk}</div>'
            f'<a class="wi-what" href="{e(x["url"])}">{what}</a>'
            f'<span class="wi-by muted">{e(x["who"])}</span>'
            f'<a class="wi-flag" href="{up}flag.html?item={e(x["id"])}" target="_self" '
            f'title="Tell us something is wrong with this item">Flag</a></li>')


def page_body(its: list[dict], note: str) -> str:
    lis = "".join(item_html(x) for x in its) or '<li class="muted">Nothing new in the last week.</li>'
    return f"""<div class="kicker">Georgia Public Service Commission</div>
<h1>The wire</h1>
<p class="lede">What just happened at the Commission: orders, filings and statements from the last week, newest first.</p>
<p class="muted">Up to {MAX_ITEMS} items. When more than that come in, filings from the Commission itself stay first, then commissioners, utilities, Commission staff and other parties. Filings go in on their own each night and at midday. Statements go in only after a person checks them.</p>
<ol class="wire" style="--shown:{SHOWN}" tabindex="0" aria-label="The wire, newest first">{lis}</ol>
<p class="wire-send"><strong>Have a statement or quote about a Commission matter?</strong> <a href="send-a-quote.html">Send it in</a>. Something wrong with an item? Use its Flag link.</p>
<p class="muted copied">{e(note)}</p>"""


def send_page() -> str:
    return f"""<div class="kicker"><a href="wire.html">The wire</a></div>
<h1>Send a statement or quote</h1>
<p class="lede">Said something on the record about a Commission matter? Send it here for the wire.</p>
<p>A person reads every submission before anything goes up. We post a short quote with who said it, the date and a link to the full statement, never a whole press release. Statements from every side go in by the same rule. Campaign statements aren't posted. Your email is only for questions about your submission and is never published.</p>
<form class="ev-form" name="wire-statement" method="POST" action="{FORMS}/quote-thanks/">
<input type="hidden" name="form-name" value="wire-statement">
<p class="hp" aria-hidden="true"><label>Leave this empty <input name="bot-field" tabindex="-1" autocomplete="off"></label></p>
<label>Who said it <span class="muted">(name and title)</span> <input name="who" required maxlength="140"></label>
<label>Organization <input name="organization" maxlength="140"></label>
<label>Date it was said or published <input type="date" name="date" required></label>
<label>The quote <span class="muted">(up to 300 characters, exactly as said)</span> <textarea name="quote" required maxlength="300" rows="3"></textarea></label>
<label>Link to the full statement <input type="url" name="link" required placeholder="https://"></label>
<label>Docket number, if there is one <input name="docket" inputmode="numeric" maxlength="12"></label>
<label>Your name <input name="sender" required maxlength="140"></label>
<label>Your email <span class="muted">(never published)</span> <input type="email" name="contact" required maxlength="200"></label>
<p><button type="submit" class="pin-follow">Send for review</button></p>
</form>"""


def flag_page() -> str:
    return f"""<div class="kicker"><a href="wire.html">The wire</a></div>
<h1>Flag an item</h1>
<p class="lede">Tell us what's wrong with an item on the wire.</p>
<p>A person reads every flag. The item stays up while we check it, and if we change it, the fix is noted. Your email is optional, only for questions, and never published.</p>
<form class="ev-form" name="wire-flag" method="POST" action="{FORMS}/flag-thanks/">
<input type="hidden" name="form-name" value="wire-flag">
<p class="hp" aria-hidden="true"><label>Leave this empty <input name="bot-field" tabindex="-1" autocomplete="off"></label></p>
<label>Item <input name="item" id="flag-item" required maxlength="40" readonly></label>
<p class="muted" id="flag-what"></p>
<label>What's wrong <select name="reason" required>
<option value="">Choose one</option><option>Wrong or garbled title</option><option>Wrong source or date</option>
<option>Quote is wrong or out of context</option><option>Duplicate</option><option>Shouldn't be public</option><option>Something else</option>
</select></label>
<label>Details <textarea name="details" maxlength="800" rows="4"></textarea></label>
<label>Your email <span class="muted">(optional, never published)</span> <input type="email" name="contact" maxlength="200"></label>
<p><button type="submit" class="pin-follow">Send flag</button></p>
</form>
<script>(function(){{var id=new URLSearchParams(location.search).get('item')||'';if(!/^[a-z0-9-]{{1,40}}$/.test(id))id='';
var f=document.getElementById('flag-item');f.value=id;if(!id){{f.readOnly=false;f.placeholder='Item number';return}}
fetch('data/wire.json').then(function(r){{return r.json()}}).then(function(j){{var x=(j.items||[]).find(function(i){{return i.id===id}});
if(x)document.getElementById('flag-what').textContent=x.day+' · '+x.who+' · '+x.what}}).catch(function(){{}})}})();</script>"""
