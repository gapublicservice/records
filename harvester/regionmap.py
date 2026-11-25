"""The map of Georgia at the top of the Regions page.

    python -m harvester.regionmap geometry PATH/TO/counties-10m.json
        # rebuilds data/reference/ga_counties_map.json from the U.S. Atlas file

The county shapes are drawn once, from the Census Bureau's cartographic
boundary files as redistributed in the us-atlas package (version 3.0.1,
counties-10m.json, ISC licence; the Census data is public domain), and kept
in data/reference/ga_counties_map.json as ready-made SVG paths. Nothing is
fetched when the page loads: the map is plain SVG inside the page, with no
map service, no tiles and no tracking.

Every project in data/reference/*_projects.json whose source names a county
gets a pin, built fresh at each build, so a project added to those lists
shows up on the map at the next build. A pin sits in one of the counties the
source names (the one nearest the middle of them all); hovering over it, or
tapping it on a phone, shades every county the source names and opens a box
with the project's details. Projects whose source names no county stay off
the map and stay in the lists below it.
"""

from __future__ import annotations

import csv
import html
import json
import math
import sys
from pathlib import Path

from .regions import REGION_OF

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "data" / "reference" / "ga_counties_map.json"
W = 500  # viewBox width; height follows the state's shape
CHECK_SHORT = {"confirmed": "Confirmed by a second public source", "partly": "Partly confirmed",
               "one source": "One public source so far"}


# ---- geometry (run by hand; the result is committed) ----

def _decode_arcs(topo):
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    out = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        out.append(pts)
    return out


def _rdp(pts, tol):
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    n = math.hypot(dx, dy) or 1e-12
    best, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        dist = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / n if (dx or dy) else math.hypot(px - x1, py - y1)
        if dist > best:
            best, idx = dist, i
    if best <= tol:
        return [pts[0], pts[-1]]
    return _rdp(pts[: idx + 1], tol)[:-1] + _rdp(pts[idx:], tol)


def geometry(path: str) -> dict:
    topo = json.loads(Path(path).read_text())
    arcs = _decode_arcs(topo)
    geoms = [g for g in topo["objects"]["counties"]["geometries"] if str(g["id"]).startswith("13")]
    used = {}
    for g in geoms:
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        for poly in polys:
            for ring in poly:
                for a in ring:
                    used.setdefault(a if a >= 0 else ~a, []).append(g["properties"]["name"])
    lons = [p[0] for i in used for p in arcs[i]]
    lats = [p[1] for i in used for p in arcs[i]]
    lon0, lon1, lat0, lat1 = min(lons), max(lons), min(lats), max(lats)
    k = math.cos(math.radians((lat0 + lat1) / 2))
    pad = 6
    scale = (W - 2 * pad) / ((lon1 - lon0) * k)
    H = round((lat1 - lat0) * scale + 2 * pad)

    def proj(p):
        return ((p[0] - lon0) * k * scale + pad, (lat1 - p[1]) * scale + pad)

    simple = {i: _rdp([proj(p) for p in arcs[i]], 0.35) for i in used}

    def ring_pts(ring):
        pts = []
        for a in ring:
            seg = simple[a] if a >= 0 else simple[~a][::-1]
            pts.extend(seg if not pts else seg[1:])
        return pts

    def d_of(rings):
        return "".join("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in r) + "Z" for r in rings)

    counties = {}
    for g in geoms:
        name = g["properties"]["name"]
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        rings = [ring_pts(r) for poly in polys for r in poly]
        outer = max((ring_pts(poly[0]) for poly in polys), key=lambda r: abs(_area(r)))
        cx, cy = _centroid(outer)
        counties[name] = {"d": d_of(rings), "cx": round(cx, 1), "cy": round(cy, 1)}
    # Lines between regional commissions, and the state line: arcs used by one
    # county only, or by two counties in different regions.
    borders = []
    for i, names in used.items():
        if len(names) == 1 or REGION_OF[names[0]] != REGION_OF[names[1]]:
            borders.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in simple[i]))
    return {"source": "U.S. Census Bureau cartographic boundary files (2017), as redistributed in us-atlas 3.0.1 "
                      "(counties-10m.json, ISC licence, copyright Michael Bostock); simplified for the page",
            "viewBox": [0, 0, W, H], "counties": dict(sorted(counties.items())), "borders": "".join(borders),
            # How a longitude and latitude become a point on the map, for plants placed by EIA's coordinates.
            "proj": {"lon0": lon0, "lat1": lat1, "k": k, "scale": scale, "pad": pad}}


def _area(r):
    return sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r))) / 2


def _centroid(r):
    a = _area(r) or 1e-9
    cx = cy = 0.0
    for i in range(len(r)):
        x0, y0 = r[i]
        x1, y1 = r[(i + 1) % len(r)]
        c = x0 * y1 - x1 * y0
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    return cx / (6 * a), cy / (6 * a)


# ---- pins (run at every build) ----

def pins(lists: list[dict], geo: dict) -> tuple[list[dict], int]:
    """One pin per project whose source names a county; returns (pins, number left off)."""
    cs = geo["counties"]
    out, left_off = [], 0
    for lst in lists:
        for x in lst["projects"]:
            named = [c for c in x.get("counties", []) if c in cs]
            if not named:
                left_off += 1
                continue
            mx = sum(cs[c]["cx"] for c in named) / len(named)
            my = sum(cs[c]["cy"] for c in named) / len(named)
            home = min(named, key=lambda c: (cs[c]["cx"] - mx) ** 2 + (cs[c]["cy"] - my) ** 2)
            out.append({"layer": lst["layer"], "x": x, "home": home, "counties": named,
                        "gas": "gas" in (lst["layer"] + " " + x.get("kind", "")).lower(),
                        "sources": [lst["sources"][k] for k in x.get("sources", []) if k in lst["sources"]]})
    # Spread pins that share a county around its middle so each can be reached.
    by_home: dict[str, list[dict]] = {}
    for p in out:
        by_home.setdefault(p["home"], []).append(p)
    for home, ps in by_home.items():
        cx, cy = cs[home]["cx"], cs[home]["cy"]
        if len(ps) == 1:
            ps[0]["px"], ps[0]["py"] = cx, cy
            continue
        rad = 6 + 2.2 * len(ps)
        for i, p in enumerate(ps):
            ang = -math.pi / 2 + 2 * math.pi * i / len(ps)
            p["px"], p["py"] = cx + rad * math.cos(ang), cy + rad * math.sin(ang)
    return out, left_off


PLANT_KIND = {"added": "Built since 2020", "planned": "Planned", "retired": "Retired since 2020"}
EIA_CSV = ROOT / "data" / "reference" / "eia860m_ga.csv"


def plants(reg: dict | None, geo: dict) -> tuple[list[dict], int]:
    """One square per plant in the Regions table, at the spot EIA lists for it.

    reg is data/index/regional_generation.json (rebuilt with each EIA edition);
    coordinates come from EIA's own rows in eia860m_ga.csv. Returns (plants,
    number left off for want of coordinates)."""
    if not reg or "proj" not in geo:
        return [], 0
    where = {}
    try:
        with EIA_CSV.open() as f:
            for r in csv.DictReader(f):
                try:
                    ll = (float(r["Latitude"]), float(r["Longitude"]))
                except (KeyError, TypeError, ValueError):
                    continue
                key = ((r.get("Plant Name") or "").strip().lower(), (r.get("County") or "").replace(" ", "").lower())
                where.setdefault(key, ll)
    except OSError:
        return [], 0
    pr = geo["proj"]
    out, left_off = [], 0
    for region, v in reg.get("regions", {}).items():
        for p in v.get("plants", []):
            ll = where.get(((p.get("plant") or "").strip().lower(), (p.get("county") or "").replace(" ", "").lower()))
            if not ll:
                left_off += 1
                continue
            x = (ll[1] - pr["lon0"]) * pr["k"] * pr["scale"] + pr["pad"]
            y = (pr["lat1"] - ll[0]) * pr["scale"] + pr["pad"]
            mw = {k: p.get(f"{k}_mw") or 0 for k in PLANT_KIND}
            out.append({"p": p, "region": region, "px": x, "py": y, "kind": max(mw, key=mw.get), "mw": mw})
    # Plants at the same spot (several units, or neighbours) are nudged apart so each can be reached.
    placed: list[tuple[float, float]] = []
    for q in sorted(out, key=lambda q: -sum(q["mw"].values())):
        step = 0
        while any((q["px"] - a) ** 2 + (q["py"] - b) ** 2 < 36 for a, b in placed) and step < 24:
            step += 1
            ang = step * 2.4
            q["px"] += 7 * math.cos(ang) / (1 + step / 6)
            q["py"] += 7 * math.sin(ang) / (1 + step / 6)
        placed.append((q["px"], q["py"]))
    return out, left_off


def _when(x):
    w = x.get("current_year")
    s = str(w) if w else "not given"
    if x.get("planned_year") and w and x["planned_year"] != w:
        s += f" (was {x['planned_year']})"
    return s


def map_html(lists: list[dict], e=html.escape, reg: dict | None = None) -> str:
    """The map block for the Regions page. Empty if the county shapes are missing.

    reg, when given, is the regional generation index; its plants go on the map
    as squares, under the project pins."""
    try:
        geo = json.loads(GEO.read_text())
    except (OSError, ValueError):
        return ""
    ps, left_off = pins(lists, geo)
    vb = " ".join(str(v) for v in geo["viewBox"])
    county_paths = "".join(f'<path data-c="{e(n, quote=True)}" d="{c["d"]}"><title>{e(n)} County</title></path>'
                           for n, c in geo["counties"].items())
    pls, plants_off = plants(reg, geo)
    eia_url = ((reg or {}).get("source", {}).get("generators", "").split("(")[-1].rstrip(")")) if reg else ""
    pmarks, marks, boxes = [], [], []
    for j, q in enumerate(pls):
        p, kind, sq = q["p"], q["kind"], 4.2
        label = f'{p["plant"]}, power plant. {PLANT_KIND[kind]}.'
        pmarks.append(f'<g class="pin plant {kind}" tabindex="0" role="button" aria-label="{e(label, quote=True)}" '
                      f'aria-controls="rm-p{j}" data-b="rm-p{j}" data-cs="{e(p.get("county") or "", quote=True)}">'
                      f'<circle class="hit" cx="{q["px"]:.1f}" cy="{q["py"]:.1f}" r="8"/>'
                      f'<rect class="pm" x="{q["px"] - sq:.1f}" y="{q["py"] - sq:.1f}" width="{2 * sq}" height="{2 * sq}"/></g>')
        rows = "".join(f'<dt>{e(PLANT_KIND[k])}</dt><dd class="mono">{q["mw"][k]:,.1f} MW</dd>' for k in PLANT_KIND if q["mw"][k])
        yrs = ", ".join(str(y) for y in p.get("years", []))
        src = (f'<a href="{e(eia_url, quote=True)}">U.S. Energy Information Administration, Form EIA-860M</a>'
               if eia_url.startswith("http") else "U.S. Energy Information Administration, Form EIA-860M")
        boxes.append(
            f'<div class="rm-box" id="rm-p{j}" role="dialog" aria-label="{e(p["plant"], quote=True)}" hidden>'
            f'<button class="rm-x" type="button" aria-label="Close">×</button>'
            f'<div class="rm-k">Power plant · {e(PLANT_KIND[kind])}</div><div class="rm-n">{e(p["plant"])}</div>'
            f'<p>{e("; ".join(p.get("owner") or []))}. {e(", ".join(p.get("technology") or []))}.</p>'
            f'<dl><dt>County</dt><dd>{e(p.get("county") or "")}</dd><dt>Region</dt><dd>{e(q["region"])}</dd>{rows}'
            f'{"<dt>Year</dt><dd class=mono>" + e(yrs) + "</dd>" if yrs else ""}'
            f'<dt>Checked</dt><dd>From the federal list of generators, which EIA updates monthly. Planned means EIA lists it as planned, not that the Commission approved it.</dd>'
            f'<dt>Source</dt><dd>{src}</dd></dl></div>')
    for i, p in enumerate(ps):
        x = p["x"]
        chk = x.get("checked", "one source")
        fill = {"confirmed": "solid", "partly": "half"}.get(chk, "open")
        cty = " ".join(p["counties"])
        label = f'{x["name"]}, {x.get("kind", "")}. {CHECK_SHORT.get(chk, chk)}.'
        r = 6.5
        if p["gas"]:
            shape = (f'<rect class="pm" x="{p["px"] - r:.1f}" y="{p["py"] - r:.1f}" width="{2 * r}" height="{2 * r}" '
                     f'transform="rotate(45 {p["px"]:.1f} {p["py"]:.1f})"/>')
        else:
            shape = f'<circle class="pm" cx="{p["px"]:.1f}" cy="{p["py"]:.1f}" r="{r}"/>'
        half = (f'<path class="ph" d="M{p["px"] - r:.1f},{p["py"]:.1f}A{r},{r} 0 0 0 {p["px"] + r:.1f},{p["py"]:.1f}Z"/>'
                if fill == "half" and not p["gas"] else
                (f'<path class="ph" d="M{p["px"] - r * 1.41:.1f},{p["py"]:.1f}L{p["px"]:.1f},{p["py"] + r * 1.41:.1f}'
                 f'L{p["px"] + r * 1.41:.1f},{p["py"]:.1f}Z"/>' if fill == "half" else ""))
        marks.append(f'<g class="pin {fill}" tabindex="0" role="button" aria-label="{e(label, quote=True)}" '
                     f'aria-controls="rm-b{i}" data-b="rm-b{i}" data-cs="{e(cty, quote=True)}">'
                     f'<circle class="hit" cx="{p["px"]:.1f}" cy="{p["py"]:.1f}" r="13"/>{shape}{half}</g>')
        regions = sorted({REGION_OF[c] for c in p["counties"]})
        src = "; ".join(f'<a href="{e(s["url"], quote=True)}">{e(s["label"])}</a>' for s in p["sources"])
        name = e(x["name"])
        if x.get("url"):
            name = f'<a href="{e(x["url"], quote=True)}">{name}</a>'
        boxes.append(
            f'<div class="rm-box" id="rm-b{i}" role="dialog" aria-label="{e(x["name"], quote=True)}" hidden>'
            f'<button class="rm-x" type="button" aria-label="Close">×</button>'
            f'<div class="rm-k">{e(p["layer"])}</div><div class="rm-n">{name}</div>'
            f'<p>{e(x.get("owner", ""))}. {e(x.get("kind", ""))}. {e(x.get("size", ""))}</p>'
            f'<dl><dt>Counties</dt><dd>{e(", ".join(p["counties"]))}</dd>'
            f'<dt>Regions</dt><dd>{e(", ".join(regions))}</dd>'
            f'<dt>Target year</dt><dd class="mono">{e(_when(x))}</dd>'
            f'<dt>Status</dt><dd>{e(x.get("status", ""))}</dd>'
            f'<dt>Checked</dt><dd><span class="rm-chk {fill}"></span>{e(CHECK_SHORT.get(chk, chk))}.'
            f'{" " + e(x["check_note"]) if x.get("check_note") else ""}</dd>'
            f'{"<dt>Source</dt><dd>" + src + "</dd>" if src else ""}</dl></div>')
    n = {k: sum(1 for p in ps if p["x"].get("checked", "one source") == k) for k in CHECK_SHORT}
    gas_n = sum(1 for p in ps if p["gas"])
    off = (f' {left_off} project{"s" if left_off != 1 else ""} whose source names no county {"are" if left_off != 1 else "is"} '
           f'not on the map; {"they are" if left_off != 1 else "it is"} <a href="#unplaced">listed below</a>.' if left_off else "")
    pk = {k: sum(1 for q in pls if q["kind"] == k) for k in PLANT_KIND}
    plant_line = ""
    if pls:
        plant_line = (f' Squares are the {len(pls)} power plants counted in the table below ({pk["added"]} built since 2020, '
                      f'{pk["planned"]} planned, {pk["retired"]} retired since 2020), each at the spot EIA lists for it.'
                      + (f' {plants_off} plant{"s" if plants_off != 1 else ""} with no location in EIA\'s list {"are" if plants_off != 1 else "is"} left off.' if plants_off else ""))
    toggles = (f'<label><input type="checkbox" data-layer="plant" checked> Power plants ({len(pls)})</label>'
               f'<label><input type="checkbox" data-layer="proj" checked> Power lines and gas projects ({len(ps)})</label>') if pls else ""
    plant_key = ('<span><i class="kp"></i>Plant built since 2020</span><span><i class="kp planned"></i>Plant planned</span>'
                 '<span><i class="kp retired"></i>Plant retired since 2020</span>') if pls else ""
    return f"""<h2 id="map">Map of {"power plants, " if pls else ""}transmission lines and gas projects</h2>
<p>{len(ps)} projects on the map: {len(ps) - gas_n} power lines and substations, {gas_n} gas pipelines and plants. Hover over a pin, or tap it on a phone, to see the project, and the counties its source names are shaded. A pin sits in one of those counties; it does not mark a street address or the line's route.{off}{plant_line}</p>
<div class="rm" id="rm">
{'<div class="rm-show mono">' + toggles + '</div>' if toggles else ""}
<div class="rm-key mono"><span><i class="kc"></i>Power line or substation</span><span><i class="kd"></i>Gas pipeline or plant</span><span><i class="kc"></i>Confirmed by a second source ({n["confirmed"]})</span><span><i class="kc half"></i>Partly confirmed ({n["partly"]})</span><span><i class="kc open"></i>One source so far ({n["one source"]})</span>{plant_key}</div>
<div class="rm-wrap"><svg viewBox="{vb}" role="group" aria-label="Map of Georgia's counties with a mark for each power plant and project">
<g class="cty">{county_paths}</g><path class="brd" d="{geo["borders"]}"/>
<g class="pins">{"".join(pmarks)}{"".join(marks)}</g></svg>
{"".join(boxes)}</div>
<p class="muted rm-src">Thick lines are the borders of Georgia's 12 regional commissions. County shapes: {e(geo["source"])}. The pins are rebuilt from the project lists below at every build, so a new project appears here when it is added to a list.{' The plants are rebuilt from each new edition of EIA&#39;s generator list.' if pls else ''}</p>
</div>
<style>
.rm{{margin:20px 0 28px}}
.rm-key{{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:12px;margin:0 0 10px;color:var(--muted)}}
.rm-key span{{display:inline-flex;align-items:center;gap:6px}}
.rm-key i{{display:inline-block;width:11px;height:11px;border:1.5px solid var(--ink);background:var(--amber)}}
.rm-key i.kc{{border-radius:50%}} .rm-key i.kd{{transform:rotate(45deg);width:9px;height:9px}}
.rm-key i.half{{background:linear-gradient(0deg,var(--amber) 50%,var(--paper) 50%)}} .rm-key i.open{{background:var(--paper)}}
.rm-key i.kp{{border-radius:0;width:9px;height:9px;background:var(--ink)}} .rm-key i.kp.planned{{background:var(--paper)}} .rm-key i.kp.retired{{background:#a3a3a3}}
.rm-show{{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:12px;margin:0 0 8px}}
.rm-show label{{display:inline-flex;align-items:center;gap:6px;cursor:pointer}}
.rm-show input{{accent-color:var(--amber);margin:0}}
.rm.no-plant .pin.plant,.rm.no-proj .pin:not(.plant){{display:none}}
.rm .pin.plant .pm{{fill:var(--ink);stroke:var(--paper);stroke-width:1}}
.rm .pin.plant.planned .pm{{fill:var(--paper);stroke:var(--ink);stroke-width:1.4}}
.rm .pin.plant.retired .pm{{fill:#a3a3a3;stroke:var(--paper);stroke-width:1}}
.rm .pin.plant.on .pm,.rm .pin.plant:focus-visible .pm{{stroke:var(--amber);stroke-width:2.5}}
.rm-wrap{{position:relative}}
.rm svg{{display:block;width:100%;max-width:620px;height:auto;touch-action:manipulation}}
.rm .cty path{{fill:var(--tint);stroke:#c9c9c4;stroke-width:.5}}
.rm .cty path.lit{{fill:#f6dca0}}
.rm .brd{{fill:none;stroke:var(--ink);stroke-width:1.3;stroke-linejoin:round}}
.rm .pin{{cursor:pointer;outline:none}}
.rm .pin .hit{{fill:transparent}}
.rm .pin .pm{{fill:var(--amber);stroke:var(--ink);stroke-width:1.6}}
.rm .pin.half .pm,.rm .pin.open .pm{{fill:var(--paper)}}
.rm .pin .ph{{fill:var(--amber);stroke:none;pointer-events:none}}
.rm .pin.on .pm,.rm .pin:focus-visible .pm{{stroke-width:3}}
.rm .pin:focus-visible .hit{{stroke:var(--amber);stroke-width:2.5}}
.rm-box{{position:absolute;z-index:6;width:300px;max-width:calc(100vw - 32px);padding:12px 14px 10px;background:var(--ink);color:var(--paper);font:400 13px/1.45 "Space Grotesk",system-ui,sans-serif;box-shadow:0 6px 20px rgba(0,0,0,.25)}}
.rm-box a{{color:var(--paper)}}
.rm-box p{{margin:4px 0 8px}}
.rm-k{{font:500 10px/1.2 "IBM Plex Mono",monospace;letter-spacing:.06em;text-transform:uppercase;color:var(--amber);padding-right:22px}}
.rm-n{{font-weight:700;font-size:15px;line-height:1.25;margin-top:3px;padding-right:22px}}
.rm-box dl{{margin:0;display:grid;grid-template-columns:auto 1fr;gap:3px 10px}}
.rm-box dt{{font:500 10px/1.7 "IBM Plex Mono",monospace;letter-spacing:.05em;text-transform:uppercase;color:#bdbdbd}}
.rm-box dd{{margin:0}}
.rm-chk{{display:inline-block;width:9px;height:9px;border-radius:50%;border:1.5px solid var(--amber);margin-right:6px;vertical-align:0}}
.rm-chk.solid{{background:var(--amber)}} .rm-chk.half{{background:linear-gradient(0deg,var(--amber) 50%,transparent 50%)}}
.rm-x{{position:absolute;top:6px;right:8px;background:none;border:0;color:var(--paper);font:400 20px/1 "Space Grotesk",sans-serif;cursor:pointer;padding:2px 4px}}
.rm-x:focus-visible{{outline:2px solid var(--amber)}}
.rm-src{{font-size:12px;max-width:620px}}
@media (max-width:720px){{.rm-box{{position:static;width:auto;max-width:none;margin-top:10px}}}}
</style>
<script>
(function(){{
var root=document.getElementById('rm');if(!root)return;
var wrap=root.querySelector('.rm-wrap'),svg=root.querySelector('svg'),pinned=null,shown=null;
var narrow=window.matchMedia('(max-width:720px)'),hover=window.matchMedia('(hover:hover)');
function lit(cs){{root.querySelectorAll('.cty path.lit').forEach(function(p){{p.classList.remove('lit')}});(cs||'').split(' ').filter(Boolean).forEach(function(c){{var p=root.querySelector('.cty path[data-c="'+c+'"]');if(p)p.classList.add('lit')}});}}
function hide(){{if(shown){{shown.box.hidden=true;shown.pin.classList.remove('on');shown.pin.setAttribute('aria-expanded','false')}}shown=null;lit('')}}
function show(pin){{
 if(shown&&shown.pin===pin)return;hide();
 var box=document.getElementById(pin.getAttribute('data-b'));if(!box)return;
 box.hidden=false;pin.classList.add('on');pin.setAttribute('aria-expanded','true');shown={{pin:pin,box:box}};
 lit(pin.getAttribute('data-cs'));
 svg.querySelector('.pins').appendChild(pin);
 if(narrow.matches){{box.style.left=box.style.top='';return}}
 var w=wrap.getBoundingClientRect(),s=svg.getBoundingClientRect(),r=pin.getBoundingClientRect(),bw=box.offsetWidth,bh=box.offsetHeight;
 var x=r.left-w.left+r.width/2+14,y=r.top-w.top-bh/2;
 if(w.right-s.right>=bw+20)x=s.right-w.left+20;
 else if(x+bw>w.width)x=r.left-w.left-bw-14+r.width/2;
 if(x<0)x=Math.max(0,Math.min(w.width-bw,r.left-w.left-bw/2));
 y=Math.max(0,Math.min(y,w.height-bh));
 box.style.left=x+'px';box.style.top=y+'px';
}}
root.querySelectorAll('.pin').forEach(function(pin){{
 pin.setAttribute('aria-expanded','false');
 pin.addEventListener('mouseenter',function(){{if(hover.matches&&!pinned)show(pin)}});
 pin.addEventListener('mouseleave',function(){{if(hover.matches&&!pinned)setTimeout(function(){{if(!pinned&&shown&&shown.pin===pin&&!shown.box.matches(':hover'))hide()}},150)}});
 pin.addEventListener('click',function(ev){{ev.stopPropagation();if(pinned===pin){{pinned=null;hide();return}}pinned=pin;show(pin);if(narrow.matches)shown.box.scrollIntoView({{block:'nearest',behavior:'smooth'}})}});
 pin.addEventListener('keydown',function(ev){{if(ev.key==='Enter'||ev.key===' '){{ev.preventDefault();pin.dispatchEvent(new MouseEvent('click'))}}}});
 pin.addEventListener('focus',function(){{if(!pinned)show(pin)}});
}});
root.querySelectorAll('.rm-box').forEach(function(b){{
 b.addEventListener('mouseleave',function(){{if(hover.matches&&!pinned)hide()}});
 b.addEventListener('click',function(ev){{ev.stopPropagation()}});
 b.querySelector('.rm-x').addEventListener('click',function(){{var p=shown&&shown.pin;pinned=null;hide();if(p)p.focus()}});
}});
root.querySelectorAll('.rm-show input').forEach(function(cb){{cb.addEventListener('change',function(){{root.classList.toggle('no-'+cb.getAttribute('data-layer'),!cb.checked);if(shown&&getComputedStyle(shown.pin).display==='none'){{pinned=null;hide()}}}})}});
document.addEventListener('click',function(){{if(shown){{pinned=null;hide()}}}});
document.addEventListener('keydown',function(ev){{if(ev.key==='Escape'&&shown){{var p=shown.pin;pinned=null;hide();p.focus()}}}});
}})();
</script>"""


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "geometry":
        geo = geometry(argv[1])
        GEO.write_text(json.dumps(geo, separators=(",", ":")) + "\n")
        print(f"{len(geo['counties'])} counties written to {GEO.relative_to(ROOT)} ({GEO.stat().st_size:,} bytes)")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
