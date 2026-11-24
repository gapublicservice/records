"""Build the public bill tracker pages and embeddable widgets.

    python -m legis.site 2025_26        # writes _site/legislature/

Pages:
  legislature/index.html                    every bill in the public scope
  legislature/<session>/<slug>/index.html   one bill: status, text changes, votes, expert views
  legislature/embed/<session>/<slug>/status.html | changes.html | votes.html
                                            each widget alone, for an iframe in Ghost

Strictly c3: facts from the official record, no position, no call to action,
no legislator contact details or links to contact pages. The expert views
panel appears only when views.panel_status() says it may.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
from pathlib import Path

from . import scope, store, textdiff, views
from .service import KNOWN_SESSIONS

e = html.escape
ROOT = store.ROOT
OUT = ROOT / "_site" / "legislature"
CODE_ROOT = Path(__file__).resolve().parent.parent

NEUTRAL = ("This page reports what the General Assembly's own record shows. "
           "Public Service takes no position on any bill.")

STAGES = [  # (label, status codes or words that mark it)
    ("Filed", ("HPF", "SPF", "HH", "SH", "Hopper")),
    ("First reading", ("HFR", "SFR", "First Readers")),
    ("In committee", ("HCFR", "SCFR", "Committee Favorably", "Favorably Reported")),
    ("Passed first chamber", ("HPA", "SPA", "HRA", "SRA", "Passed/Adopted")),
    ("Passed second chamber", ()),
    ("Sent to Governor", ("HSG", "SSG", "Sent to Governor")),
    ("Signed or vetoed", ("HDSG", "SDSG", "Signed by Governor", "Veto", "Act ")),
]

WIDGET_CSS = """
.lt-timeline{list-style:none;margin:12px 0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));border-top:1px solid #111}
.lt-timeline li{padding:10px 8px 10px 0;font-size:14px;color:#5b5b5b;border-top:4px solid #e4e4e4;margin-top:-1px}
.lt-timeline li.done{color:#111;border-top-color:#E8A317}
.lt-timeline li b{display:block;font:500 11px/1.2 "IBM Plex Mono",monospace;letter-spacing:.06em;text-transform:uppercase}
.lt-diff{font:15px/1.7 "IBM Plex Mono",monospace;border:1px solid #e4e4e4;padding:14px;max-height:520px;overflow:auto;background:#fff}
.lt-diff del{background:#fde3df;color:#a3261b}
.lt-diff ins{background:#e2f3e4;color:#1d6b2a;text-decoration:none}
.lt-views{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.lt-views section{border-top:3px solid #111;padding-top:8px}
.lt-view{margin:0 0 16px}
.lt-view blockquote{margin:6px 0;padding-left:12px;border-left:3px solid #e4e4e4}
.lt-context{margin:4px 0 6px;font-size:14px}
.lt-disclosure{border:1px solid #e4e4e4;background:#fafafa;padding:10px 12px;font-size:15px}
@media (max-width:640px){.lt-views{grid-template-columns:1fr}}
.lt-bill{max-width:900px;line-height:1.7}
.lt-bill p{margin:0 0 18px}
.lt-bill .lede{margin:0 0 32px;line-height:1.5}
.lt-bill .kicker{margin-bottom:12px}
.lt-bill h2{margin:64px 0 20px;padding-top:24px;border-top:1px solid #e4e4e4}
.lt-bill h3{margin:28px 0 12px}
.lt-bill details{margin:12px 0 20px}
.lt-bill .lt-timeline{margin:16px 0 24px}
.lt-bill .lt-disclosure{padding:18px 22px;margin:0 0 28px;line-height:1.6}
.lt-bill .lt-views{gap:48px;margin-top:28px}
.lt-bill .lt-views section{padding-top:16px}
.lt-bill .lt-views h3{margin:0 0 24px}
.lt-bill .lt-view{margin:0 0 40px}
.lt-bill .lt-view blockquote{margin:12px 0 14px;padding:2px 0 2px 18px;font-size:18px;line-height:1.55}
.lt-bill .lt-context{margin:0 0 10px;line-height:1.55}
.lt-bill .lt-src{margin:0;font-size:14px;line-height:1.5}
@media (max-width:640px){.lt-bill h2{margin-top:48px}.lt-bill .lt-views{gap:8px}}
"""


# The shared footer describes the Commission's records; bill pages come from elsewhere.
COMMISSION_SOURCE = "Records are copied each night from the Commission's public site; each one links to the original."
BILL_SOURCE = ("Bill records come from the Georgia General Assembly's site (legis.ga.gov) and LegiScan, "
               "updated nightly and every two hours during session; each bill links to its General Assembly page.")


def _page(title: str, body: str, depth: int) -> str:
    try:  # inside the records repository, use its frame
        sys.path.insert(0, str(CODE_ROOT))
        from harvester.site import page  # type: ignore
        html_out = page(title, f"<style>{WIDGET_CSS}</style>{body}", on="legislature", depth=depth)
        return html_out.replace(COMMISSION_SOURCE, BILL_SOURCE)
    except Exception:
        up = "../" * depth
        return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{e(title)} · Public Service record</title>'
                f'<link rel="stylesheet" href="{up}style.css"><style>{WIDGET_CSS}</style></head>'
                f'<body><main>{body}</main></body></html>')


def _embed(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>'
            f'<style>body{{margin:0;font:16px/1.55 "Space Grotesk",system-ui,sans-serif;color:#111}}'
            f'{WIDGET_CSS}</style></head><body>{body}</body></html>')


def stage_of(bill: dict) -> int:
    hist = bill.get("status_history", [])
    reached = 0
    chambers_passed = set()
    for h in hist:
        code, act = h.get("code") or "", h.get("action") or ""
        if code in ("HPA", "HRA") or ("House" in act and "Passed" in act):
            chambers_passed.add("H")
        if code in ("SPA", "SRA") or ("Senate" in act and "Passed" in act):
            chambers_passed.add("S")
        for i, (_, marks) in enumerate(STAGES):
            if any(m == code or (len(m) > 4 and m in act) for m in marks):
                reached = max(reached, i)
    if len(chambers_passed) == 2:
        reached = max(reached, 4)
    return reached


def status_widget(bill: dict) -> str:
    st = stage_of(bill)
    items = "".join(f'<li class="{"done" if i <= st else ""}"><b>{i + 1}</b>{e(lab)}</li>'
                    for i, (lab, _) in enumerate(STAGES))
    hist = bill.get("status_history", [])
    last = hist[-1] if hist else None
    latest = (f'<p><span class="kicker">Latest action</span><br><span class="mono">{e((last["date"] or "")[:10])}</span> '
              f'{e(last["action"])}</p>') if last else ""
    comm = ", ".join(f'{e(c["name"])} ({e(str(c.get("chamber") or ""))})' for c in bill.get("committees", []))
    rows = "".join(f'<tr><td class="mono">{e((h["date"] or "")[:10])}</td><td>{e(h["action"])}</td></tr>'
                   for h in reversed(hist))
    return (f'<div class="lt-status"><ol class="lt-timeline">{items}</ol>{latest}'
            + (f'<p><span class="kicker">Committee</span><br>{comm}</p>' if comm else "")
            + f'<details><summary>Full status history</summary><table><tbody>{rows}</tbody></table></details></div>')


def changes_widget(bill: dict) -> str:
    d = store.sess_dir(bill["session"]) / "compare" / bill["slug"]
    comps = [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.exists() else []
    versions = store.ordered_versions(bill)
    vlist = "".join(f'<li><a href="{e(v["url"])}">{e(v["label"] or str(v["doc_id"]))}</a></li>' for v in versions)
    out = [f'<p class="kicker">Versions ({len(versions)})</p><ul>{vlist}</ul>' if versions else
           '<p class="muted">No version of the text is posted yet.</p>']
    for c in comps:
        lines = "".join(f"<li>{e(x)}</li>" for x in textdiff.summary_lines(c["summary"]))
        out.append(f'<h3>{e(c["from"]["label"])} → {e(c["to"]["label"])}</h3><ul>{lines}</ul>'
                   f'<details><summary>Word-by-word comparison</summary><div class="lt-diff">{c["html"]}</div></details>')
    amends = [v for v in versions if store.is_floor_amendment(v)]
    if amends:
        out.append('<p class="muted">Floor amendments are shown as their own documents above; the next full '
                   'version of the bill carries their changes into the comparison.</p>')
    return "".join(out)


def votes_widget(bill: dict) -> str:
    vs = bill.get("votes", [])
    if not vs:
        return '<p class="muted">No recorded roll-call votes yet.</p>'
    rows = "".join(
        f'<tr><td class="mono">{e((v["date"] or "")[:10])}</td><td>{e(str(v["chamber"] or ""))}</td>'
        f'<td>{e(v["motion"] or v["roll_call"])}</td><td class="num">{v["yea"]}</td><td class="num">{v["nay"]}</td>'
        f'<td class="num">{(v["not_voting"] or 0) + (v["excused"] or 0)}</td></tr>'
        for v in sorted(vs, key=lambda v: v["date"] or ""))
    return ('<table><thead><tr><th>Date</th><th>Chamber</th><th>Motion</th><th class="num">Yea</th>'
            f'<th class="num">Nay</th><th class="num">Not voting or excused</th></tr></thead><tbody>{rows}</tbody></table>')


_MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]


def _ap_date(iso: str) -> str:
    """2025-02-10 -> Feb. 10, 2025 (AP style). Anything else is shown as it came."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    return f"{_MONTHS[int(m[2]) - 1]} {int(m[3])}, {m[1]}" if m else str(iso or "")


def _member(name: str) -> str:
    """'Hufstetler, Chuck 52nd' -> 'Chuck Hufstetler (52nd)'. Anything else is shown as it came."""
    m = re.fullmatch(r"\s*([^,]+),\s*(.+?)\s+(\d+(?:st|nd|rd|th))\s*", name or "")
    return f"{m[2]} {m[1]} ({m[3]})" if m else (name or "")


# Paul approved the intro Nov 24. NONE_YET is still a draft (views.EMPTY_SIDE_LINE_APPROVED).
VIEWS_INTRO = "Quoted from public sources and checked against them. Both sides are shown when both have one."
NONE_YET = {
    "for": "No view in support that meets our standards has been found yet. Others will be added as they're published.",
    "against_or_concerns": "No view against this bill or raising concerns that meets our standards has been found yet. Others will be added as they're published.",
}


def views_widget(bill: dict) -> str:
    st = views.panel_status(views.load_panel(bill["session"], bill["slug"]))
    if st["state"] != "live":
        return f'<p class="muted">{e(st["note"])}</p>' if st["note"] else ""
    cols = []
    titles = {"for": "Views in support", "against_or_concerns": "Views against or raising concerns"}
    for side in views.SIDES:
        items = []
        for v in st["views"]:
            if v["side"] != side:
                continue
            link = v["source_url"]
            if v.get("video"):
                from .video import moment_link
                meta = json.loads((views.VIDEO / str(v["video"]["id"]) / "meta.json").read_text())
                link = moment_link(meta, int(v["video"]["start_seconds"]))
            items.append(f'<div class="lt-view"><b>{e(v["who"])}</b>, {e(v["role"])}'
                         f'<blockquote>{e(v["quote"])}</blockquote>'
                         + (f'<p class="muted lt-context">{e(v["context"])}</p>' if v.get("context") else "") +
                         f'<p class="lt-src"><a href="{e(link)}" title="{e(v["source_title"])}">{e(v.get("source_label") or v["source_title"])}</a>'
                         f' · {e(_ap_date(v["source_date"]))}</p></div>')
        if not items:
            items.append(f'<p class="muted lt-none">{e(NONE_YET[side])}</p>')
        cols.append(f'<section><h3>{titles[side]}</h3>{"".join(items)}</section>')
    panel = views.load_panel(bill["session"], bill["slug"]) or {}
    disclosure = (f'<p class="lt-disclosure">{e(panel["disclosure"])}</p>' if panel.get("disclosure") else "")
    return (disclosure + f'<p class="muted">{e(VIEWS_INTRO)}</p>'
            f'<div class="lt-views">{"".join(cols)}</div>')


def bill_page(bill: dict) -> str:
    names = [_member(s["name"]) for s in sorted(bill.get("sponsors", []), key=lambda s: s.get("order") or 0)
             if s.get("name")]
    if len(names) > 1:
        more = len(names) - 1
        sponsors = (f'<p>Sponsor: {e(names[0])} and {more} co-sponsor{"s" if more != 1 else ""}</p>'
                    f'<details><summary>Show all sponsors</summary><p>{e(", ".join(names))}</p></details>')
    elif names:
        sponsors = f'<p>Sponsor: {e(names[0])}</p>'
    else:
        sponsors = ""
    why = " · ".join(scope.RULES_SHORT[r] for r in bill.get("scope", []))
    vw = views_widget(bill)
    body = (f'<p class="kicker">{e(KNOWN_SESSIONS.get(bill["session"], {}).get("label", bill["session"]))}</p>'
            f'<h1>{e(bill["key"])}</h1><p class="lede">{e(bill["caption"])}</p>'
            + sponsors
            + (f'<p class="muted">Why it\'s tracked: {e(why)}</p>' if why else "")
            + f'<h2>Status</h2>{status_widget(bill)}'
            + f'<h2>What changed in the text</h2>{changes_widget(bill)}'
            + f'<h2>Votes</h2>{votes_widget(bill)}'
            + (f'<h2>Expert views</h2>{vw}' if vw else "")
            + (f'<h2>Summary from the General Assembly</h2><details class="lt-summary"><summary>Show the summary</summary>'
               f'<p>{e(bill["summary"])}</p></details>' if bill.get("summary") else "")
            + f'<p class="muted"><a href="{e(bill["page"])}">Full record on the General Assembly\'s site</a>'
            + ("" if "lt-disclosure" in vw else f'. {NEUTRAL}') + '</p>')
    # Paul, Nov 23: pages that carry a sponsor's priority disclosure drop the no-position line.
    return _page(bill["key"], f'<div class="lt-bill">{body}</div>', depth=3)


def index_page(session: str, bills: list[dict]) -> str:
    rows = []
    for b in sorted(bills, key=lambda b: (b["document_type"] or "", b["number"] or 0)):
        hist = b.get("status_history", [])
        last = hist[-1] if hist else {"date": "", "action": ""}
        rows.append(f'<tr><td class="mono"><a href="{session}/{b["slug"]}/">{e(b["key"])}</a></td>'
                    f'<td>{e(b["caption"][:220])}</td><td class="mono">{e((last["date"] or "")[:10])}</td>'
                    f'<td>{e(last["action"])}</td></tr>')
    body = (f'<p class="kicker">Georgia General Assembly</p><h1>Bills on utilities, the PSC and elections</h1>'
            f'<p class="lede">Every bill that amends Georgia\'s public utility law, names the Public Service '
            f'Commission, goes to a utilities committee, or changes statewide election law. {len(bills)} bills.</p>'
            f'<table><thead><tr><th>Bill</th><th>Caption</th><th>Last action</th><th></th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table><p class="muted">{NEUTRAL}</p>')
    return _page("Bills", body, depth=1)


def _latest_text(bill: dict) -> str:
    if not bill.get("versions"):
        return ""
    last = store.ordered_versions(bill)[-1]
    p = store.version_path(bill["session"], bill["slug"], last["doc_id"])
    return p.read_text() if p.exists() else ""


def build(session: str) -> int:
    # Scope is worked out again from the current rule, so a change to
    # legis/scope.py shows on the site at once, not after the next full pass.
    bills = []
    for b in store.all_bills(session):
        b["scope"] = scope.reasons(b, _latest_text(b))
        if b["scope"]:
            bills.append(b)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(index_page(session, bills))
    for b in bills:
        d = OUT / session / b["slug"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(bill_page(b))
        ed = OUT / "embed" / session / b["slug"]
        ed.mkdir(parents=True, exist_ok=True)
        (ed / "status.html").write_text(_embed(f'{b["key"]} status', status_widget(b)))
        (ed / "changes.html").write_text(_embed(f'{b["key"]} text changes', changes_widget(b)))
        (ed / "votes.html").write_text(_embed(f'{b["key"]} votes', votes_widget(b)))
    # A public, machine-readable copy of the tracked bills for anyone to reuse.
    store.write_json(OUT / "bills.json", [{k: b.get(k) for k in (
        "key", "session", "page", "caption", "scope", "sponsors", "committees", "status_history",
        "versions")} for b in bills])
    print(f"{len(bills)} bill pages")
    return 0


if __name__ == "__main__":
    sys.exit(build(sys.argv[1] if len(sys.argv) > 1 else "2025_26"))
