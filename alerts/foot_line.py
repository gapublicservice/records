"""Take the GCVEF sponsor line off Public Service posts and pages on Ghost.

Paul, Nov 25: "No sponsors for now. Remove all of them." A sponsor credit comes
back only if GCV or GCVEF funds the site. The same pass swaps the old "not a
work product" independence wording for the editorial policy's line.

Run by hand through the "Ghost foot line" workflow. Dry run by default: it lists
what it would change. With --apply it saves each changed post or page in place
(published posts stay published; nothing is emailed).
"""
from __future__ import annotations

import argparse
import json

from alerts.ghost import Ghost

SPONSOR = [" Sponsored by the Georgia Conservation Voters Education Fund (GCVEF).",
           " Sponsored by the Georgia Conservation Voters Education Fund."]
OLD_INDEP = "It is not a work product of the Georgia Public Service Commission."
NEW_INDEP = "It is not a product or publication of the Georgia Public Service Commission."


def fix(text: str) -> str:
    for s in SPONSOR:
        text = text.replace(s, "")
    return text.replace(OLD_INDEP, NEW_INDEP)


def run(apply: bool, g: Ghost | None = None) -> int:
    g = g or Ghost()
    changed = 0
    for kind in ("posts", "pages"):
        page = 1
        while page:
            res = g.call("GET", f"/{kind}/", formats="lexical,html", limit=50, page=page, filter="status:[published,draft,scheduled]")
            for item in res.get(kind, []):
                lex = item.get("lexical") or ""
                if "Sponsored by the Georgia Conservation Voters" not in lex and OLD_INDEP not in lex:
                    continue
                new = fix(lex)
                json.loads(new)  # still valid JSON
                print(f"{'SAVE' if apply else 'would save'} {kind[:-1]} {item['slug']} ({item['status']})")
                changed += 1
                if apply:
                    g.call("PUT", f"/{kind}/{item['id']}/",
                           {kind: [{"lexical": new, "updated_at": item["updated_at"]}]})
            page = (res.get("meta", {}).get("pagination", {}) or {}).get("next")
    # Read back: nothing should still carry the sponsor line.
    left = 0
    if apply:
        for kind in ("posts", "pages"):
            res = g.call("GET", f"/{kind}/", formats="lexical", limit="all", filter="status:[published,draft,scheduled]")
            for item in res.get(kind, []):
                if "Sponsored by the Georgia Conservation Voters" in (item.get("lexical") or ""):
                    print(f"STILL HAS SPONSOR: {kind[:-1]} {item['slug']}")
                    left += 1
    print(f"{changed} {'saved' if apply else 'to change'}; {left} still carrying the sponsor line")
    return 1 if left else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    return run(ap.parse_args().apply)


if __name__ == "__main__":
    raise SystemExit(main())
