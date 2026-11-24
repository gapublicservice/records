"""Turn public attachments into searchable text.

PDF: pdftotext (poppler). Word: the document XML. Plain text and CSV: as is.
Zip: each file inside, by the same rules, skipping any that the trade-secret
checks in guard.py hold back. Spreadsheets and other formats are listed, not read yet.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import tempfile
import zipfile
from xml.etree import ElementTree

from . import guard

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _ext(name: str) -> str:
    return os.path.splitext(name or "")[1].lower()


def pdf_text(data: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", f.name, "-"],
                             capture_output=True, timeout=300)
    return out.stdout.decode("utf-8", "replace")


def docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    paras = []
    for p in root.iter(W_NS + "p"):
        paras.append("".join(t.text or "" for t in p.iter(W_NS + "t")))
    return "\n".join(paras)


def text_for(name: str, data: bytes) -> tuple[str | None, str]:
    """Returns (text or None, how). how says what was done, for the record."""
    ext = _ext(name)
    if not ext and data[:5] == b"%PDF-":
        ext = ".pdf"
    try:
        if ext == ".pdf":
            return pdf_text(data), "pdftotext"
        if ext == ".docx":
            return docx_text(data), "docx"
        if ext in (".txt", ".csv"):
            return data.decode("utf-8", "replace"), "plain"
        if ext == ".zip":
            return zip_text(data)
    except Exception as e:  # a bad file should not stop the night
        return None, f"failed: {type(e).__name__}"
    return None, f"not read: {ext or 'unknown type'}"


def zip_text(data: bytes) -> tuple[str | None, str]:
    parts, skipped, unread = [], 0, 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            if guard.before_download(info.filename, None):
                skipped += 1
                continue
            if info.file_size > 50_000_000:
                continue
            member = z.read(info)
            if guard.metadata_reason(info.filename, member):
                skipped += 1
                continue
            inner, _ = text_for(info.filename, member)
            if inner and guard.text_reason(inner)[0]:
                skipped += 1
                continue
            if inner:
                parts.append(f"===== {info.filename} =====\n{inner}")
            else:
                unread += 1
    notes = [f"{len(parts)} read"]
    if unread:
        notes.append(f"{unread} not read")
    if skipped:
        notes.append(f"{skipped} trade-secret-marked files skipped")
    how = "zip (" + ", ".join(notes) + ")"
    return ("\n\n".join(parts) or None), how


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\x0c", "\n")
    return re.sub(r"\n{4,}", "\n\n\n", text).strip() + "\n"
