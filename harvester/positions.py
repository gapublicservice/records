"""Where parties stand: positions on the record, docket by docket.

    python -m harvester.positions --check    # verify every entry against stored filing text

Each docket file in data/reference/positions/ lists, for one contested question,
what each party asked the Commission to do, in our own words, with the filing
where it says so. A position is shown only when its "check" phrase is found in
the stored text of that filing, so every summary can be traced to the record.
Nothing here is a judgment about who is right.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "reference" / "positions"
AGENDAS = ROOT / "data" / "reference" / "agendas"
PSC_DOC = "https://psc.ga.gov/search/facts-document/?documentId="
e = html.escape

ROLE_ORDER = {"Utility": 0, "Commission staff": 1, "Intervenor": 2}
SPONSOR_NAMES = ("Georgia Conservation Voters Education Fund", "Georgia Conservation Voters", "GCV Education Fund", "GCVEF")


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("­", "")
    return re.sub(r"\s+", " ", re.sub(r"-\s*\n\s*", "", s)).strip().lower()


def text_of(doc_id: int, file_id: int) -> str | None:
    p = ROOT / "data" / "text" / str(doc_id // 1000) / str(doc_id) / f"{file_id}.txt"
    return p.read_text(errors="replace") if p.exists() else None


def found(pos: dict) -> bool:
    t = text_of(int(pos["document_id"]), int(pos["file_id"]))
    return bool(t and pos.get("check") and _norm(pos["check"]) in _norm(t))


def load() -> list[dict]:
    out = []
    for p in sorted(DIR.glob("*.json")):
        d = json.loads(p.read_text())
        d["_file"] = p.name
        shown, held = [], []
        for pos in d.get("positions", []):
            (shown if found(pos) else held).append(pos)
        shown.sort(key=lambda x: (ROLE_ORDER.get(x.get("role"), 9), x.get("party", "")))
        d["shown"], d["held"] = shown, held
        dates = [x.get("date", "") for x in d.get("positions", [])] + [(d.get("outcome") or {}).get("date", "")]
        d["_latest"] = max(dates) if dates else ""
        out.append(d)
    out.sort(key=lambda d: d["_latest"], reverse=True)
    out.sort(key=lambda d: d.get("status") != "open")
    return out


def has_sponsor(d: dict) -> bool:
    names = ([p.get("party", "") + " " + p.get("asked", "") for p in d.get("shown", [])]
             + d.get("parties_without_stated_position", []))
    return any(any(s in n for s in SPONSOR_NAMES) for n in names)


def _src(x: dict, up: str) -> str:
    return (f'<a href="{PSC_DOC}{int(x["document_id"])}">{e(x.get("source_title", "Filing"))}</a>'
            f' · <span class="mono">{e(x.get("date", ""))}</span>')


def section(d: dict, up: str = "") -> str:
    k = str(d["docket"])
    rows = []
    for p in d["shown"]:
        where = f'<br><span class="muted">Where: {e(p["where"])}. Look for: “{e(p["check"])}”</span>' if p.get("where") else ""
        rows.append(f'<tr><td><b>{e(p["party"])}</b><br><span class="muted">{e(p.get("role", ""))}</span></td>'
                    f'<td>{e(p["asked"])}</td><td>{_src(p, up)}{where}</td></tr>')
    out = d.get("outcome")
    outcome = (f'<p><b>What the Commission decided:</b> {e(out["summary"])} {_src(out, up)}</p>' if out else
               '<p><b>Status:</b> open. The Commission has not decided this question yet.</p>')
    disc = ('<p class="ps-disclosure">The editor of this site works for Georgia Conservation Voters and the Georgia '
            'Conservation Voters Education Fund. One of them is a party in this docket, alone or on a joint filing. '
            'Its position is shown by the same rules as every other party\'s.</p>'
            if has_sponsor(d) else "")
    quiet = d.get("parties_without_stated_position") or []
    quiet_html = (f'<p class="muted">Parties on the docket with no stated position we could read: {e("; ".join(quiet))}.</p>'
                  if quiet else "")
    return (f'<section class="ps-pos" id="d{e(k)}"><h2><span class="mono">{e(k)}</span> · {e(d.get("short", ""))}</h2>'
            f'<p class="muted">{e(d.get("phase", ""))} · <a href="{up}docket/{e(k)}/">All filings in this docket</a></p>'
            f'<p class="lede">{e(d.get("question", ""))}</p>{disc}{outcome}'
            '<table class="wide"><thead><tr><th>Party</th><th>What they asked the Commission to do</th>'
            f'<th>Where they said it</th></tr></thead><tbody>{"".join(rows)}</tbody></table>{quiet_html}</section>')


def load_agendas() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(AGENDAS.glob("*.json"))] if AGENDAS.exists() else []


def agenda_section(a: dict) -> str:
    groups = []
    for g in a.get("groups", []):
        items = []
        for it in g.get("items", []):
            dk = "".join(f' <a href="docket/{int(n)}/">Docket {int(n)}</a>.' for n in it.get("dockets", []))
            items.append(f'<li>{e(it["ask"])}{dk} <span class="muted">When: {e(it.get("when", "not given"))}.</span></li>')
        groups.append(f'<h3>{e(g["heading"])}</h3><ul>{"".join(items)}</ul>')
    return (f'<section class="ps-pos" id="agenda-{e(a["id"])}"><h2>{e(a["org"])} · {e(a["label"])}</h2>'
            f'<p class="lede">{e(a["title"])}</p>'
            f'<p class="ps-disclosure">{e(a["relationship"])} This is an advocacy agenda, not a filing at the Commission. '
            'It is summarized here in our words as a source, and it is not this site\'s position.</p>'
            f'{"".join(groups)}<p class="muted">Source: {e(a["source"])}</p></section>')


def agendas_body(agendas: list[dict]) -> str:
    if not agendas:
        return ""
    return ('<h2 id="agendas">Published agendas</h2><p>What organizations ask the Commission to do outside any one docket. '
            'These are not filings. Any organization\'s published agenda can be added on the same terms: summarized in our words, '
            'with its source named.</p>' + "".join(agenda_section(a) for a in agendas))


def page_body(docs: list[dict], note: str) -> str:
    agendas = load_agendas()
    agenda_toc = (f'<p>Also on this page: <a href="#agendas">published agendas</a> '
                  f'({e("; ".join(a["org"] + ", " + a["label"] for a in agendas))}).</p>' if agendas else "")
    toc = "".join(f'<li><a href="#d{d["docket"]}"><span class="mono">{d["docket"]}</span> {e(d.get("short", ""))}</a>'
                  f' <span class="muted">({"open" if d.get("status") == "open" else "decided"}, '
                  f'{len(d["shown"])} parties)</span></li>' for d in docs)
    return (f'<div class="kicker">Where parties stand</div><h1>What each party asked the Commission to do</h1>'
            '<p class="lede">For each contested question, every party\'s ask on the public record: the company, '
            'Commission staff and each intervenor, with the filing where they said it.</p>'
            '<div class="note">The summaries are ours; the filing is the authority. A position appears only '
            'when it is on the public record and the phrase shown under it is found in the filing\'s text, '
            'so anyone can check it. Each party\'s last word is used: a brief or proposed order before testimony. '
            'Parties are listed the same way whoever they are. Public Service takes no position on any docket.'
            f'</div>{note}<ul>{toc}</ul>{agenda_toc}' + "".join(section(d) for d in docs) + agendas_body(agendas))


def docket_link(d: str, docs: list[dict] | None = None) -> str:
    docs = docs if docs is not None else load()
    if any(str(x["docket"]) == str(d) and x["shown"] for x in docs):
        return f'<p><a href="../../positions.html#d{e(str(d))}">Where parties stand in this docket</a></p>'
    return ""


STYLE = ('<style>.ps-pos{margin:40px 0}.ps-pos td{vertical-align:top}.ps-disclosure{border:1px solid #e4e4e4;'
         'background:#fafafa;padding:10px 12px;font-size:15px}@media (prefers-color-scheme:dark){.ps-disclosure'
         '{background:transparent;border-color:#444}}</style>')


def write(out: Path, page, note: str) -> list[dict]:
    docs = load()
    (out / "positions.html").write_text(page("Where parties stand", page_body(docs, note), "positions",
                                             extra_head=STYLE))
    return docs


def main(argv=None) -> int:
    bad = 0
    for d in load():
        for p in d["held"]:
            bad += 1
            print(f'{d["_file"]}: not found in filing text: {p.get("party")} doc {p.get("document_id")}: {p.get("check")!r}')
        print(f'{d["_file"]}: {len(d["shown"])} shown, {len(d["held"])} held back')
    return 1 if bad and "--strict" in (argv or sys.argv[1:]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
