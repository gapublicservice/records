"""Clean bill text and compare versions.

Georgia bill PDFs carry line numbers down the left margin, an LC stamp at the
top of each page ("26 LC 44 3498S") and a page footer ("H. B. 7 - 2 -").
clean() strips those so a comparison sees only changes in wording. The
patterns are set from the layout described in the plan and get tuned on the
first live run against real version PDFs.
"""

from __future__ import annotations

import difflib
import html
import re
import subprocess
import tempfile

LC_STAMP = re.compile(r"^\s*\d{2}\s+LC\s+\d+\s+\d+\S*\s*$", re.I)
FOOTER = re.compile(r"^\s*([HS]\.\s*[BR]\.\s*\d+\s*(\([A-Z ]+\)|/[A-Z]+)?)?\s*(-\s*\d+\s*-)?\s*$", re.I)
LINE_NO = re.compile(r"^\s*\d{1,3}(\s{2,}|\t|\s(?=\S))")
SECTION = re.compile(r"\bSECTION\s+(\d+[A-Z]?)\.")
CODE_REF = re.compile(
    r"(?:Code\s+Section|O\.\s*C\.\s*G\.\s*A\.\s*§?)\s*(\d{1,2}-\d{1,3}[A-Z]?-\d{1,4}(?:\.\d+)?)", re.I)
TITLE_REF = re.compile(r"Title\s+(\d{1,2})\s+of\s+the\s+Official\s+Code", re.I)
NUMBER = re.compile(r"^\$?\d[\d,]*(\.\d+)?%?$")


def pdf_text(data: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", f.name, "-"],
                             capture_output=True, timeout=300)
    return out.stdout.decode("utf-8", "replace")


def clean(raw: str) -> str:
    """Bill text with margins, stamps and footers removed, one paragraph a line."""
    lines = []
    for line in raw.replace("\r\n", "\n").replace("\x0c", "\n").split("\n"):
        if LC_STAMP.match(line) or (line.strip() and FOOTER.match(line)):
            continue
        line = LINE_NO.sub("", line, count=1).strip()
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # words split across lines
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    # A paragraph break also comes before each SECTION heading.
    out = []
    for p in paras:
        if not p:
            continue
        out.extend(x.strip() for x in re.split(r"(?=\bSECTION \d+[A-Z]?\.)", p) if x.strip())
    return "\n".join(out) + "\n"


def tokens(text: str) -> list[str]:
    return re.findall(r"\S+|\n", text)


def compare(old: str, new: str) -> dict:
    """Word-by-word comparison plus a plain summary of what changed."""
    a, b = tokens(old), tokens(new)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    ops, added, removed, numbers = [], 0, 0, []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        ops.append((tag, " ".join(a[i1:i2]), " ".join(b[j1:j2])))
        if tag in ("delete", "replace"):
            removed += sum(1 for t in a[i1:i2] if t != "\n")
        if tag in ("insert", "replace"):
            added += sum(1 for t in b[j1:j2] if t != "\n")
        if tag == "replace":
            old_n = [t.strip(".,;:()") for t in a[i1:i2] if NUMBER.match(t.strip(".,;:()"))]
            new_n = [t.strip(".,;:()") for t in b[j1:j2] if NUMBER.match(t.strip(".,;:()"))]
            if old_n or new_n:
                if old_n != new_n:
                    numbers.append({"from": old_n, "to": new_n})
    old_sec, new_sec = set(SECTION.findall(old)), set(SECTION.findall(new))
    old_code, new_code = set(CODE_REF.findall(old)), set(CODE_REF.findall(new))
    return {
        "ops": ops,
        "summary": {
            "words_added": added,
            "words_removed": removed,
            "unchanged": added == 0 and removed == 0,
            "sections_added": sorted(new_sec - old_sec, key=_seckey),
            "sections_dropped": sorted(old_sec - new_sec, key=_seckey),
            "numbers_changed": numbers[:20],
            "code_sections_newly_touched": sorted(new_code - old_code),
            "code_sections_no_longer_touched": sorted(old_code - new_code),
        },
    }


def _line_run(nums: list[str]) -> bool:
    """1 2 3 4: page line numbers that slipped into the text, not figures."""
    if len(nums) < 3 or not all(n.isdigit() for n in nums):
        return False
    v = [int(n) for n in nums]
    return all(b - a == 1 for a, b in zip(v, v[1:]))


def _seckey(s: str):
    m = re.match(r"(\d+)(.*)", s)
    return (int(m.group(1)), m.group(2)) if m else (0, s)


def code_sections(text: str) -> list[str]:
    return sorted(set(CODE_REF.findall(text)))


def code_titles(text: str) -> list[int]:
    titles = {int(t) for t in TITLE_REF.findall(text)}
    titles |= {int(s.split("-")[0]) for s in CODE_REF.findall(text)}
    return sorted(titles)


def summary_lines(s: dict) -> list[str]:
    """Plain sentences for the public page. Facts only, no judgment."""
    if s["unchanged"]:
        return ["The wording did not change."]
    out = [f'{s["words_added"]:,} words added and {s["words_removed"]:,} removed.']
    if s["sections_added"]:
        out.append("New sections: " + ", ".join(s["sections_added"]) + ".")
    if s["sections_dropped"]:
        out.append("Sections no longer in the bill: " + ", ".join(s["sections_dropped"]) + ".")
    # Only a figure that was swapped for another counts. A number that merely
    # appears or vanishes is nearly always a heading or a line number that moved.
    real = [n for n in s["numbers_changed"] if n["from"] and n["to"]
            and not (_line_run(n["from"]) or _line_run(n["to"]))]
    for n in real[:5]:
        out.append(f'A figure changed from {" ".join(n["from"])} to {" ".join(n["to"])}.')
    if s["code_sections_newly_touched"]:
        out.append("Now also amends Code Section " + ", ".join(s["code_sections_newly_touched"]) + ".")
    if s["code_sections_no_longer_touched"]:
        out.append("No longer amends Code Section " + ", ".join(s["code_sections_no_longer_touched"]) + ".")
    return out


def to_html(ops: list[tuple[str, str, str]], context: int = 40) -> str:
    """Red-and-green comparison. Long unchanged stretches fold to their ends."""
    e = html.escape
    parts = []
    for tag, old, new in ops:
        if tag == "equal":
            words = old.split(" ")
            if len(words) > context * 2:
                old = " ".join(words[:context]) + " … " + " ".join(words[-context:])
            parts.append(e(old).replace("\n", "<br>"))
        else:
            if old:
                parts.append(f"<del>{e(old)}</del>")
            if new:
                parts.append(f"<ins>{e(new)}</ins>")
    return " ".join(parts)
