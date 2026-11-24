import io
import json
import os
import tempfile
import unittest
import zipfile

from harvester import guard


def pdf_with_title(title: str) -> bytes:
    """A one-page PDF whose Info dictionary carries a title."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
        b"<< /Title (" + title.encode() + b") >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 4 0 R >>\n"
              f"startxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def docx_with(title: str, body: str = "Hello") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("docProps/core.xml",
                   '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
                   'package/2006/metadata/core-properties" '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   f"<dc:title>{title}</dc:title></cp:coreProperties>")
        z.writestr("word/document.xml",
                   '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                   'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
                   f"{body}</w:t></w:r></w:p></w:body></w:document>")
    return buf.getvalue()


class Labels(unittest.TestCase):
    def test_names_and_descriptions(self):
        held = [
            ("testimony_ts.pdf", None),
            ("Smith Testimony CONFIDENTIAL.pdf", None),
            ("exhibit_unredacted.xlsx", None),
            ("report.zip", "Trade Secret SONP Report"),
            ("filing.pdf", "Response filed under seal"),
            ("financials.pdf", "2024 Financial Statements (Highly Sensitive)"),
        ]
        for name, desc in held:
            self.assertIsNotNone(guard.before_download(name, desc), (name, desc))

    def test_public_copies_and_filings_about_trade_secrets(self):
        kept = [
            ("dkt_22403_hedging_jul_2024_pd.zip", "Hedging Report for July 2024 TS"),
            ("financials_-_public.pdf", "2022 Financial Statements (Trade Secret)"),
            ("Testimony.PD.pdf", "Direct testimony, trade secret version filed separately"),
            ("Smith redacted.pdf", None),
            ("motion.pdf", "Motion for Protective Treatment of Trade Secret Information"),
            ("petition.pdf", "Trade Secret Petition"),
            ("tariff.pdf", "Revised Ts and Cs with Disclosure Statement"),
            ("order.pdf", "Order on confidentiality claim"),
        ]
        for name, desc in kept:
            self.assertIsNone(guard.before_download(name, desc), (name, desc))

    def test_non_public_is_not_public(self):
        self.assertIsNotNone(guard.before_download("non-public version.pdf", None))
        self.assertIsNotNone(guard.before_download("nonpublic.pdf", None))


class Metadata(unittest.TestCase):
    def test_pdf_title(self):
        self.assertIsNotNone(guard.metadata_reason("a.pdf", pdf_with_title("TRADE SECRET - Exhibit 4")))
        self.assertIsNone(guard.metadata_reason("a.pdf", pdf_with_title("Exhibit 4 Public Disclosure")))
        self.assertIsNone(guard.metadata_reason("a.pdf", pdf_with_title("Exhibit 4")))

    def test_word_title(self):
        self.assertIsNotNone(guard.metadata_reason("a.docx", docx_with("Confidential testimony")))
        self.assertIsNone(guard.metadata_reason("a.docx", docx_with("Direct testimony")))


class Text(unittest.TestCase):
    def test_banner_at_top_of_page(self):
        t = "TRADE SECRET\nDocket 44280\nTestimony of A. Witness\n" + "words\n" * 50
        self.assertIsNotNone(guard.text_reason(t)[0])
        t = "Docket 44280\n" + "words\n" * 20 + "\x0c  CONFIDENTIAL  \nPage 2\n"
        self.assertIsNotNone(guard.text_reason(t)[0])

    def test_banner_in_public_version_is_fine(self):
        t = "TRADE SECRET\nPUBLIC DISCLOSURE VERSION\nTestimony\n"
        self.assertEqual(guard.text_reason(t), (None, None))

    def test_trade_secret_status_in_a_table_is_fine(self):
        rows = "".join(f"44280\nSTF-1\n{i}\nCOMPLETE\nNONE\n" for i in range(5))
        t = "DATA REQUEST RESPONSE TRANSMITTAL\nDATE: Sep 16, 2024\n" + rows + \
            "44280\nSTF-1\n6\nCOMPLETE\nTRADE SECRET\n"
        self.assertEqual(guard.text_reason(t), (None, None))

    def test_bracketed_passages(self):
        blank = "Cost is [BEGIN TRADE SECRET] xxxxxxx [END TRADE SECRET] per year."
        self.assertEqual(guard.text_reason(blank), (None, None))
        redacted = "[BEGIN TRADE SECRET]\nREDACTED IN ITS ENTIRETY\n[END TRADE SECRET]"
        self.assertEqual(guard.text_reason(redacted), (None, None))
        full = "Cost is [BEGIN TRADE SECRET] $41.7 million [END TRADE SECRET] per year."
        self.assertIsNotNone(guard.text_reason(full)[0])
        public = "PUBLIC DISCLOSURE VERSION\n" + full
        held, review = guard.text_reason(public)
        self.assertIsNone(held)
        self.assertIsNotNone(review)


class Store(unittest.TestCase):
    def test_withheld_files_leave_no_text(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["RECORDS_ROOT"] = d
            try:
                import importlib
                from harvester import run, psc
                importlib.reload(run)
                files = {
                    "1": ("a.pdf", pdf_with_title("CONFIDENTIAL")),
                    "2": ("b.docx", docx_with("Testimony", "TRADE SECRET")),
                    "3": ("c.docx", docx_with("Testimony", "Public words")),
                    "4": ("d_ts.pdf", b"never fetched"),
                }

                class F:
                    fetched = []

                    def get(self, url, max_bytes=None):
                        F.fetched.append(url)
                        return files[url][1]

                f = psc.Filing(document_id=5000, url="u", description="Testimony")
                for aid, (name, _) in files.items():
                    f.attachments.append(psc.Attachment(
                        attachment_id=int(aid), name=name, url=aid,
                        trade_secret_marked=psc.is_trade_secret_name(name)))
                rec = run.store(F(), f, with_text=True)
                by = {a["attachment_id"]: a for a in rec["attachments"]}
                self.assertNotIn("4", F.fetched)
                for aid in (1, 2, 4):
                    self.assertTrue(by[aid]["trade_secret_marked"], aid)
                    self.assertTrue(by[aid]["text"].startswith("not stored"), aid)
                    self.assertNotIn("sha256", by[aid])
                    self.assertNotIn("text_file", by[aid])
                    self.assertFalse(run.text_path(5000, aid).exists())
                self.assertFalse(by[3]["trade_secret_marked"])
                self.assertIn("Public words", run.text_path(5000, 3).read_text())

                # The sweep holds back a stored file that the checks now catch.
                p = run.text_path(5000, 3)
                p.write_text("TRADE SECRET\nTestimony\n")
                run.main(["guard-sweep"])
                saved = json.loads(run.filing_path(5000).read_text())
                a3 = [a for a in saved["attachments"] if a["attachment_id"] == 3][0]
                self.assertTrue(a3["trade_secret_marked"])
                self.assertFalse(p.exists())
            finally:
                del os.environ["RECORDS_ROOT"]


if __name__ == "__main__":
    unittest.main()
