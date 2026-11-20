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
import shutil
from pathlib import Path

from .run import DATA, ROOT

OUT = ROOT / "_site"
SRC = ROOT / "site"
PSC_DOC = "https://psc.ga.gov/search/facts-document/?documentId="
PSC_DOCKET = "https://psc.ga.gov/search/facts-docket/?docketId="

INDEPENDENCE = ("Public Service is an independent project. It is not a product of the Georgia "
                "Public Service Commission, and the Commission does not run or endorse it. "
                "The Commission's own record is at psc.ga.gov.")
SPONSOR = "Sponsored by the Georgia Conservation Voters Education Fund (GCVEF)."

e = html.escape


def page(title: str, body: str, on: str, depth: int = 0, extra_head: str = "") -> str:
    up = "../" * depth
    nav = [("index.html", "Search", "search"), ("dockets.html", "Dockets", "dockets"),
           ("today.html", "Last night", "today"), ("regions.html", "Regions", "regions"),
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
<header class="site"><div class="bar">
<a class="name" href="{up}index.html"><span>Public<br>Service<small>The record</small></span><span class="dot"></span></a>
<nav>{links}</nav></div></header>
<main>{body}</main>
<footer class="site"><div class="bar">
<p><strong>{e(INDEPENDENCE)}</strong></p>
<p>{e(SPONSOR)} Records are copied each night from the Commission's public site; each one links to the original.</p>
<p class="mono">Built {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC · data and code: <a href="https://github.com/gapublicservice/records">github.com/gapublicservice/records</a></p>
</div></footer></body></html>
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
    cells.append(f'<td><a href="{PSC_DOC}{r["document_id"]}">{e((r.get("description") or "").strip() or "(no description)")}</a><br>{tags}</td>')
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
                        r["counties_in_title"], 1 if r["disagreement"] else 0])
    return {"units": units, "regions": regions, "filings": compact}


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
 let shown=0, hits=[];
 function row(f){
  const dk=f[3].map(d=>'<a class="mono" href="docket/'+d+'/">'+d+'</a>').join(' ')||'<span class="muted">none</span>';
  let tags=f[5].map(i=>'<span class="tag">'+esc(U[i])+'</span>').join('')+f[7].map(c=>'<span class="tag">'+esc(c)+' County</span>').join('');
  if(f[8]) tags+='<span class="tag dis">disagreement</span>';
  return '<tr><td class="mono">'+esc(f[1])+'</td><td>'+dk+'</td><td>'+esc(f[2]||'No filer named')+'</td><td><a href="https://psc.ga.gov/search/facts-document/?documentId='+f[0]+'">'+esc(f[4]||'(no description)')+'</a><br>'+tags+'</td></tr>';
 }
 function run(){
  const q=$('#q').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const u=$('#unit').value, g=$('#region').value, y=$('#year').value, dis=$('#dis').checked;
  hits=F.filter(f=>{
   if(u!==''&&!f[5].includes(+u))return false;
   if(g!==''&&!f[6].includes(+g))return false;
   if(y&&!f[1].startsWith(y))return false;
   if(dis&&!f[8])return false;
   if(!q.length)return true;
   const hay=(f[2]+' '+f[4]+' '+f[3].join(' ')+' '+f[7].join(' ')+' '+f[0]).toLowerCase();
   return q.every(w=>hay.includes(w));
  });
  shown=0; $('#rows').innerHTML=''; more();
  $('#count').textContent=hits.length.toLocaleString()+' filing'+(hits.length===1?'':'s');
  const p=new URLSearchParams(); if($('#q').value)p.set('q',$('#q').value); if(u)p.set('unit',U[u]); if(g)p.set('region',G[g]); if(y)p.set('year',y); if(dis)p.set('dis','1');
  history.replaceState(null,'',p.toString()?'?'+p:location.pathname);
 }
 function more(){const next=hits.slice(shown,shown+100);$('#rows').insertAdjacentHTML('beforeend',next.map(row).join(''));shown+=next.length;$('#more').style.display=shown<hits.length?'':'none'}
 const P=new URLSearchParams(location.search);
 if(P.get('q'))$('#q').value=P.get('q'); if(P.get('unit'))$('#unit').value=U.indexOf(P.get('unit')); if(P.get('region'))$('#region').value=G.indexOf(P.get('region'));
 if(P.get('year'))$('#year').value=P.get('year'); if(P.get('dis'))$('#dis').checked=true;
 let t; $('#q').addEventListener('input',()=>{clearTimeout(t);t=setTimeout(run,150)});
 ['#unit','#region','#year','#dis'].forEach(s=>$(s).addEventListener('change',run));
 $('#more').addEventListener('click',more); run();
})();
"""


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

    dates = sorted(r["filed_date"] for r in rows if r.get("filed_date") and r["filed_date"] >= "1990")
    contested = [d for d, v in dockets.items() if v["contested"]]
    daily = sorted((DATA / "daily").glob("*.json"))
    last_night = daily[-1].stem if daily else None
    new_ids = set(json.loads(daily[-1].read_text())) if daily else set()

    # Search (home)
    stats = (f'<div class="stats"><div><b>{len(rows):,}</b><span>filings in the record</span></div>'
             f'<div><b>{len(dockets):,}</b><span>dockets</span></div>'
             f'<div><b>{len(contested)}</b><span>contested dockets</span></div>'
             f'<div><b>{dates[0][:7] if dates else ""}</b><span>earliest filing month</span></div>'
             f'<div><b>{len(new_ids)}</b><span>new filings last night</span></div></div>')
    body = f"""<div class="kicker">Georgia Public Service Commission</div>
<h1>Every public filing, searchable.</h1>
<p class="lede">A nightly copy of every filing posted to the Commission's public site since September 2022, tagged by staff unit, place and disagreement. Every result links to the Commission's own page.</p>
{stats}
<div class="search"><input id="q" type="search" placeholder="Search filer, title, docket or county" aria-label="Search">
<select id="unit" aria-label="Staff unit"></select><select id="region" aria-label="Region"></select><select id="year" aria-label="Year"></select></div>
<div class="row2"><label><input type="checkbox" id="dis"> Only filings that object, oppose or ask for rehearing</label><span id="count" class="mono"></span></div>
<table class="wide"><thead><tr><th>Filed</th><th>Docket</th><th>Filer</th><th>Filing</th></tr></thead><tbody id="rows"></tbody></table>
<button id="more" class="more">Show 100 more</button>
<noscript><p>Search needs JavaScript. Browse by <a href="dockets.html">docket</a> instead.</p></noscript>
<script>{SEARCH_JS}</script>"""
    (OUT / "index.html").write_text(page("Search", body, "search"))

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
        if v["disagreeing_filers"]:
            facts.append(("Parties that filed a disagreement", "; ".join(v["disagreeing_filers"])))
        stat = "".join(f"<tr><th>{e(k)}</th><td>{e(x)}</td></tr>" for k, x in facts)
        badge = '<span class="tag dis">contested</span> ' if v["contested"] else ""
        body = f"""<div class="kicker">Docket <span class="mono">{d}</span></div>
<h1>{e(title[:200]) or "Docket " + d}</h1>
<p>{badge}<a href="{PSC_DOCKET}{d}">This docket on the Commission's site</a></p>
<table>{stat}</table>
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
    body = f"""<div class="kicker">Regional picture</div><h1>Power plants by region since 2020</h1>
<p class="lede">Megawatts of generating capacity added, retired and planned in each of Georgia's 12 regional commissions, with the dockets whose filing titles name a county there.</p>
<div class="note">Plants and their counties come from the U.S. Energy Information Administration's monthly generator list (Form EIA-860M, <a href="{e(reg['source']['generators'].split('(')[-1].rstrip(')'))}">this edition</a>). Counties are grouped by the regional list in the Georgia Department of Audits and Accounts' 2019 report on regional commissions. Nameplate megawatts, summed from EIA's rows. Planned means EIA lists the plant as planned, not that the Commission approved it. Transmission lines, substations and gas pipelines are not in this table yet.</div>
<table class="wide"><thead><tr><th>Region and counties</th><th class="num">Added MW</th><th class="num">Retired MW</th><th class="num">Planned MW</th><th>Largest plants</th><th class="num">Dockets</th></tr></thead><tbody>{"".join(trs)}</tbody></table>"""
    (OUT / "regions.html").write_text(page("Regions", body, "regions"))

    # About
    body = f"""<div class="kicker">About</div><h1>About the record</h1>
<p class="lede">Public Service keeps a complete, searchable copy of what the Georgia Public Service Commission posts, for reporters, partners and anyone following the Commission's work.</p>
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
<p>This archive shows what the Commission posted. It does not show that what a filing says is true.</p>"""
    (OUT / "about.html").write_text(page("About", body, "about"))
    n = sum(1 for _ in OUT.rglob("*.html"))
    print(f"{n} pages written to {OUT.relative_to(ROOT)}")


def main() -> int:
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
