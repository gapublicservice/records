"""Transmission and gas projects by regional commission.

    python -m harvester.infrastructure   # writes data/index/regional_infrastructure.json

Two kinds of entries:

* Project lists kept by hand in data/reference/*_projects.json, each read from a
  named public source (utility filings at the Commission, utility project pages,
  federal notices). A project counts in a region only when its source names a
  county there; projects whose source names no county are listed apart.
* Gas certificate applications found automatically in the record: filings whose
  title asks the Commission for a natural gas or pipeline certificate of public
  convenience and necessity and names a county.
"""

from __future__ import annotations

import json
import re

from .regions import REGION_OF, REGIONS
from .run import DATA, save_json

REF = DATA / "reference"
OUT = DATA / "index" / "regional_infrastructure.json"
_CANON = {c.lower(): c for c in REGION_OF}
CERT = re.compile(r"certificate of public convenience", re.I)
NOT_GAS = re.compile(r"telecom|interexchange|local exchange|alternative operator|cancel", re.I)


def project_lists():
    out = []
    for p in sorted(REF.glob("*_projects.json")):
        d = json.loads(p.read_text())
        d["file"] = f"data/reference/{p.name}"
        for x in d["projects"]:
            x["counties"] = [_CANON[c.lower()] for c in x.get("counties", []) if c.lower() in _CANON]
            x["regions"] = sorted({REGION_OF[c] for c in x["counties"]})
        out.append(d)
    return sorted(out, key=lambda d: d.get("order", 9))


def gas_certificates(rows):
    certs = []
    for f in rows:
        t = f.get("description") or ""
        if not CERT.search(t) or NOT_GAS.search(t):
            continue
        if "Natural Gas" not in (f.get("units") or []) and not re.search(r"pipeline|natural gas", t, re.I):
            continue
        counties = [c for c in f.get("counties_in_title") or [] if c in REGION_OF]
        certs.append({"filed": f.get("filed_date"), "document_id": f["document_id"],
                      "dockets": f.get("dockets") or [], "filer": f.get("company") or "",
                      "title": t, "counties": counties,
                      "regions": sorted({REGION_OF[c] for c in counties})})
    certs.sort(key=lambda c: c["filed"] or "", reverse=True)
    return certs


def build(rows=None):
    if rows is None:
        rows = [json.loads(l) for l in (DATA / "index" / "filings.jsonl").open()]
    lists = project_lists()
    certs = gas_certificates(rows)
    regions = {g: {"projects": [], "certificates": 0} for g in REGIONS}
    for d in lists:
        for i, x in enumerate(d["projects"]):
            for g in x["regions"]:
                regions[g]["projects"].append({"layer": d["layer"], "name": x["name"], "kind": x["kind"]})
    for c in certs:
        for g in c["regions"]:
            regions[g]["certificates"] += 1
    return {"lists": lists, "certificates": certs, "regions": regions}


def main() -> int:
    d = build()
    save_json(OUT, d)
    for g, v in d["regions"].items():
        print(f"{g}: {len(v['projects'])} projects, {v['certificates']} gas certificate filings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def _check(x, e):
    c = x.get("checked")
    if not c:
        return ""
    return f'<br><span class="muted"><b>{e(CHECK_WORDS.get(c, c))}.</b> {e(x.get("check_note", ""))}</span>'


def _src_links(d, x, e):
    links = []
    for k in x.get("sources", []):
        s = d["sources"][k]
        links.append(f'<a href="{e(s["url"], quote=True)}">{e(s["label"])}</a>')
    return "; ".join(links)


CHECK_WORDS = {"confirmed": "Confirmed by a second public source", "partly": "Partly confirmed",
               "one source": "One public source so far"}
SERTP_GEORGIA_NEW = 36  # Georgia new lines and new substations in the 2026 SERTP public project list, all on this page


def _coverage(d, e):
    n = {k: 0 for k in CHECK_WORDS}
    total = 0
    for lst in d["lists"]:
        for x in lst["projects"]:
            total += 1
            n[x.get("checked", "one source")] = n.get(x.get("checked", "one source"), 0) + 1
    return (f'<h3>How complete this is</h3><p>Transmission: all {SERTP_GEORGIA_NEW} Georgia new lines and new substations in the public '
            'project list of the 2026 regional transmission plan (SERTP, June 2026 draft) are on this page. That is the ten-year plan '
            'Georgia Power, Georgia Transmission, MEAG Power and the region\'s other utilities publish each year. Its other entries for '
            'the Southern Company area are rebuilds, reconductoring and equipment work, or are in Alabama and Mississippi, and are left out. '
            'The plan can miss lines built to serve one large customer, such as a data center, and projects too early to be in it; '
            'those appear in federal environmental reviews and local notices, and are added as they are found.</p>'
            '<p>Gas: Atlanta Gas Light\'s 2025-2034 plan at the Commission is the record for its system; no outside list exists to check it '
            'against. Interstate pipelines are from FERC\'s list of approved projects.</p>'
            f'<p class="muted">Of {total} projects: {n["confirmed"]} confirmed by a second public source, {n["partly"]} partly confirmed, '
            f'{n["one source"]} with one public source so far. Checked November 23, 2026.</p>')


def regions_html(d, e, psc_doc: str, copied: str) -> str:
    """The transmission and gas part of the Regions page. e is html.escape."""
    layers = [x["layer"] for x in d["lists"]]
    head = "".join(f'<th class="num">{e(l)}</th>' for l in layers)
    trs = []
    for g, v in sorted(d["regions"].items(), key=lambda kv: -len(kv[1]["projects"])):
        cells = "".join(f'<td class="num mono">{sum(1 for p in v["projects"] if p["layer"] == l)}</td>' for l in layers)
        trs.append(f'<tr><td><strong>{e(g)}</strong></td>{cells}<td class="num mono">{v["certificates"]}</td></tr>')
    coverage = _coverage(d, e)
    out = [f"""<h2 id="grid">Transmission lines and gas projects by region</h2>
<p>Counts of projects whose source names a county in each region. A line or pipeline that runs through several regions counts in each. Projects whose source names no county are listed below the tables, not counted.</p>
<div class="note">These are lists read by hand from named public sources. Each project links to its source and says whether a second public source confirms it.</div>
{coverage}
<table class="wide"><thead><tr><th>Region</th>{head}<th class="num">Gas certificate filings</th></tr></thead><tbody>{"".join(trs)}</tbody></table>"""]
    unplaced = []
    for lst in d["lists"]:
        rows = []
        for x in lst["projects"]:
            name = e(x["name"])
            if x.get("url"):
                name = f'<a href="{e(x["url"], quote=True)}">{name}</a>'
            when = x.get("current_year")
            when_s = (str(when) if when else "not given")
            if x.get("planned_year") and when and x["planned_year"] != when:
                when_s += f' (was {x["planned_year"]})'
            row = (f'<tr><td><strong>{name}</strong><br><span class="muted">{e(x.get("owner", ""))}. {e(x["kind"])}. {e(x["size"])}</span></td>'
                   f'<td>{e(", ".join(x["counties"]) or "not named in the source")}'
                   f'{"<br><span class=muted>" + e(", ".join(x["regions"])) + "</span>" if x["regions"] else ""}</td>'
                   f'<td class="mono">{e(when_s)}</td><td>{e(x["status"])}<br><span class="muted">{_src_links(lst, x, e)}</span>'
                   f'{_check(x, e)}</td></tr>')
            if x["counties"]:
                rows.append(row)
            else:
                unplaced.append((lst["layer"], row))
        if rows:
            out.append(f'<h3>{e(lst["layer"])}</h3><p class="muted">{e(lst["about"])}</p>'
                       f'<table class="wide"><thead><tr><th>Project</th><th>Counties and regions</th><th>Target year</th><th>Status and source</th></tr></thead><tbody>{"".join(rows)}</tbody></table>')
    if unplaced:
        out.append('<h3>Projects whose source names no county</h3><p class="muted">Most are from the regional plan, which names '
                   'substations, not counties. Listed so nothing is hidden; not counted in any region until a public source names the county.</p>')
        for layer in [l["layer"] for l in d["lists"]]:
            rs = [r for lay, r in unplaced if lay == layer]
            if rs:
                out.append(f'<h4>{e(layer)}</h4><table class="wide"><thead><tr><th>Project</th><th>Counties</th><th>Target year</th>'
                           f'<th>Status and source</th></tr></thead><tbody>{"".join(rs)}</tbody></table>')
    crow = []
    for c in d["certificates"]:
        dk = ", ".join(f'<a href="docket/{n}/">{n}</a>' for n in c["dockets"])
        crow.append(f'<tr><td class="mono">{e(c["filed"] or "")}</td><td>{e(", ".join(c["counties"]) or "not in title")}</td>'
                    f'<td><a href="{psc_doc}{c["document_id"]}">{e(c["title"])}</a><br><span class="muted">{e(c["filer"])}</span></td><td class="mono">{dk}</td></tr>')
    out.append(f"""<h3>Gas certificate applications at the Commission</h3>
<p>Filings asking the Commission for a new or amended natural gas or pipeline certificate of public convenience and necessity, found in the record automatically. Most extend a gas utility's service area or a city gas system into a county; the title names the county.</p>
{copied}
<table class="wide"><thead><tr><th>Filed</th><th>County in title</th><th>Filing</th><th>Docket</th></tr></thead><tbody>{"".join(crow)}</tbody></table>""")
    return "\n".join(out)
