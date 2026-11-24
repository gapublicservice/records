"""Expert views: the checks a panel must pass before it posts.

Rules:
  - Both sides, or one very credible view (Paul, Nov 24): a panel shows views
    on both sides when both have one. A panel with views on one side only may
    post when the reviewer has approved showing it alone (any approved source
    kind) and the line for the empty side is approved; the empty side then
    says none meeting the standards has been found yet.
  - Equal treatment: same fields for every view, ordered by date.
  - A roster set in advance: only listed kinds of source; the publisher and
    its affiliates are never sources.
  - Verified against a public, citable source: every quote is checked against
    a saved copy of that public source, and a named reviewer signs off. A view
    heard only on video posts only once the video is pulled, transcribed and
    saved, with a link to the moment it was said.
  - No call to action in anything the panel shows.
  - A named reviewer approves each panel, and every change is dated.

Files:
  data/legislature/views/roster.json             kinds of source allowed
  data/legislature/views/<session>/<slug>.json    the panel: views + approval
  data/legislature/sources/<id>.txt              saved text of each cited source
  data/legislature/video/<id>/transcript.json    pulled hearing video, transcribed
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

from . import store

VIEWS = store.DATA / "views"
SOURCES = store.DATA / "sources"
VIDEO = store.DATA / "video"

SIDES = ("for", "against_or_concerns")
# A lone view may come from any approved source kind; Paul judges each one (Nov 24, "B").
# Paul approved the empty-side line as drafted (Nov 24). Each lone panel still needs his sign-off.
EMPTY_SIDE_LINE_APPROVED = True
EXCLUDED_ORGS = re.compile(r"\bGeorgia Conservation Voters\b|\bGCVEF?\b", re.I)
CALL_TO_ACTION = re.compile(
    r"\b(call|contact|email|e-mail|write|tell|urge|ask)\s+(your|the|our)\s+"
    r"(legislators?|representatives?|senators?|lawmakers?|members?)\b"
    r"|\bsign\s+(the|our)\s+petition\b|\btake action\b|\burge\s+(lawmakers|legislators|the)\b"
    r"|\bvote\s+(yes|no)\s+on\b", re.I)
REQUIRED = ("id", "side", "who", "role", "kind", "quote", "source_url", "source_title",
            "source_date", "verified_by", "verified_at")


def _words(s: str) -> list[str]:
    s = s.lower().replace("’", "'")
    return re.findall(r"[a-z0-9$%']+", s)


def quote_in(quote: str, text: str, threshold: float = 0.92) -> tuple[bool, float, int]:
    """Is the quote in the text, allowing small transcription differences?
    Returns (found, best ratio, word offset of the best match)."""
    q, t = _words(quote), _words(text)
    if not q:
        return False, 0.0, -1
    joined_q = " ".join(q)
    if joined_q in " ".join(t):
        idx = " ".join(t).index(joined_q)
        return True, 1.0, " ".join(t)[:idx].count(" ")
    best, at = 0.0, -1
    n = len(q)
    step = max(1, n // 4)
    for i in range(0, max(1, len(t) - n + 1), step):
        r = difflib.SequenceMatcher(a=q, b=t[i:i + n], autojunk=False).ratio()
        if r > best:
            best, at = r, i
    if at >= 0:  # refine around the best window
        for i in range(max(0, at - step), min(len(t), at + step + 1)):
            r = difflib.SequenceMatcher(a=q, b=t[i:i + n], autojunk=False).ratio()
            if r > best:
                best, at = r, i
    return best >= threshold, round(best, 3), at


def load_roster() -> dict:
    p = VIEWS / "roster.json"
    return json.loads(p.read_text()) if p.exists() else {"kinds": [], "approved_by": None}


def panel_path(session: str, slug: str) -> Path:
    return VIEWS / session / f"{slug}.json"


def load_panel(session: str, slug: str) -> dict | None:
    p = panel_path(session, slug)
    return json.loads(p.read_text()) if p.exists() else None


def check_view(v: dict, roster: dict) -> list[str]:
    """Problems with one view. Empty means it passes."""
    probs = [f"missing {k}" for k in REQUIRED if not v.get(k)]
    if v.get("side") not in SIDES:
        probs.append("side must be 'for' or 'against_or_concerns'")
    if not str(v.get("source_url", "")).startswith("https://"):
        probs.append("source link must be a public https address")
    kinds = {k["key"] for k in roster.get("kinds", [])}
    if v.get("kind") not in kinds:
        probs.append(f"source kind '{v.get('kind')}' is not on the approved roster")
    if EXCLUDED_ORGS.search(" ".join([v.get("who", ""), v.get("role", "")])):
        probs.append("the publisher and its affiliates are never sources")
    if CALL_TO_ACTION.search(v.get("quote", "")):
        probs.append("quote contains a call to action; choose another passage")
    video = v.get("video")
    if video:
        tp = VIDEO / str(video.get("id", "")) / "transcript.json"
        if not video.get("archive_url"):
            probs.append("video not saved yet (no archive copy)")
        if not tp.exists():
            probs.append("video not transcribed yet")
        else:
            segs = json.loads(tp.read_text())["segments"]
            found, ratio, _ = quote_in(v.get("quote", ""), " ".join(s["text"] for s in segs))
            if not found:
                probs.append(f"quote not found in the transcript (best match {ratio:.0%})")
            if video.get("start_seconds") is None:
                probs.append("no link to the moment it was said")
    else:
        sid = v.get("source_copy")
        sp = SOURCES / f"{sid}.txt" if sid else None
        if not sp or not sp.exists():
            probs.append("no saved copy of the source to check the quote against")
        else:
            found, ratio, _ = quote_in(v.get("quote", ""), sp.read_text())
            if not found:
                probs.append(f"quote not found in the saved source (best match {ratio:.0%})")
    return probs


def panel_status(panel: dict | None, roster: dict | None = None) -> dict:
    """Whether a bill's panel may post, and what it would show.

    Returns {"state": "live"|"held"|"none", "views": [...], "reasons": [...],
             "note": public sentence or None}."""
    roster = roster if roster is not None else load_roster()
    if not panel or not panel.get("views"):
        return {"state": "none", "views": [], "reasons": [], "note": None}
    reasons = []
    if not roster.get("approved_by"):
        reasons.append("the source roster has not been approved")
    good, problems = [], {}
    for v in panel["views"]:
        p = check_view(v, roster)
        if p:
            problems[v.get("id", "?")] = p
        else:
            good.append(v)
    sides = {v["side"] for v in good}
    one_sided = sides != set(SIDES)
    single_ok = (one_sided and bool(good) and EMPTY_SIDE_LINE_APPROVED
                 and bool(panel.get("single_view_approved_by")) and bool(panel.get("single_view_approved_at")))
    if one_sided and not good:
        reasons.append("no view has passed its checks")
    elif one_sided and not single_ok:
        reasons.append("only one side has a view, and it is not approved to show alone"
                       " (needs the reviewer's sign-off and an approved empty-side line)")
    if not panel.get("approved_by") or not panel.get("approved_at"):
        reasons.append("no reviewer has approved this panel")
    if problems:
        reasons.append(f"{len(problems)} view(s) failed checks")
    state = "live" if not reasons else "held"
    note = None
    views = sorted(good, key=lambda v: v["source_date"]) if state == "live" else []
    return {"state": state, "views": views, "reasons": reasons, "problems": problems, "note": note,
            "single": state == "live" and one_sided}


def balance_report(session: str) -> list[dict]:
    """The weekly list: every panel, how many verified views per side, and what holds it."""
    roster = load_roster()
    out = []
    d = VIEWS / session
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        panel = json.loads(p.read_text())
        st = panel_status(panel, roster)
        counts = {s: 0 for s in SIDES}
        for v in panel.get("views", []):
            if not check_view(v, roster):
                counts[v["side"]] += 1
        out.append({"bill": panel.get("bill", p.stem), "state": st["state"], "verified": counts,
                    "reasons": st["reasons"]})
    return out
