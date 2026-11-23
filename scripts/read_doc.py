"""Print the text of one downloaded reference document, for reading in a run log.

    python scripts/read_doc.py doc

Reads PDF (pdftotext), Word, Excel (every sheet, one row per line) and zip
archives of those. Files whose names mark them trade secret are skipped and
not opened. Nothing is saved.
"""

import io
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, ".")
from harvester.extract import docx_text  # noqa: E402
from harvester.psc import is_trade_secret_name  # noqa: E402


def xlsx_text(data: bytes) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"--- sheet: {ws.title}")
        for row in ws.iter_rows(values_only=True):
            cells = ["" if v is None else str(v).strip() for v in row]
            if any(cells):
                out.append(" | ".join(cells).rstrip(" |"))
    return "\n".join(out)


def pdf_text(data: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True,
                              text=True).stdout


def text(name: str, data: bytes) -> str:
    low = name.lower()
    if data[:5] == b"%PDF-" or low.endswith(".pdf"):
        return pdf_text(data)
    if data[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(data))
        names = z.namelist()
        if "[Content_Types].xml" in names:
            if any(n.startswith("xl/") for n in names):
                return xlsx_text(data)
            if any(n.startswith("word/") for n in names):
                return docx_text(data)
        parts = []
        for info in z.infolist():
            if info.is_dir():
                continue
            if is_trade_secret_name(info.filename):
                parts.append(f"===== {info.filename}: skipped, marked trade secret")
                continue
            parts.append(f"===== {info.filename}\n{text(info.filename, z.read(info))}")
        return "\n".join(parts)
    return data.decode("utf-8", "replace")


if __name__ == "__main__":
    path = sys.argv[1]
    for line in text(path, open(path, "rb").read()).splitlines():
        if line.strip():
            print(line)
