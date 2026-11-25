"""Two boxes on each docket page, approved by Paul on Nov 25, 2026:

1. How to comment: the Commission's own comment form, its in-person rules and
   the next date on the Commission's calendar for the docket. A plain how-to
   that takes no side.
2. The official record: what the Commission posts as the record of a
   hearing (court reporter transcripts and filed exhibits, each on the
   Commission's site) and the Commission's own video of meetings that took up
   the docket, kept apart from our unofficial transcripts.

The how-to text paraphrases the Commission's public comment page, its public
comment guidelines and its home page, as read on COMMENT_READ. Check them again
when the Commission changes them; the Commission's pages are the ones to follow.
"""

from __future__ import annotations

import datetime as dt
import html
import re

e = html.escape

PSC_DOC = "https://psc.ga.gov/search/facts-document/?documentId="
PSC_DOCKET = "https://psc.ga.gov/search/facts-docket/?docketId="
COMMENT_PAGE = "https://psc.ga.gov/public-comments/"
GUIDELINES = "https://psc.ga.gov/downloads/pubic-comment-guidelines.pdf"  # the Commission's own spelling
YOUTUBE = "https://www.youtube.com/@GeorgiaPSC"
ROOM = "Room 110, 244 Washington Street SW, Atlanta"
COMMENT_READ = "Nov 25, 2026"

# The Commission's hearing transcripts, as titled in its dockets: "Hearing Transcript 5-13-2026",
# "Transcript for Hearing held ...", "Transcript to Oral Argument held ...", and the court
# reporter's errata to one.
OFFICIAL_TRANSCRIPT_RX = re.compile(
    r"hearing transcript|transcripts? (?:of|from|for|to) (?:the )?(?:hearings?|oral argument)|errata to the transcript",
    re.I)
EXHIBIT_RX = re.compile(r"\bexhibits?\b", re.I)

_TS_RX = re.compile(r"trade secret|\bconfidential\b", re.I)

KIND_NOTE = {
    "hearing": "At a hearing, public comment is heard at the start of each hearing day.",
    "docket": "At a hearing, public comment is heard at the start of each hearing day.",
    "committee": "At a committee meeting, public comment is heard at the end, after the committee agendas.",
    "session": "Administrative sessions take no public comment in person, so comment online.",
}


def _day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%A}, {d:%B} {d.day}, {d.year}"


def next_date(d: str, cal: list[dict], agenda_items: list[dict], today: str) -> dict | None:
    """The next date on the Commission's calendar that takes up this docket: a meeting the
    calendar lists for it, or a meeting whose agenda names it. None when there isn't one."""
    out = []
    for c in cal:
        if c.get("date", "") >= today and str(d) in {str(x) for x in c.get("dockets") or []}:
            out.append({"date": c["date"], "time": c.get("time") or "", "kind": c.get("kind") or "",
                        "title": c.get("title") or "Commission meeting", "href": c.get("url") or "", "ours": ""})
    for a in agenda_items:
        if a.get("date", "") >= today:
            out.append({"date": a["date"], "time": a.get("time") or "", "kind": a.get("kind") or "",
                        "title": f'{a.get("label") or "Agenda"} names this docket', "href": a.get("event") or "",
                        "ours": a.get("page") or ""})
    if not out:
        return None
    return min(out, key=lambda x: (x["date"], x["time"]))


def comment_box(d: str, nxt: dict | None, up: str = "../../") -> str:
    if nxt:
        when = _day(nxt["date"]) + (f' at {nxt["time"]}' if nxt["time"] else "")
        what = (f'<a href="{e(nxt["href"])}">{e(nxt["title"])}</a>' if nxt["href"] else e(nxt["title"]))
        ours = f' · <a href="{up}{e(nxt["ours"])}#d{e(d)}">The agenda</a>' if nxt["ours"] else ""
        tip = KIND_NOTE.get(nxt["kind"], "")
        date_line = (f'<p class="cb-next"><b>Next on the Commission\'s calendar:</b> {e(when)}. {what}{ours}'
                     f'{(" " + e(tip)) if tip else ""}</p>')
    else:
        date_line = ('<p class="cb-next"><b>Next on the Commission\'s calendar:</b> no upcoming hearing or meeting '
                     f'lists this docket yet. <a href="{up}calendar.html">The Commission calendar</a>.</p>')
    return f"""<section class="comment-box" id="comment" aria-labelledby="comment-h">
<h2 id="comment-h">How to comment on this docket</h2>
{date_line}
<ul>
<li><b>Online:</b> use the <a href="{COMMENT_PAGE}">Commission's public comment form</a> and give docket number <span class="mono">{e(d)}</span>. The Commission says comments must be in 24 hours before a Commission vote. Leave an email address if you want a receipt.</li>
<li><b>In person:</b> hearings and meetings are open to the public in {e(ROOM)}. Sign up on the Commission's sheet; speakers are called first come, first served, and each gets up to 3 minutes. Public comment is heard at the start of each hearing day and at the end of committee meetings, and not at administrative sessions.</li>
<li><b>Watch:</b> hearings and meetings stream live on the <a href="{YOUTUBE}">Commission's YouTube channel</a>.</li>
</ul>
<p class="copied">Paraphrased from the Commission's <a href="{COMMENT_PAGE}">public comment page</a>, its <a href="{GUIDELINES}">public comment guidelines</a> and its home page, as read {COMMENT_READ}. The Commission's own pages are the ones to follow; check them before you go. Public Service does not collect or pass on comments.</p>
</section>"""


def official_transcripts(fs: list[dict]) -> list[dict]:
    return [r for r in fs if OFFICIAL_TRANSCRIPT_RX.search(r.get("description") or "")]


def exhibit_filings(fs: list[dict]) -> list[dict]:
    """Filings whose own title names exhibits, leaving out trade-secret versions."""
    return [r for r in fs if EXHIBIT_RX.search(r.get("description") or "")
            and not _TS_RX.search(r.get("description") or "")
            and not OFFICIAL_TRANSCRIPT_RX.search(r.get("description") or "")]


def _row(r: dict, marker) -> str:
    return (f'<li><span class="mono tl-date">{e(r.get("filed_date") or "")}</span> '
            f'<a href="{PSC_DOC}{r["document_id"]}">{e((r.get("description") or "").strip())}</a>'
            f' <span class="muted">{e(r.get("company") or "")}</span> {marker(r["document_id"], r.get("files"))}</li>')


def videos_for(agenda_items: list[dict], meet_day: dict) -> list[dict]:
    """Meetings whose agenda names this docket and whose Commission video we transcribed."""
    out, seen = [], set()
    for a in agenda_items:
        m = meet_day.get((a.get("date"), a.get("kind")))
        if m and m["id"] not in seen:
            seen.add(m["id"])
            out.append({"m": m, "a": a})
    return out


def official_box(d: str, fs: list[dict], agenda_items: list[dict], meet_day: dict, marker, kind_label: dict,
                 up: str = "../../") -> str:
    trs = official_transcripts(fs)
    exs = exhibit_filings(fs)
    vids = videos_for(agenda_items, meet_day)
    if trs:
        tr_html = (f'<ul class="off-list">{"".join(_row(r, marker) for r in trs)}</ul>'
                   '<p class="muted">Filed by the Commission in this docket. Where no file is posted, the '
                   'Commission\'s page for the filing is the place to ask for it.</p>')
    else:
        tr_html = ('<p class="muted">No hearing transcript is filed in this docket in our record, which starts in '
                   f'September 2022. <a href="{PSC_DOCKET}{e(d)}">The docket on the Commission\'s site</a> is the one to check.</p>')
    ex_html = (f'<details><summary>{len(exs)} filing{"s" if len(exs) != 1 else ""} whose title names exhibits</summary>'
               f'<ul class="off-list">{"".join(_row(r, marker) for r in exs)}</ul></details>'
               if exs else '<p class="muted">No filing in this docket has a title that names exhibits.</p>')
    if vids:
        v_rows = "".join(
            f'<li><span class="mono tl-date">{e(v["m"]["date"])}</span> {e(kind_label.get(v["m"]["kind"], "Meeting"))}: '
            f'<a href="{e(v["m"].get("source_page") or YOUTUBE)}">The Commission\'s video</a> '
            f'<span class="tag official">Official</span> · <a href="{up}transcript/{e(v["m"]["id"])}/">Our transcript</a> '
            f'<span class="tag unofficial">Unofficial</span></li>' for v in vids)
        v_html = f'<ul class="off-list">{v_rows}</ul>'
    else:
        v_html = ""
    return f"""<section class="official" id="official" aria-labelledby="official-h">
<h2 id="official-h">The official record</h2>
<p class="muted">The Commission's own record of this docket is on <a href="{PSC_DOCKET}{e(d)}">its docket page</a>. These links go there. Our unofficial transcripts of administrative sessions and committee meetings are marked Unofficial and are not the record.</p>
<h3>Hearing transcripts <span class="tag official">Official</span></h3>
{tr_html}
<h3>Testimony and exhibits <span class="tag official">Official</span></h3>
{ex_html}
<h3>Video</h3>
{v_html}<p class="muted">The Commission streams and keeps its hearings and meetings on <a href="{YOUTUBE}">its YouTube channel</a>.</p>
</section>"""


def transcript_official(m: dict, ev_url: str | None, agendas: dict, known=None, up: str = "../../") -> str:
    """On an unofficial transcript page: where the official versions are."""
    ev = (agendas.get(ev_url) or {}) if ev_url else {}
    nums = []
    for f in ev.get("files") or []:
        for it in f.get("items") or []:
            n = str(it.get("docket"))
            if n not in nums and (known is None or n in known):
                nums.append(n)
    dk = ""
    if nums:
        links = ", ".join(f'<a class="mono" href="{up}docket/{e(n)}/#official">{e(n)}</a>' for n in nums)
        dk = f" Dockets on this meeting's agenda, each with links to its official record: {links}."
    src = m.get("source_page") or YOUTUBE
    page_link = f' and <a href="{e(ev_url)}">its page for this meeting</a>' if ev_url else ""
    return (f'<div class="official-note"><p><span class="tag unofficial">Unofficial</span> This transcript is ours, made by machine. '
            f'<span class="tag official">Official</span> The Commission\'s own record is <a href="{e(src)}">its video</a>{page_link}. '
            f'Our record shows no Commission transcript of administrative sessions or committee meetings; for hearings, the '
            f'Commission files a court reporter\'s transcript in the docket.{dk}</p></div>')
