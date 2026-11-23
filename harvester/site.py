"""Build the public tracker website from the record.

    python -m harvester.site            # writes _site/

Static pages only: a search over every filing, one page per docket, the
latest night's filings, the regional picture and an About page. The search
runs in the reader's browser over _site/data/filings.json, so the site needs
no server. Every filing links to the Commission's own page.
"""

from __future__ import annotations

import collections
import datetime as dt
import html
import json
import re
import shutil
from pathlib import Path

from . import ics, infrastructure
from .run import DATA, ROOT

OUT = ROOT / "_site"
SRC = ROOT / "site"
PSC_DOC = "https://psc.ga.gov/search/facts-document/?documentId="
PSC_DOCKET = "https://psc.ga.gov/search/facts-docket/?docketId="

INDEPENDENCE = ("Public Service is an independent project. It is not a product of the Georgia "
                "Public Service Commission, and the Commission does not run or endorse it. "
                "The Commission's own record is at psc.ga.gov.")
# Footer on every records page: Paul's wording, picked Nov 23, 2026.
FOOTER = ("Public Service Records is a project of Paul Glaze, produced in his work with "
          "Georgia Conservation Voters and the GCV Education Fund. It is independent and is "
          "not a work product of the Georgia Public Service Commission. Public Service Records "
          "was produced with standard APIs, GitHub, and Claude. The writing is all original.")
SPONSOR = "Sponsored by the Georgia Conservation Voters Education Fund (GCVEF)."
# Paul's own climate line for the About page, in his words. Empty until he writes it;
# when set, it appears right under the About page's opening line.
CLIMATE_LINE = ""

e = html.escape

PSC_FILE = "https://services.psc.ga.gov/api/v1/External/Public/Get/Document/DownloadFile/{doc}/{att}"
# Plain, general reasons a filing has no file to download. They describe the kind of
# entry, never the party, and they must stay the same in the page and in SEARCH_JS.
FILE_NOTES = {
    "none": ("No file posted",
             "The Commission's page for this entry doesn't list a file to download. Some entries "
             "are notices or record-only entries, and sometimes a file is added later."),
    "confidential": ("Confidential",
                     "Every file listed for this entry is marked as a trade secret, which the "
                     "Commission keeps out of public view, so there is nothing public to download. "
                     "When a public version is filed, it usually appears as its own entry."),
    "unconfirmed": ("File not reached",
                    "The Commission lists a file here, but our last attempt to download it failed. "
                    "That is often temporary and the record tries again. The Commission's own page "
                    "may still offer it."),
    "more_confidential": ("{n} confidential",
                          "This entry also lists {n} file{s} marked as a trade secret. Those are kept "
                          "out of public view and can't be downloaded."),
}
STATE_CODE = {"available": 0, "none": 1, "confidential": 2, "unconfirmed": 3}


def _why(label: str, text: str) -> str:
    return (f'<button type="button" class="file no" aria-label="{e(label)}: why">{e(label)}'
            f'<span class="why" role="tooltip">{e(text)}</span></button>')


def file_marker(doc_id: int, files: dict | None) -> str:
    """The download line under a filing: a link to the file, or why there isn't one."""
    if not files:
        return ""
    state, public, conf = files["state"], files.get("public") or [], files.get("confidential", 0)
    if state == "available":
        if len(public) == 1:
            out = (f'<a class="file ok" href="{PSC_FILE.format(doc=doc_id, att=public[0])}">'
                   'Download file</a>')
        else:
            out = f'<a class="file ok" href="{PSC_DOC}{doc_id}">{len(public)} files to download</a>'
        if conf:
            lab, txt = FILE_NOTES["more_confidential"]
            out += _why(lab.format(n=conf), txt.format(n=conf, s="" if conf == 1 else "s"))
        return out
    return _why(*FILE_NOTES[state])


# Links that leave the site (the Commission's pages and files, the public
# repo) open in a new tab, so the record stays open behind them. The site's
# own navigation stays in the same tab. Applied to the finished page, so it
# also covers the links the search script builds.
_EXTERNAL = re.compile(r'<a (?![^>]*target=)([^>]*?)href="https://')


def external_new_tab(markup: str) -> str:
    return _EXTERNAL.sub(r'<a \1target="_blank" rel="noopener" href="https://', markup)


def page(title: str, body: str, on: str, depth: int = 0, extra_head: str = "") -> str:
    return external_new_tab(_page(title, body, on, depth, extra_head))


def _page(title: str, body: str, on: str, depth: int = 0, extra_head: str = "") -> str:
    up = "../" * depth
    nav = [("index.html", "Search", "search"), ("dockets.html", "Dockets", "dockets"),
           ("calendar.html", "Calendar", "calendar"), ("today.html", "Last night", "today"),
           ("regions.html", "Regions", "regions"), ("legislature/index.html", "Legislature", "legislature"),
           ("about.html", "About", "about")]
    links = "".join(f'<a href="{up}{h}" class="{"on" if k == on else ""}">{t}</a>' for h, t, k in nav)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} · Public Service record</title>
<meta name="description" content="Every public filing at the Georgia Public Service Commission, searchable. An independent project.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Space+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{up}style.css">{extra_head}
</head><body>
<div class="ps-top"><a target="_self" href="https://www.gapublicservice.org/"><span class="dot"></span><span>From <b>Public Service</b><span class="more"> · the newsletter, sessions and explainers</span></span><span class="go">Visit<span class="more"> the site</span> ↗</span></a></div>
<header class="site"><div class="bar">
<a class="name" href="{up}index.html"><span>Public<br>Service<small>The record</small></span><span class="dot"></span></a>
<nav>{links}</nav></div></header>
<main>{body}</main>
<footer class="site"><div class="bar">
<p><strong>{e(FOOTER)}</strong></p>
<p>{e(SPONSOR)} Records are copied each night from the Commission's public site; each one links to the original.</p>
<p class="mono">Built {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC · data and code: <a href="https://github.com/gapublicservice/records">github.com/gapublicservice/records</a></p>
</div></footer>
<script>document.addEventListener('click',function(v){{var b=v.target.closest('.file.no');document.querySelectorAll('.file.no.open').forEach(function(x){{if(x!==b)x.classList.remove('open')}});if(b)b.classList.toggle('open')}});document.addEventListener('keydown',function(v){{if(v.key==='Escape')document.querySelectorAll('.file.no.open').forEach(function(x){{x.classList.remove('open')}})}});</script>
</body></html>
"""


def load():
    rows = [json.loads(l) for l in (DATA / "index" / "filings.jsonl").open()]
    dockets = json.loads((DATA / "index" / "dockets.json").read_text())
    return rows, dockets


def filing_row(r: dict, depth: int, show_docket: bool = True) -> str:
    up = "../" * depth
    dk = " ".join(f'<a href="{up}docket/{d}/" class="mono">{d}</a>' for d in r["dockets"]) or '<span class="muted">none</span>'
    tags = "".join(f'<span class="tag">{e(u)}</span>' for u in r["units"])
    tags += "".join(f'<span class="tag">{e(c)} County</span>' for c in r["counties_in_title"])
    tags += "".join(f'<span class="tag dis">{e(x)}</span>' for x in r["disagreement"])
    cells = [f'<td class="mono">{e(r.get("filed_date") or "")}</td>']
    if show_docket:
        cells.append(f"<td>{dk}</td>")
    cells.append(f'<td>{e(r.get("company") or "No filer named")}</td>')
    cells.append(f'<td><a href="{PSC_DOC}{r["document_id"]}">{e((r.get("description") or "").strip() or "(no description)")}</a><br>{file_marker(r["document_id"], r.get("files"))}{tags}</td>')
    return "<tr>" + "".join(cells) + "</tr>"


def docket_meta(d) -> dict:
    p = DATA / "dockets" / f"{d}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def docket_title(rows: list[dict], d=None) -> str:
    meta = docket_meta(d) if d is not None else {}
    if meta.get("title"):
        return meta["title"]
    if not rows:
        return ""
    dated = sorted((r for r in rows if r.get("filed_date")), key=lambda r: (r["filed_date"], r["document_id"]))
    first = dated[0] if dated else rows[0]
    return (first.get("description") or "").strip()


def build_search_data(rows):
    units = sorted({u for r in rows for u in r["units"]})
    regions = sorted({g for r in rows for g in r["regions"]})
    compact = []
    for r in rows:
        compact.append([r["document_id"], r.get("filed_date") or "", r.get("company") or "",
                        r["dockets"], (r.get("description") or "").strip(),
                        [units.index(u) for u in r["units"]],
                        [regions.index(g) for g in r["regions"]],
                        r["counties_in_title"], 1 if r["disagreement"] else 0,
                        file_compact(r.get("files"))])
    return {"units": units, "regions": regions, "notes": FILE_NOTES, "filings": compact}


def file_compact(files: dict | None) -> list:
    if not files:
        return []
    return [STATE_CODE[files["state"]], files.get("public") or [], files.get("confidential", 0)]


SEARCH_JS = r"""
(async function(){
 const $=s=>document.querySelector(s);
 const res=await fetch('data/filings.json'); const D=await res.json();
 const U=D.units, G=D.regions, F=D.filings.sort((a,b)=>b[1].localeCompare(a[1])||b[0]-a[0]);
 const fill=(sel,arr,label)=>{sel.innerHTML='<option value="">'+label+'</option>'+arr.map((x,i)=>'<option value="'+i+'">'+x+'</option>').join('')};
 fill($('#unit'),U,'Any staff unit'); fill($('#region'),G,'Any region');
 const years=[...new Set(F.map(f=>f[1].slice(0,4)).filter(Boolean))].sort().reverse();
 $('#year').innerHTML='<option value="">Any year</option>'+years.map(y=>'<option>'+y+'</option>').join('');
 const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
 const N=D.notes, ST=['available','none','confidential','unconfirmed'];
 const why=(l,t)=>'<button type="button" class="file no" aria-label="'+esc(l)+': why">'+esc(l)+'<span class="why" role="tooltip">'+esc(t)+'</span></button>';
 function file(f){
  const x=f[9]; if(!x||!x.length)return '';
  const st=ST[x[0]], pub=x[1], conf=x[2];
  if(st!=='available')return why(N[st][0],N[st][1]);
  let o=pub.length===1?'<a class="file ok" href="https://services.psc.ga.gov/api/v1/External/Public/Get/Document/DownloadFile/'+f[0]+'/'+pub[0]+'">Download file</a>'
   :'<a class="file ok" href="https://psc.ga.gov/search/facts-document/?documentId='+f[0]+'">'+pub.length+' files to download</a>';
  if(conf)o+=why(N.more_confidential[0].replace('{n}',conf),N.more_confidential[1].replace('{n}',conf).replace('{s}',conf===1?'':'s'));
  return o;
 }
 if($('#hasfile'))$('#hasfile').addEventListener('change',()=>run());
 let shown=0, hits=[];
 function row(f){
  const dk=f[3].map(d=>'<a class="mono" href="docket/'+d+'/">'+d+'</a>').join(' ')||'<span class="muted">none</span>';
  let tags=f[5].map(i=>'<span class="tag">'+esc(U[i])+'</span>').join('')+f[7].map(c=>'<span class="tag">'+esc(c)+' County</span>').join('');
  if(f[8]) tags+='<span class="tag dis">disagreement</span>';
  return '<tr><td class="mono">'+esc(f[1])+'</td><td>'+dk+'</td><td>'+esc(f[2]||'No filer named')+'</td><td><a href="https://psc.ga.gov/search/facts-document/?documentId='+f[0]+'">'+esc(f[4]||'(no description)')+'</a><br>'+file(f)+tags+'</td></tr>';
 }
 function run(){
  const q=$('#q').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const u=$('#unit').value, g=$('#region').value, y=$('#year').value, dis=$('#dis').checked, hf=$('#hasfile')&&$('#hasfile').checked;
  hits=F.filter(f=>{
   if(u!==''&&!f[5].includes(+u))return false;
   if(g!==''&&!f[6].includes(+g))return false;
   if(y&&!f[1].startsWith(y))return false;
   if(dis&&!f[8])return false;
   if(hf&&!(f[9]&&f[9][0]===0))return false;
   if(!q.length)return true;
   const hay=(f[2]+' '+f[4]+' '+f[3].join(' ')+' '+f[7].join(' ')+' '+f[0]).toLowerCase();
   return q.every(w=>hay.includes(w));
  });
  shown=0; $('#rows').innerHTML=''; more();
  $('#count').textContent=hits.length.toLocaleString()+' filing'+(hits.length===1?'':'s');
  const p=new URLSearchParams(); if($('#q').value)p.set('q',$('#q').value); if(u)p.set('unit',U[u]); if(g)p.set('region',G[g]); if(y)p.set('year',y); if(dis)p.set('dis','1'); if(hf)p.set('file','1');
  history.replaceState(null,'',p.toString()?'?'+p:location.pathname);
 }
 function more(){const next=hits.slice(shown,shown+100);$('#rows').insertAdjacentHTML('beforeend',next.map(row).join(''));shown+=next.length;$('#more').style.display=shown<hits.length?'':'none'}
 const P=new URLSearchParams(location.search);
 if(P.get('q'))$('#q').value=P.get('q'); if(P.get('unit'))$('#unit').value=U.indexOf(P.get('unit')); if(P.get('region'))$('#region').value=G.indexOf(P.get('region'));
 if(P.get('year'))$('#year').value=P.get('year'); if(P.get('dis'))$('#dis').checked=true; if(P.get('file')&&$('#hasfile'))$('#hasfile').checked=true;
 let t; $('#q').addEventListener('input',()=>{clearTimeout(t);t=setTimeout(run,150)});
 ['#unit','#region','#year','#dis'].forEach(s=>$(s).addEventListener('change',run));
 $('#more').addEventListener('click',more); run();
})();
"""


# Front page: pinned dockets (Paul's list, Nov 20) and two tickers.
# The follow-a-docket page on the main site (live Nov 20, on Paul's yes).
# Set to None to take every Follow button off the records site.
FOLLOW_URL = "https://www.gapublicservice.org/follow/"
PINNED = [
    {"label": "Affordability", "docket": None,
     "title": "Affordability docket",
     "note": "Proposed at the Commission. Not opened yet, so it has no docket number."},
    {"label": "RTP", "docket": 57171},
    {"label": "Fuel", "docket": 56765},
    {"label": "Rate case", "docket": 44280},
    {"label": "IRP", "docket": 56002},
    {"label": "RFP", "docket": 56368},
    {"label": "RFP", "docket": 57454},
    {"label": "RFP", "docket": 56478},
]
KIND_LABEL = {"hearing": "Hearing", "docket": "Hearing", "session": "Administrative session",
              "committee": "Committee meeting", "forum": "Public forum",
              "working group": "Working group", "other": "Meeting"}


def _short(text: str, n: int = 80) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"(?<=[a-z])\?s\b", "\u2019s", text)  # the Commission's broken apostrophes
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def _day(iso: str, weekday: bool = False) -> str:
    d = dt.date.fromisoformat(iso)
    return d.strftime(("%a " if weekday else "") + "%b ") + str(d.day)


def load_calendar() -> list[dict]:
    p = DATA / "index" / "calendar.json"
    return json.loads(p.read_text()).get("events", []) if p.exists() else []


def load_agendas() -> dict:
    """Agenda files by calendar event address, from harvester.agendas."""
    p = DATA / "index" / "agendas.json"
    return json.loads(p.read_text()).get("events", {}) if p.exists() else {}


try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = dt.timezone(dt.timedelta(hours=-5))

LAG = ("We copy the Commission's site each night at about 3 AM Eastern, so a change the "
       "Commission makes during the day shows up here the next morning, and anything posted after "
       "that run waits a day. The Commission's own page is the one to rely on.")


def _when(iso: str | None) -> str:
    """'Nov 20, 2026 at 12:46 PM Eastern' from a UTC time stamp."""
    if not iso:
        return ""
    if len(iso) == 10:
        d = dt.date.fromisoformat(iso)
        return f"the night of {d:%b} {d.day}, {d.year}"
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(_ET)
    return f'{t:%b} {t.day}, {t.year} at {t.hour % 12 or 12}:{t:%M} {"AM" if t.hour < 12 else "PM"} Eastern'


def copied_note(what: str, checked: str | None) -> str:
    """The standing note on anything copied from the Commission: when, and how long changes take."""
    when = f" Last copied {_when(checked)}." if checked else ""
    return f'<p class="copied"><b>{e(what)}</b>{e(when)} {e(LAG)}</p>'


def agenda_slug(ev_url: str) -> str:
    """The Commission's own name for the meeting, from its calendar address."""
    m = re.search(r"/commission-calendar/([a-z0-9.\-]+)/", ev_url or "")
    return m.group(1) if m else ics.uid_for({"url": ev_url})


def has_agenda_text(ev: dict | None) -> bool:
    return any(f.get("text") for f in (ev or {}).get("files") or [])


def agendas_by_docket(agendas: dict, known) -> dict:
    """For each known docket, the agenda items that name it, newest meeting first."""
    out = collections.defaultdict(list)
    for url, ev in agendas.items():
        for f in ev.get("files", []):
            for it in f.get("items", []):
                if str(it["docket"]) in known:
                    out[str(it["docket"])].append({"date": ev["date"], "time": ev["time"], "kind": ev["kind"],
                                                   "event": url, "label": f["label"], "file": f["url"],
                                                   "page": (f"agenda/{agenda_slug(url)}/" if f.get("text") else ""), "docket": it["docket"],
                                                   "line": it["line"]})
    for v in out.values():
        v.sort(key=lambda x: x["date"], reverse=True)
    return out


def agenda_link(ev_url: str, agendas: dict, cls: str = "tk-agenda", up: str = "") -> str:
    """'Agenda' to our linked copy when we have its text, else to the file or the Commission's event page."""
    ev = agendas.get(ev_url) or {}
    files = ev.get("files") or []
    if not files:
        return ""
    if has_agenda_text(ev):
        return f' <a class="{cls}" href="{up}agenda/{e(agenda_slug(ev_url))}/">Agenda</a>'
    if len(files) == 1:
        return f' <a class="{cls}" href="{e(files[0]["url"])}">Agenda</a>'
    return f' <a class="{cls}" href="{e(ev_url)}">Agendas ({len(files)})</a>'


def agenda_pick(items: list[dict], today: str) -> dict | None:
    """The next meeting whose agenda lists the docket, else the latest one in the last 30 days."""
    ahead = [x for x in items if x["date"] >= today]
    if ahead:
        return min(ahead, key=lambda x: x["date"])
    recent = (dt.date.fromisoformat(today) - dt.timedelta(days=30)).isoformat()
    past = [x for x in items if recent <= x["date"] < today]
    return past[0] if past else None


def _agenda_href(x: dict, up: str = "") -> str:
    return f'{up}{x["page"]}#d{x.get("docket", "")}' if x.get("page") else x["file"]


def agenda_button(items: list[dict], today: str, up: str = "") -> str:
    ag = agenda_pick(items, today)
    if not ag:
        return ""
    when = "On the" if ag["date"] >= today else "Was on the"
    return (f' <a class="pin-follow agenda-btn" href="{e(_agenda_href(ag, up))}">{when} {e(_day(ag["date"]))} agenda</a>')


def agenda_table(items: list[dict], up: str = "", checked: str | None = None) -> str:
    if not items:
        return ""
    trs = "".join(
        f'<tr><td class="mono">{e(x["date"])}</td><td>{e(x["label"])}</td>'
        f'<td>{e(_short(x["line"], 220))}</td><td>'
        + (f'<a href="{e(_agenda_href(x, up))}">Agenda</a> · ' if x.get("page") else "")
        + f'<a href="{e(x["file"])}">File</a></td></tr>' for x in items)
    return ('<h2>On Commission agendas</h2><p class="muted">Meetings whose agenda names this docket, read from the '
            'agenda files the Commission attaches to its calendar. The line shown is the agenda\'s own wording; '
            'agendas are often amended, so the Commission\'s file is the one to cite.</p>'
            + copied_note("Agendas are copies.", checked) +
            '<table class="wide"><thead><tr><th>Meeting</th><th>Agenda</th><th>Item</th><th>File</th></tr></thead>'
            f'<tbody>{trs}</tbody></table>')


def _meta(name: str) -> dict:
    p = DATA / "index" / name
    if not p.exists():
        return {}
    d = json.loads(p.read_text())
    return {k: v for k, v in d.items() if k != "events"}


def _cal_row(ev: dict, agendas: dict, known: set, add: bool) -> str:
    uid = ics.uid_for(ev)
    what = e(ics.summary_for(ev).removeprefix("PSC "))
    link = f'<a href="{e(ev["url"])}">{what}</a>' if ev.get("url") else what
    if ev.get("other"):
        link += ' <span class="tag">Not a Commission event</span>'
    dks = sorted({int(d) for d in ev.get("dockets") or []})  # the agenda page lists the rest
    dk = " ".join(f'<a class="mono" href="docket/{d}/">{d}</a>' for d in dks if str(d) in known)
    ag = agenda_link(ev.get("url"), agendas).strip() if ev.get("url") else ""
    adds = ""
    if add:
        adds = (f'<a class="cal-btn" href="{e(ics.google_link(ev, agendas, known))}">Google</a> '
                f'<a class="cal-btn" href="cal/{uid}.ics" download>Apple or Outlook</a>')
    return (f'<tr id="ev-{uid}"><td class="mono">{e(_day(ev["date"], True))}</td><td class="mono">{e(ev.get("time") or "")}</td>'
            f'<td>{link}{(" " + dk) if dk else ""}</td><td>{ag}</td>' + (f'<td class="cal-add">{adds}</td>' if add else "") + '</tr>')


def upcoming_json(allev: list[dict], agendas: dict, today: str, known: set, checked: str | None, n: int = 5) -> dict:
    """The next few meetings, for the "Upcoming meetings" block on the main site's home page."""
    out = []
    for ev in [x for x in allev if x["date"] >= today][:n]:
        uid = ics.uid_for(ev)
        ag = agendas.get(ev.get("url")) if ev.get("url") else None
        out.append({"date": ev["date"], "day": _day(ev["date"], True), "time": ev.get("time") or "",
                    "what": ics.summary_for(ev).removeprefix("PSC "), "other": bool(ev.get("other")),
                    "url": ev.get("url") or "",
                    "agenda": f"{ics.SITE}/agenda/{agenda_slug(ev['url'])}/" if has_agenda_text(ag) else "",
                    "add": f"{ics.SITE}/calendar.html#ev-{uid}",
                    "google": ics.google_link(ev, agendas, known), "ics": f"{ics.SITE}/cal/{uid}.ics"})
    when = f"Last copied {_when(checked)}. " if checked else ""
    return {"checked": checked, "calendar": f"{ics.SITE}/calendar.html", "subscribe": f"{ics.SITE}/calendar.html#subscribe",
            "note": f"Copied from the Commission's calendar. {when}{LAG}", "events": out}


def older_agendas(agendas: dict, before: str) -> str:
    """Every earlier meeting whose agenda we have as a linked page, newest first."""
    rows = sorted(((ev["date"], url, ev) for url, ev in agendas.items()
                   if ev["date"] < before and has_agenda_text(ev)), reverse=True)
    if not rows:
        return ""
    items = "".join(f'<li><span class="mono">{e(d)}</span> <a href="agenda/{e(agenda_slug(u))}/">'
                    f'{e(KIND_LABEL.get(ev["kind"], "Meeting"))}</a> '
                    f'<span class="muted">{len(ev.get("dockets") or [])} dockets</span></li>' for d, u, ev in rows)
    return f'<h2>Earlier agendas</h2><ul class="ag-dockets">{items}</ul>'


def calendar_page(allev: list[dict], agendas: dict, today: str, checked: str | None) -> str:
    known = set(load_known_dockets())
    links = ics.subscribe_links()
    up = [ev for ev in allev if ev["date"] >= today]
    recent = (dt.date.fromisoformat(today) - dt.timedelta(days=60)).isoformat()
    past = [ev for ev in allev if recent <= ev["date"] < today][::-1]
    months, rows = None, []
    for ev in up:
        m = dt.date.fromisoformat(ev["date"]).strftime("%B %Y")
        if m != months:
            rows.append(f'<tr class="cal-month"><th colspan="5">{e(m)}</th></tr>')
            months = m
        rows.append(_cal_row(ev, agendas, known, True))
    head = '<thead><tr><th>Day</th><th>Time</th><th>Meeting</th><th>Agenda</th><th>Add to your calendar</th></tr></thead>'
    upcoming = (f'<table class="wide cal">{head}<tbody>{"".join(rows)}</tbody></table>' if up
                else '<p class="muted">Nothing on the Commission calendar yet.</p>')
    past_rows = "".join(_cal_row(ev, agendas, known, False) for ev in past)
    return f"""<div class="kicker">Georgia Public Service Commission</div>
<h1>Commission calendar</h1>
<p class="lede">Every hearing, administrative session and committee meeting on the Commission's calendar, with links to each agenda and docket. The Commission's site has no calendar feed, so we make one.</p>
<section id="subscribe" class="cal-subscribe">
<h2>Subscribe</h2>
<p>Add the whole calendar once and new meetings appear on their own. Calendar apps refresh a subscribed feed on their own schedule, usually every few hours to once a day, so a change can take up to a day more to reach you after it shows up here.</p>
<p class="btns"><a class="pin-follow" href="{e(links['google'])}">Google Calendar</a> <a class="pin-follow" href="{e(links['webcal'])}">Apple Calendar</a> <a class="pin-follow" href="{e(links['outlook'])}">Outlook</a></p>
<p class="muted">Other apps: subscribe to <span class="mono">{e(links['feed'])}</span></p>
</section>
{copied_note("The calendar is a copy.", checked)}
<p class="muted">The Commission lists start times only, so each meeting is set to two hours in your calendar. Agendas usually appear a few days before a meeting.</p>
<h2>Coming up</h2>
{upcoming}
<h2>Last 60 days</h2>
<table class="wide cal"><thead><tr><th>Day</th><th>Time</th><th>Meeting</th><th>Agenda</th></tr></thead><tbody>{past_rows}</tbody></table>
{older_agendas(agendas, recent)}"""


_KNOWN: list = []


def load_known_dockets() -> list:
    if not _KNOWN:
        p = DATA / "index" / "dockets.json"
        _KNOWN.extend(json.loads(p.read_text()).keys() if p.exists() else [])
    return _KNOWN


_ENUM = re.compile(r"^(\(?(\d{1,3}|[A-Za-z]|[ivxIVX]{1,5})[.)]|\([a-z]{2}\)|[A-Z]{1,2}-?\d{1,2}\.)\s")


def _agenda_line(line: str, nums: set[int], dockets: dict, seen: set) -> str:
    """One line of the agenda as HTML, its docket numbers linked."""
    if not line:
        return ""
    txt = e(re.sub(r"(?<=[a-z])\?s\b", "’s", line))
    anchors = []

    def sub(m):
        d = int(m.group(1))
        if d not in nums:
            return m.group(0)
        href = f"../../docket/{d}/" if str(d) in dockets else f"{PSC_DOCKET}{d}"
        idattr = ""
        if d not in seen:
            seen.add(d)
            idattr = f' id="d{d}"'
        return f'<a class="mono dk"{idattr} href="{href}">{d}</a>'
    txt = re.sub(r"(?<!\d)(\d{4,5})(?!\d)", sub, txt)
    if _is_heading(line):
        return f'<p class="ag-h">{txt}</p>'
    cls = "ag-item" if _ENUM.match(line) else "ag-p"
    return f'<p class="{cls}">{txt}</p>'


def _is_heading(line: str) -> bool:
    return bool(re.sub(r"[^A-Za-z]", "", line)) and line.upper() == line and len(line) <= 90 and not _ENUM.match(line)


def agenda_paragraphs(lines: list[str]) -> list[str]:
    """Rejoin lines that old Word files wrap mid-sentence. A new paragraph starts at a blank
    line, a numbered or lettered item, or a heading in capitals."""
    out: list[str] = []
    cur = ""
    for line in lines + [""]:
        if not line:
            if cur:
                out.append(cur)
            cur = ""
            continue
        if not cur:
            cur = line
        elif _ENUM.match(line) or _is_heading(line) or _is_heading(cur):
            out.append(cur)
            cur = line
        elif cur.endswith("-") and line[:1].isdigit():
            cur += line
        else:
            cur += " " + line
    return out


def _item_text(line: str) -> str:
    """An agenda line without its item number and docket number: 'QX Ground, LLC; GUFPA Case No. ...'."""
    return re.sub(r"^.*?docket\s*(?:nos?\.?|numbers?|#)?\s*[\d,\s&and-]*[:.]?\s*", "", line, count=1, flags=re.I) or line


def agenda_page(url: str, ev: dict, dockets: dict, checked: str | None) -> str:
    kind = KIND_LABEL.get(ev["kind"], "Meeting")
    d = dt.date.fromisoformat(ev["date"])
    when = f'{d:%A, %B} {d.day}, {d.year}' + (f' at {ev["time"]}' if ev.get("time") else "")
    seen: set = set()
    parts, all_items = [], {}
    for f in ev.get("files") or []:
        nums = {i["docket"] for i in f.get("items") or []}
        for i in f.get("items") or []:
            all_items.setdefault(i["docket"], i["line"])
        ext = f["name"].rsplit(".", 1)[-1].lower()
        head = (f'<div class="ag-file"><h2>{e(f.get("label") or "Agenda")}</h2>'
                f'<p class="muted">The Commission\'s file: <a href="{e(f["url"])}">{e(f["name"])}</a> ({e(ext)})</p></div>')
        if f.get("text"):
            body = "".join(_agenda_line(l, nums, dockets, seen) for l in agenda_paragraphs(f["text"]))
        else:
            body = '<p class="muted">We could not read this file\'s text. Open the Commission\'s file above.</p>'
        parts.append(head + f'<div class="agenda">{body}</div>')
    dk_list = "".join(
        f'<li><a class="mono" href="{("../../docket/" + str(n) + "/") if str(n) in dockets else PSC_DOCKET + str(n)}">{n}</a> '
        f'{e(_short(docket_title([], str(n)) or _item_text(line), 110))}</li>' for n, line in sorted(all_items.items()))
    read = ev.get("read") or checked
    return f"""<div class="kicker"><a href="../../calendar.html">Commission calendar</a></div>
<h1>{e(kind)}, {e(f"{d:%b} {d.day}, {d.year}")}</h1>
<p class="lede">{e(when)}. <a href="{e(url)}">The Commission's page for this meeting</a></p>
<div class="note"><strong>This is a copy of the agenda the Commission posted, made so each docket links to its record.</strong>
The Commission's file is the official agenda and the one to cite. Layout and numbering may differ a little from the original.</div>
{copied_note("Agendas are copies.", read)}
<p class="muted">Agendas are often amended in the days before a meeting. An amended agenda the Commission posts after our nightly run shows up here the next morning.</p>
{"".join(parts)}
{f'<h2>Dockets on this agenda</h2><ul class="ag-dockets">{dk_list}</ul>' if dk_list else ""}"""


def ticker(name: str, items: list[str], empty: str) -> str:
    if not items:
        return (f'<div class="ticker"><span class="tk-label">{e(name)}</span>'
                f'<div class="tk-view"><span class="tk-item muted">{e(empty)}</span></div></div>')
    run = "".join(f'<span class="tk-item">{i}</span>' for i in items)
    return (f'<div class="ticker" role="region" aria-label="{e(name)}"><span class="tk-label">{e(name)}</span>'
            f'<div class="tk-view" tabindex="0"><div class="tk-run" style="--n:{len(items)}">'
            f'<span class="tk-set">{run}</span><span class="tk-set" aria-hidden="true">{run}</span>'
            f'</div></div></div>')


def front_tickers(events: list[dict], dockets: dict, today: str, agendas: dict | None = None) -> str:
    horizon = (dt.date.fromisoformat(today) + dt.timedelta(days=60)).isoformat()
    up = []
    for ev in events:
        if not (today <= ev["date"] <= horizon):
            continue
        kind = KIND_LABEL.get(ev["kind"], "Meeting")
        title = re.sub(r"\s*\d{1,2}-\d{1,2}(-\d{2,4})?$", "", ev["title"])
        title = re.sub(r"^(docket\s*(no\.?|#|nos\.?)?\s*[\d,\s&and]+[\s:-]*)", "", title, flags=re.I).strip()
        dk = "".join(f'<a class="mono" href="docket/{d}/">{d}</a> ' for d in ev["dockets"])
        plain = ev["kind"] in ("session", "committee") or kind.lower() == title.lower()
        what = "" if plain else f' {e(_short(title, 70))}'
        up.append(f'<b>{e(_day(ev["date"], True))}</b> <span class="muted">{e(ev["time"])}</span> '
                  f'<a href="{e(ev["url"])}">{e(kind)}</a>{agenda_link(ev["url"], agendas or {})}'
                  f' <a class="tk-add" href="calendar.html#ev-{ics.uid_for(ev)}" title="Add this meeting to your calendar">+ Add</a>'
                  f' {dk}{what}')
    hot = sorted(((k, v) for k, v in dockets.items() if v.get("contested")),
                 key=lambda kv: kv[1].get("last_filed") or "", reverse=True)
    cont = []
    for d, v in hot:
        n = len(v.get("disagreeing_filers") or [])
        cont.append(f'<a class="mono" href="docket/{d}/">{d}</a> {e(_short(docket_title([], d), 60))} '
                    f'<span class="muted">{n} filer{"s" if n != 1 else ""} objecting, last filing {e(_day(v["last_filed"]))}</span>')
    sub = ('<p class="cal-sub">Put every Commission meeting in your own calendar: '
           '<a href="calendar.html#subscribe">Subscribe</a>. The Commission\'s site has no calendar feed, '
           'so we make one each night.</p>')
    return (ticker("Upcoming", up, "Nothing on the Commission calendar in the next 60 days.")
            + ticker("Contested", cont, "No contested dockets right now.") + sub)


def pinned_cards(dockets: dict, events: list[dict], today: str, on_agenda: dict | None = None) -> str:
    cards = []
    for pin in PINNED:
        d = pin["docket"]
        if d is None:
            cards.append(f'<div class="pin expected"><div class="pin-top"><span class="pin-label">{e(pin["label"])}</span>'
                         f'<span class="pin-badge">Expected</span></div><h3>{e(pin["title"])}</h3>'
                         f'<p class="muted">{e(pin["note"])}</p></div>')
            continue
        v = dockets.get(str(d), {})
        nxt = next((ev for ev in events if d in ev["dockets"] and ev["date"] >= today), None)
        facts = [f'{v.get("filings", 0):,} filings']
        if v.get("last_filed"):
            facts.append(f'latest {_day(v["last_filed"])}, {v["last_filed"][:4]}')
        lines = f'<p class="pin-facts mono">{e(" · ".join(facts))}</p>'
        if nxt:
            lines += f'<p class="pin-next">Next: <a href="{e(nxt["url"])}">{e(KIND_LABEL.get(nxt["kind"], "Meeting"))}, {e(_day(nxt["date"], True))}</a></p>'
        ag = agenda_pick((on_agenda or {}).get(str(d), []), today)
        if ag:
            when = "On the agenda" if ag["date"] >= today else "Was on the agenda"
            lines += (f'<p class="pin-next">{when}: <a href="{e(_agenda_href(ag))}">'
                      f'{e(KIND_LABEL.get(ag["kind"], "Meeting"))}, {e(_day(ag["date"], True))}</a></p>')
        if v.get("contested"):
            lines += '<p><span class="tag dis">Contested</span></p>'
        follow = (f'<a class="pin-follow" href="{e(FOLLOW_URL)}?docket={d}">Follow</a>' if FOLLOW_URL else "")
        cards.append(f'<div class="pin"><div class="pin-top"><span class="pin-label">{e(pin["label"])}</span>'
                     f'<a class="mono pin-dk" href="docket/{d}/">{d}</a></div>'
                     f'<h3><a href="docket/{d}/">{e(_short(docket_title([], d), 90))}</a></h3>{lines}{follow}</div>')
    return '<h2>Dockets to watch</h2><div class="pins">' + "".join(cards) + "</div>"



def latest_strip(rows: list[dict], n: int = 10) -> str:
    """Newest filings by Commission document number, as a row that scrolls sideways."""
    newest = sorted(rows, key=lambda r: r["document_id"], reverse=True)[:n]
    cards = []
    for r in newest:
        dk = " ".join(f'<a href="docket/{d}/" class="mono">{d}</a>' for d in r["dockets"]) or '<span class="muted">no docket</span>'
        cards.append(f'<div class="lf"><div class="lf-top mono"><span>{e(r.get("filed_date") or "")}</span>{dk}</div>'
                     f'<a class="lf-title" href="{PSC_DOC}{r["document_id"]}">{e(_short((r.get("description") or "").strip() or "(no description)", 110))}</a>'
                     f'<span class="muted lf-by">{e(_short(r.get("company") or "No filer named", 60))}</span>'
                     f'<span class="lf-file">{file_marker(r["document_id"], r.get("files"))}</span></div>')
    arrows = ('<span class="lf-nav"><button type="button" class="lf-btn" data-dir="-1" aria-label="Earlier in the list">&larr;</button>'
              '<button type="button" class="lf-btn" data-dir="1" aria-label="Further along the list">&rarr;</button></span>')
    script = ("<script>document.querySelectorAll('.lf-btn').forEach(function(b){b.addEventListener('click',function(){"
              "var s=document.querySelector('.lfs');var c=s.querySelector('.lf');"
              "s.scrollBy({left:(+b.dataset.dir)*(c?c.offsetWidth:260),behavior:'smooth'});});});</script>")
    return (f'<div class="lf-head"><h2>Latest filings</h2>{arrows}</div>'
            '<div class="lfs" tabindex="0" role="region" aria-label="Latest filings">'
            + "".join(cards) + "</div>" + script)


def build():
    rows, dockets = load()
    by_docket = collections.defaultdict(list)
    for r in rows:
        for d in r["dockets"]:
            by_docket[d].append(r)
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "data").mkdir(parents=True)
    shutil.copy(SRC / "style.css", OUT / "style.css")
    (OUT / ".nojekyll").write_text("")
    (OUT / "data" / "filings.json").write_text(json.dumps(build_search_data(rows), separators=(",", ":"), ensure_ascii=False))
    # Docket titles for the follow page on the main site, which shows the
    # title of the docket a reader is about to follow.
    (OUT / "data" / "docket-titles.json").write_text(json.dumps(
        {d: _short(docket_title(by_docket.get(d, []), d), 140) for d in sorted(dockets, key=int)},
        separators=(",", ":"), ensure_ascii=False))

    dates = sorted(r["filed_date"] for r in rows if r.get("filed_date") and r["filed_date"] >= "1990")
    contested = [d for d, v in dockets.items() if v["contested"]]
    # First month with a full month's filings; a few older stragglers sit before it.
    per_month = collections.Counter(x[:7] for x in dates)
    first_full = next((m for m in sorted(per_month) if per_month[m] >= 100), dates[0][:7] if dates else "")
    since = dt.date.fromisoformat(first_full + "-01").strftime("%b %Y") if first_full else ""
    daily = sorted((DATA / "daily").glob("*.json"))
    last_night = daily[-1].stem if daily else None
    new_ids = set(json.loads(daily[-1].read_text())) if daily else set()

    # Search (home)
    stats = (f'<div class="stats"><div><b>{len(rows):,}</b><span>filings in the record</span></div>'
             f'<div><b>{len(dockets):,}</b><span>dockets</span></div>'
             f'<div><b>{len(contested)}</b><span>contested dockets</span></div>'
             f'<div><b>{since}</b><span>complete record since</span></div>'
             f'<div><b>{len(new_ids)}</b><span>new filings last night</span></div></div>')
    events = load_calendar()
    agendas = load_agendas()
    cal_meta = _meta("calendar.json")
    agendas_checked = _meta("agendas.json").get("checked")
    last_nightly = json.loads((DATA / "state.json").read_text()).get("last_nightly") if (DATA / "state.json").exists() else None
    on_agenda = agendas_by_docket(agendas, dockets)
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=-5))).date().isoformat()
    body = front_tickers(events, dockets, now, agendas) + f"""<div class="kicker">Georgia Public Service Commission</div>
<h1>Every public filing, searchable.</h1>
<p class="lede">A nightly copy of every filing posted to the Commission's public site since September 2022, tagged by staff unit, place and disagreement. Every result links to the Commission's own page.</p>
{pinned_cards(dockets, events, now, on_agenda)}
{latest_strip(rows)}
<h2>Search the record</h2>
{stats}
{copied_note("Filings are copies.", last_nightly)}
<div class="search"><input id="q" type="search" placeholder="Search filer, title, docket or county" aria-label="Search">
<select id="unit" aria-label="Staff unit"></select><select id="region" aria-label="Region"></select><select id="year" aria-label="Year"></select></div>
<div class="row2"><label><input type="checkbox" id="dis"> Only filings that object, oppose or ask for rehearing</label><label><input type="checkbox" id="hasfile"> Only filings with a file to download</label><span id="count" class="mono"></span></div>
<table class="wide"><thead><tr><th>Filed</th><th>Docket</th><th>Filer</th><th>Filing</th></tr></thead><tbody id="rows"></tbody></table>
<button id="more" class="more">Show 100 more</button>
<noscript><p>Search needs JavaScript. Browse by <a href="dockets.html">docket</a> instead.</p></noscript>
<script>{SEARCH_JS}</script>"""
    (OUT / "index.html").write_text(page("Search", body, "search"))

    # Calendar feed, calendar page and agenda pages
    allev = ics.write(OUT, events, agendas, now, set(dockets))
    (OUT / "calendar.html").write_text(page("Calendar", calendar_page(allev, agendas, now, cal_meta.get("checked")), "calendar"))
    (OUT / "data" / "upcoming.json").write_text(json.dumps(upcoming_json(allev, agendas, now, set(dockets), cal_meta.get("checked")), indent=1))
    n_ag = 0
    for url, ev in agendas.items():
        if not has_agenda_text(ev):
            continue
        out = OUT / "agenda" / agenda_slug(url)
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text(page(f"Agenda, {_day(ev['date'])}, {ev['date'][:4]}",
                                             agenda_page(url, ev, dockets, agendas_checked), "calendar", depth=2))
        n_ag += 1
    print(f"{len(allev)} calendar events, {n_ag} agenda pages")

    # Docket list
    def dk_line(d, v):
        title = docket_title(by_docket.get(int(d), []), d)
        badge = '<span class="tag dis">contested</span>' if v["contested"] else ""
        regs = "".join(f'<span class="tag">{e(g)}</span>' for g in v.get("regions", {}))
        return (f'<tr><td><a class="mono" href="docket/{d}/">{d}</a></td><td>{e(title[:160])}<br>{badge}'
                f'{"".join(f"<span class=tag>{e(u)}</span>" for u in v["units"])}{regs}</td>'
                f'<td class="num mono">{v["filings"]:,}</td><td class="mono">{e(v["last_filed"] or "")}</td></tr>')
    ordered = sorted(dockets.items(), key=lambda kv: (kv[1]["last_filed"] or ""), reverse=True)
    con_rows = "".join(dk_line(d, v) for d, v in ordered if v["contested"])
    all_rows = "".join(dk_line(d, v) for d, v in ordered)
    body = f"""<div class="kicker">Dockets</div><h1>{len(dockets):,} dockets</h1>
<p class="lede">Each docket is a case or proceeding at the Commission. Titles are the Commission's own; where its page hasn't been read yet, the title shown is that of the docket's earliest filing in the record.</p>
<h2>Contested dockets</h2>
<p class="muted">Two or more different parties, other than the Commission and its hearing officers, have each filed something whose own title objects, opposes, complains, asks for rehearing or moves to compel, dismiss or strike. A rule on filing titles, not a judgment about who is right.</p>
<table class="wide"><thead><tr><th>Docket</th><th>Title and tags</th><th class="num">Filings</th><th>Last filed</th></tr></thead><tbody>{con_rows}</tbody></table>
<h2>All dockets, most recent first</h2>
<table class="wide"><thead><tr><th>Docket</th><th>Title and tags</th><th class="num">Filings</th><th>Last filed</th></tr></thead><tbody>{all_rows}</tbody></table>"""
    (OUT / "dockets.html").write_text(page("Dockets", body, "dockets"))

    # One page per docket
    for d, v in dockets.items():
        fs = sorted(by_docket.get(int(d), []), key=lambda r: (r.get("filed_date") or "", r["document_id"]), reverse=True)
        title = docket_title(fs, d)
        meta = docket_meta(d)
        facts = []
        if meta:
            facts += [("Industry (Commission's label)", meta.get("industry") or ""),
                      ("Opened", meta.get("date") or ""), ("Status", meta.get("status") or "")]
        facts += [("Filings in the record", f"{v['filings']:,}"),
                 ("First and last filed", f"{v['first_filed'] or '?'} to {v['last_filed'] or '?'}"),
                 ("Staff unit", ", ".join(v["units"]) or "not tagged"),
                 ("Committee", ", ".join(v["committees"]) or "not tagged")]
        if v.get("regions"):
            facts.append(("Regions named in filing titles", ", ".join(f"{g} ({n})" for g, n in v["regions"].items())))
        fst = collections.Counter((r.get("files") or {}).get("state") for r in fs)
        if fs and any(fst):
            bits = [f"{fst['available']:,} of {len(fs):,} filings have a file to download"]
            if fst["confidential"]:
                bits.append(f"{fst['confidential']:,} confidential")
            if fst["none"]:
                bits.append(f"{fst['none']:,} with no file posted")
            if fst["unconfirmed"]:
                bits.append(f"{fst['unconfirmed']:,} not reached on our last try")
            facts.append(("Files", "; ".join(bits)))
        if v["disagreeing_filers"]:
            facts.append(("Parties that filed a disagreement", "; ".join(v["disagreeing_filers"])))
        stat = "".join(f"<tr><th>{e(k)}</th><td>{e(x)}</td></tr>" for k, x in facts)
        badge = '<span class="tag dis">contested</span> ' if v["contested"] else ""
        body = f"""<div class="kicker">Docket <span class="mono">{d}</span></div>
<h1>{e(title[:200]) or "Docket " + d}</h1>
<p>{badge}<a href="{PSC_DOCKET}{d}">This docket on the Commission's site</a></p>
<p class="btns">{f'<a class="pin-follow" href="{e(FOLLOW_URL)}?docket={d}">Follow this docket</a>' if FOLLOW_URL else ""}{agenda_button(on_agenda.get(d, []), now, "../../")}</p>
<table>{stat}</table>
{agenda_table(on_agenda.get(d, []), "../../", agendas_checked)}
<h2>Filings, newest first</h2>
<table class="wide"><thead><tr><th>Filed</th><th>Filer</th><th>Filing</th></tr></thead><tbody>{"".join(filing_row(r, 2, False) for r in fs)}</tbody></table>"""
        p = OUT / "docket" / d
        p.mkdir(parents=True, exist_ok=True)
        (p / "index.html").write_text(page(f"Docket {d}", body, "dockets", depth=2))

    # Last night
    new = sorted((r for r in rows if r["document_id"] in new_ids), key=lambda r: r["document_id"], reverse=True)
    dis = [r for r in new if r["disagreement"]]
    body = f"""<div class="kicker">Last night's harvest · {e(last_night or "")}</div>
<h1>{len(new)} new filing{"s" if len(new) != 1 else ""}</h1>
<p class="lede">What the 3 AM harvest found on the Commission's site. The harvest runs every night and rechecks recent numbers the Commission fills in late.</p>
{copied_note("Filings are copies.", last_nightly)}
<h2>Disagreements</h2>
{'<table class="wide"><tbody>' + "".join(filing_row(r, 0) for r in dis) + "</tbody></table>" if dis else '<p class="muted">None last night.</p>'}
<h2>All new filings</h2>
<table class="wide"><thead><tr><th>Filed</th><th>Docket</th><th>Filer</th><th>Filing</th></tr></thead><tbody>{"".join(filing_row(r, 0) for r in new)}</tbody></table>
<p class="muted">The full nightly digest, with flags and the Friday spot check, is in the <a href="https://github.com/gapublicservice/records/tree/main/data/digests">record's digests</a>.</p>"""
    (OUT / "today.html").write_text(page("Last night", body, "today"))

    # Regions
    reg = json.loads((DATA / "index" / "regional_generation.json").read_text())
    trs = []
    for g, v in sorted(reg["regions"].items(), key=lambda kv: -kv[1]["added_mw"]):
        top = "; ".join(f"{p['plant']} ({p['county']})" for p in v["plants"][:3]) or "none"
        n_dk = sum(1 for dv in dockets.values() if g in dv.get("regions", {}))
        trs.append(f'<tr><td><strong>{e(g)}</strong><br><span class="muted">{e(", ".join(v["counties"]))}</span></td>'
                   f'<td class="num mono">{v["added_mw"]:,.0f}</td><td class="num mono">{v["retired_mw"]:,.0f}</td>'
                   f'<td class="num mono">{v["planned_mw"]:,.0f}</td><td>{e(top)}</td>'
                   f'<td class="num mono"><a href="index.html?region={html.escape(g, quote=True)}">{n_dk}</a></td></tr>')
    grid = infrastructure.regions_html(infrastructure.build(rows), html.escape, PSC_DOC,
                                       copied_note("Gas certificate filings are copies.", last_nightly))
    body = f"""<div class="kicker">Regional picture</div><h1>Power plants, power lines and gas projects by region</h1>
<p class="lede">Megawatts of generating capacity added, retired and planned since 2020 in each of Georgia's 12 regional commissions, with the dockets whose filing titles name a county there. Below the plants: transmission lines, gas pipelines and gas certificate filings.</p>
<div class="note">Plants and their counties come from the U.S. Energy Information Administration's monthly generator list (Form EIA-860M, <a href="{e(reg['source']['generators'].split('(')[-1].rstrip(')'))}">this edition</a>). Counties are grouped by the regional list in the Georgia Department of Audits and Accounts' 2019 report on regional commissions. Nameplate megawatts, summed from EIA's rows. Planned means EIA lists the plant as planned, not that the Commission approved it. Transmission lines and gas projects are <a href="#grid">further down</a>.</div>
<table class="wide"><thead><tr><th>Region and counties</th><th class="num">Added MW</th><th class="num">Retired MW</th><th class="num">Planned MW</th><th>Largest plants</th><th class="num">Dockets</th></tr></thead><tbody>{"".join(trs)}</tbody></table>
{grid}"""
    (OUT / "regions.html").write_text(page("Regions", body, "regions"))

    # About
    body = f"""<div class="kicker">About</div><h1>About the record</h1>
<p class="lede">Public Service keeps a complete, searchable copy of what the Georgia Public Service Commission posts, for reporters, advocates, local officials and ratepayers: anyone who needs to know what the Commission did and why.</p>
{f"<p>{e(CLIMATE_LINE)}</p>" if CLIMATE_LINE else ""}
<div class="note"><strong>{e(INDEPENDENCE)}</strong></div>
<h2>Who is behind it</h2>
<p>{e(SPONSOR)} GCVEF also funds the editor's work, and the editor also works for Georgia Conservation Voters. Neither group decides what the record contains: it holds every public filing, whoever filed it.</p>
<h2>How the record is made</h2>
<p>The Commission has no single feed of new filings. Every filing has its own numbered page, so each night at 3 AM a program walks the numbers forward, stores what it finds and rechecks recent numbers the Commission fills in late. The code and every stored record are public at <a href="https://github.com/gapublicservice/records">github.com/gapublicservice/records</a>.</p>
<p>Trade-secret versions of filings are never public and are never downloaded or stored here.</p>
<h2>How the tags work</h2>
<p>Every tag is a written rule applied to what the Commission published, and each carries the rule that set it. <strong>Staff unit and committee</strong> follow the Commission's own 2025 annual report. <strong>Counties</strong> are those a filing's title names. <strong>Disagreement</strong> means a filing's own title objects, opposes, complains, protests, takes exceptions, appeals, asks for rehearing or moves to compel, dismiss or strike. None of this is a judgment about who is right.</p>
<h2>How to check a record</h2>
<p>Every filing links to the Commission's own page. Each stored file carries a SHA-256 fingerprint of the file as downloaded, so anyone can download the original and confirm it is the same. Each Friday five records chosen at random are checked by hand against the Commission's pages, and the result is posted in the record.</p>
<h2>Files and downloads</h2>
<p>Each filing shows whether the Commission offers a file anyone can download. <strong>Download file</strong> goes straight to the file on the Commission's site; when there are several, the link opens the Commission's page that lists them. When there is nothing to download, the marker says why in general terms: no file was posted, every file listed is marked as a trade secret, or our last attempt to reach the file failed. Hover over the marker, or tap it on a phone, to read the reason. Trade-secret files are never downloaded or stored here.</p>
<p>This archive shows what the Commission posted. It does not show that what a filing says is true.</p>"""
    (OUT / "about.html").write_text(page("About", body, "about"))
    n = sum(1 for _ in OUT.rglob("*.html"))
    print(f"{n} pages written to {OUT.relative_to(ROOT)}")


def main() -> int:
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
