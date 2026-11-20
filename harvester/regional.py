"""Regional picture of electric generation: what was built, retired and is
planned in each of Georgia's 12 regional commissions since 2020.

    python -m harvester.regional     # writes data/index/regional_generation.json and .md

Places each generator by the county EIA lists for it (data/reference/
eia860m_ga.csv), and each county by the state audit's regional list
(harvester/regions.py). Plants are summed from EIA's own rows; nothing is
estimated. Transmission lines, substations, gas pipelines and customer
programs are not in EIA's list and are not counted here.
"""

from __future__ import annotations

import collections
import csv
import json

from .regions import REGION_OF, REGIONS, SOURCE as REGION_SOURCE
from .run import DATA, save_json

SINCE = 2020
REF = DATA / "reference"
OUT = DATA / "index"
_CANON = {c.lower().replace(" ", ""): c for c in REGION_OF}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _year(v):
    n = _num(v)
    return int(n) if n else None


def build():
    meta = json.loads((REF / "eia860m_ga.json").read_text())
    rows = list(csv.DictReader((REF / "eia860m_ga.csv").open()))
    regions = {g: {"added": collections.Counter(), "retired": collections.Counter(),
                   "planned": collections.Counter(), "canceled": collections.Counter(),
                   "plants": collections.defaultdict(lambda: {"county": None, "owner": set(),
                                                             "added_mw": 0.0, "retired_mw": 0.0,
                                                             "planned_mw": 0.0, "technology": set(),
                                                             "years": set()})}
               for g in REGIONS}
    unplaced = 0
    for r in rows:
        county = _CANON.get((r.get("County") or "").lower().replace(" ", ""))
        if not county:
            unplaced += 1
            continue
        g = REGION_OF[county]
        mw = _num(r.get("Nameplate Capacity (MW)")) or 0.0
        tech = r.get("Technology") or "Unknown"
        sheet = r["sheet"]
        if sheet == "Operating" and (_year(r.get("Operating Year")) or 0) >= SINCE:
            kind, yr = "added", _year(r.get("Operating Year"))
        elif sheet == "Retired" and (_year(r.get("Retirement Year")) or 0) >= SINCE:
            kind, yr = "retired", _year(r.get("Retirement Year"))
        elif sheet == "Planned":
            kind, yr = "planned", _year(r.get("Planned Operation Year"))
        elif sheet.startswith("Canceled"):
            regions[g]["canceled"][tech] += mw
            continue
        else:
            continue
        regions[g][kind][tech] += mw
        p = regions[g]["plants"][r.get("Plant Name") or r.get("Plant ID")]
        p["county"] = county
        p["owner"].add(r.get("Entity Name") or "")
        p[f"{kind}_mw"] += mw
        p["technology"].add(tech)
        if yr:
            p["years"].add(yr)
    out = {"source": {"generators": f"{meta['source']} ({meta['url']})", "regions": REGION_SOURCE},
           "since": SINCE, "unplaced_rows": unplaced, "regions": {}}
    for g, v in regions.items():
        plants = []
        for name, p in v["plants"].items():
            plants.append({"plant": name, "county": p["county"], "owner": sorted(p["owner"]),
                           "technology": sorted(p["technology"]), "years": sorted(p["years"]),
                           **{k: round(p[k], 1) for k in ("added_mw", "retired_mw", "planned_mw")}})
        plants.sort(key=lambda p: -(p["added_mw"] + p["retired_mw"] + p["planned_mw"]))
        out["regions"][g] = {
            "counties": REGIONS[g],
            **{f"{k}_mw": round(sum(v[k].values()), 1) for k in ("added", "retired", "planned", "canceled")},
            **{f"{k}_by_technology": {t: round(m, 1) for t, m in v[k].most_common() if m}
               for k in ("added", "retired", "planned")},
            "plants": plants,
        }
    return out


def markdown(d) -> str:
    lines = [f"# Electric generation by regional commission, {d['since']} to now", "",
             f"Generators: {d['source']['generators']}. Regions: {d['source']['regions']}. "
             "Nameplate megawatts, summed from EIA's rows. Planned means EIA lists the "
             "generator as planned; it may not be built. Transmission, substations and gas "
             "pipelines are not in this list.", "",
             "| Region | Added since 2020 (MW) | Retired since 2020 (MW) | Planned (MW) | Largest plants |",
             "|---|---:|---:|---:|---|"]
    for g, v in sorted(d["regions"].items(), key=lambda kv: -kv[1]["added_mw"]):
        top = "; ".join(f"{p['plant']} ({p['county']})" for p in v["plants"][:3]) or "none"
        lines.append(f"| {g} | {v['added_mw']:,.0f} | {v['retired_mw']:,.0f} | {v['planned_mw']:,.0f} | {top} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    d = build()
    save_json(OUT / "regional_generation.json", d)
    (OUT / "regional_generation.md").write_text(markdown(d))
    print(markdown(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
