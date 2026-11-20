"""Keep the Georgia rows of EIA's monthly generator inventory (Form EIA-860M).

    python -m harvester.eia eia860m.xlsx SOURCE_URL

Writes data/reference/eia860m_ga.csv (one row per generator, every sheet:
operating, planned, retired, canceled) and eia860m_ga.json (where it came from).
The sheet's own column names are kept, so a reader can match them to EIA's.
"""

from __future__ import annotations

import csv
import json
import sys

from .run import DATA

OUT = DATA / "reference"


def main(argv=None) -> int:
    import openpyxl
    path, url = (argv or sys.argv[1:])[:2]
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows, cols = [], ["sheet"]
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        header = None
        for r in it:
            cells = [str(c).strip() if c is not None else "" for c in r]
            if "Plant State" in cells or "Plant ID" in cells:
                header = cells
                break
        if not header:
            continue
        for c in header:
            if c and c not in cols:
                cols.append(c)
        si = header.index("Plant State") if "Plant State" in header else None
        for r in it:
            if si is None or r is None or len(r) <= si or r[si] != "GA":
                continue
            row = {"sheet": ws.title}
            row.update({h: ("" if v is None else v) for h, v in zip(header, r) if h})
            rows.append(row)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "eia860m_ga.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    by = {}
    for r in rows:
        by[r["sheet"]] = by.get(r["sheet"], 0) + 1
    (OUT / "eia860m_ga.json").write_text(json.dumps(
        {"source": "U.S. Energy Information Administration, Form EIA-860M", "url": url,
         "rows": len(rows), "rows_by_sheet": by}, indent=2) + "\n")
    print(len(rows), "Georgia generator rows", by)
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
