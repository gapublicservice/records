"""Keep trade-secret and confidential filings out of the record.

The Commission posts a public (redacted) version and a trade-secret version of
many filings. Only the public version may be copied. A file name is not enough
to tell them apart, so a file is held back when any of these says it is not
the public version:

1. its file name or the filing's description (checked before download)
2. the file's own metadata: PDF title, subject and keywords; Word properties
3. its first pages: a "TRADE SECRET" or "CONFIDENTIAL" banner with no word
   saying the copy is public or redacted
4. its text: a [BEGIN TRADE SECRET] ... [END TRADE SECRET] passage that still
   holds words or figures (in a public version those passages are blanked)

Each check returns a short reason, or None. A held-back file is listed in the
record with the reason, and its text, size and fingerprint are not stored.
"""

from __future__ import annotations

import io
import re
import subprocess
import tempfile
import zipfile
from xml.etree import ElementTree

# Words that say a copy is the protected one.
RISK_RE = re.compile(
    r"(?:^|[^a-z0-9])("
    r"ts|trade[\s_-]*secrets?|confidential|unredacted|un[\s_-]redacted|"
    r"under[\s_-]+seal|sealed|non[\s_-]*public|highly[\s_-]+sensitive|"
    r"protected[\s_-]+materials?|attorneys?['’]?[\s_-]+eyes[\s_-]+only|aeo"
    r")(?:[^a-z0-9]|$)",
    re.I,
)

# Words that say a copy is the public one. "PUBLIC" alone counts, but not
# inside "non-public" or "nonpublic".
SAFE_RE = re.compile(
    r"(?<![a-z0-9])(?<!non[\s_-])(?<!non)(public|redacted)(?![a-z0-9])", re.I)
# In names and descriptions, the Commission's "PD" (public disclosure) counts too.
SAFE_LABEL_RE = re.compile(
    r"(?<![a-z0-9])(?<!non[\s_-])(?<!non)(public|redacted|pd)(?![a-z0-9])", re.I)
# "Ts and Cs" is terms and conditions, not trade secret.
TERMS_RE = re.compile(r"\bt['’]?s\s*(?:and|&)\s*c['’]?s\b", re.I)

# Things that mention trade secrets without being one: a motion or order about
# protecting them, a notice that one was filed, an affidavit supporting a claim.
_ABOUT = (r"(motion|petition|request|order|notice|affidavit|certificate|"
          r"objection|ruling|designation|claim|protective|non[\s_-]*disclosure)")
_TS = r"(trade[\s_-]*secrets?|confidential(?:ity)?)"
ABOUT_RE = re.compile(
    rf"{_ABOUT}[^.]{{0,60}}?{_TS}|{_TS}[\s_-]+(?:treatment[\s_-]+)?{_ABOUT}", re.I)


def label_reason(text: str | None, where: str) -> str | None:
    """A name, description or metadata field that marks the protected copy."""
    t = TERMS_RE.sub(" ", (text or "").strip())
    if not t or not RISK_RE.search(t):
        return None
    if SAFE_LABEL_RE.search(t) or ABOUT_RE.search(t):
        return None
    return f"trade-secret marker in {where}"


def before_download(name: str | None, description: str | None) -> str | None:
    """Checks that need no download. A name with any TS marker is held back,
    as before; a description only when it says nothing about a public copy."""
    from .psc import is_trade_secret_name
    if is_trade_secret_name(name or ""):
        return "trade-secret marker in file name"
    if name and SAFE_LABEL_RE.search(TERMS_RE.sub(" ", name)):
        return None  # the file itself says it is the public copy
    return label_reason(name, "file name") or label_reason(description, "filing description")


# --- the file's own metadata -------------------------------------------------

def pdf_metadata(data: bytes) -> dict[str, str]:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        out = subprocess.run(["pdfinfo", "-enc", "UTF-8", f.name],
                             capture_output=True, timeout=60)
    meta = {}
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        key, _, val = line.partition(":")
        if key in ("Title", "Subject", "Keywords"):
            meta[key.lower()] = val.strip()
    return meta


DC = "{http://purl.org/dc/elements/1.1/}"
CP = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"


def office_metadata(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        try:
            root = ElementTree.fromstring(z.read("docProps/core.xml"))
        except KeyError:
            return {}
    meta = {}
    for tag, key in ((DC + "title", "title"), (DC + "subject", "subject"),
                     (CP + "keywords", "keywords"), (CP + "category", "category")):
        el = root.find(tag)
        if el is not None and el.text:
            meta[key] = el.text.strip()
    return meta


def metadata_reason(name: str, data: bytes) -> str | None:
    ext = (name or "").lower().rsplit(".", 1)[-1] if "." in (name or "") else ""
    try:
        if ext == "pdf" or data[:5] == b"%PDF-":
            meta = pdf_metadata(data)
        elif ext in ("docx", "xlsx", "pptx"):
            meta = office_metadata(data)
        else:
            return None
    except Exception:
        return None
    for key, val in meta.items():
        if label_reason(val, f"file {key}"):
            return f"trade-secret marker in file {key}"
    return None


# --- the file's text ---------------------------------------------------------

FIRST_PAGES = 6000  # about the first two or three pages of pdftotext output

# A banner: a short line that is mostly the marker itself.
BANNER_RE = re.compile(
    r"^[\s*\-–—_=#|]*(?:contains\s+)?(?:highly\s+)?"
    r"(trade\s+secret|confidential|filed\s+under\s+seal|under\s+seal|"
    r"proprietary\s+and\s+confidential|confidential\s+and\s+proprietary|"
    r"protected\s+material|attorneys?['’]?\s+eyes\s+only)"
    r"(?:\s+(?:version|information|material|document|filing|copy|"
    r"pursuant\s+to\s+[^\n]{0,60}))?[\s*\-–—_=#|.:]*$",
    re.I | re.M,
)

TS_BLOCK_RE = re.compile(
    r"(?:\[|<<|\{)\s*(?:begin|start)\s+(?:trade\s+secret|ts|confidential)[^\]>}]*(?:\]|>>|\})"
    r"(.*?)"
    r"(?:\[|<<|\{)\s*end\s+(?:trade\s+secret|ts|confidential)[^\]>}]*(?:\]|>>|\})",
    re.I | re.S,
)


def _block_has_content(inner: str) -> bool:
    """True when a bracketed passage still holds words or figures."""
    if re.search(r"redacted", inner, re.I):
        return False
    t = re.sub(r"confidential|trade\s+secret|page\s+\d+\s+of\s+\d+", "", inner, flags=re.I)
    t = re.sub(r"[xX*■█▇▆▅□▪•·._\-–—\s]+", "", t)
    return len(re.findall(r"[A-Za-z0-9]", t)) >= 3


HEADER_LINES = 10  # a banner sits in the first lines of a page


def _page_heads(text: str, pages: int = 3) -> list[str]:
    heads = []
    for page in text.split("\x0c")[:pages]:
        lines = [ln for ln in page.splitlines() if ln.strip()]
        heads.append("\n".join(lines[:HEADER_LINES]))
    return heads


def text_reason(text: str | None) -> tuple[str | None, str | None]:
    """Returns (reason to hold the file back, reason to flag it for a person).

    A banner at the top of one of the first pages, in a copy that never calls
    itself public or redacted, holds the file back. A bracketed passage that
    still holds figures holds it back too, unless the copy calls itself the
    public version: then the filer's own redaction stands and a person checks.
    """
    if not text:
        return None, None
    public = bool(SAFE_RE.search(text[:FIRST_PAGES]))
    if not public and any(BANNER_RE.search(h) for h in _page_heads(text)):
        return "trade-secret banner at the top of the first pages", None
    for m in TS_BLOCK_RE.finditer(text):
        if _block_has_content(m.group(1)):
            if public:
                return None, "trade-secret passage in a public version may hold figures"
            return "trade-secret passage that is not blanked", None
    return None, None
