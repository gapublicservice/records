"""The Corrections page: the corrections policy and a public correction log.

Policy text: data/reference/corrections-policy.md, written by the editor.
    Plain paragraphs separated by blank lines. A line starting "## " is a
    heading. The page stays unbuilt while this file is empty or missing.
Correction log: data/reference/corrections.json, a list of entries, newest
    shown first:
    {"date": "2026-12-03",            # when the correction went up
     "page": "positions.html#d57171", # the page on this site, or a full URL
     "wrong": "What the page got wrong, in plain words.",
     "changed": "What was changed, and when."}
    All four fields are required.

ON controls whether the page, its nav link and its footer link are built.
Switch it on only once the editor's policy text is in.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re

from .run import DATA

ON = False
POLICY = DATA / "reference" / "corrections-policy.md"
LOG = DATA / "reference" / "corrections.json"
FIELDS = ("date", "page", "wrong", "changed")


def policy_text() -> str:
    return POLICY.read_text().strip() if POLICY.exists() else ""


def enabled() -> bool:
    return ON and bool(policy_text())


def load_log() -> list[dict]:
    if not LOG.exists():
        return []
    rows = json.loads(LOG.read_text())
    for i, r in enumerate(rows):
        missing = [f for f in FIELDS if not str(r.get(f, "")).strip()]
        if missing:
            raise SystemExit(f"corrections.json entry {i + 1} is missing {', '.join(missing)}")
        dt.date.fromisoformat(r["date"])
    return sorted(rows, key=lambda r: r["date"], reverse=True)


def _policy_html(text: str) -> str:
    e = html.escape
    out = []
    for block in re.split(r"\n\s*\n", text):
        b = block.strip()
        if b.startswith("## "):
            out.append(f"<h3>{e(b[3:].strip())}</h3>")
        elif b:
            out.append(f"<p>{e(' '.join(b.split()))}</p>")
    return "\n".join(out)


def _page_link(p: str) -> str:
    e = html.escape
    href = p if p.startswith("https://") else p.lstrip("/")
    return f'<a href="{e(href, quote=True)}">{e(p)}</a>'


def body(rows: list[dict] | None = None, policy: str | None = None) -> str:
    e = html.escape
    rows = load_log() if rows is None else rows
    policy = policy_text() if policy is None else policy
    if rows:
        trs = "".join(f'<tr><td class="mono">{e(r["date"])}</td><td>{_page_link(r["page"])}</td>'
                      f'<td>{e(r["wrong"])}</td><td>{e(r["changed"])}</td></tr>' for r in rows)
        log = (f'<table class="wide"><thead><tr><th>Date</th><th>Page</th><th>What was wrong</th>'
               f'<th>What changed</th></tr></thead><tbody>{trs}</tbody></table>')
    else:
        log = '<p class="muted">No corrections yet.</p>'
    return f"""<div class="kicker">Corrections</div>
<h1>Corrections</h1>
<section id="policy">
<h2>Our corrections policy</h2>
{_policy_html(policy)}
</section>
<section id="log">
<h2>Correction log</h2>
<p>Every correction to this site, newest first. The full history of every change is also public in the <a href="https://github.com/gapublicservice/records/commits/main">record's change history</a>.</p>
{log}
</section>"""
