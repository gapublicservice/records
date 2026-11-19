import unittest
from pathlib import Path

from harvester.psc import parse_filing, is_trade_secret_name
from harvester import extract

FIX = Path(__file__).parent / "fixtures"


class ParseFiling(unittest.TestCase):
    def setUp(self):
        self.f = parse_filing(226607, (FIX / "filing_226607.html").read_text())

    def test_fields(self):
        self.assertEqual(self.f.company, "Georgia Power Company")
        self.assertTrue(self.f.description.startswith("Docket No. 55378"))
        self.assertEqual(self.f.filed_date, "2026-05-15")
        self.assertEqual(self.f.received_date, "2026-05-15")
        self.assertEqual(self.f.dockets, [55378])

    def test_attachments_and_trade_secret_marks(self):
        marks = {a.attachment_id: a.trade_secret_marked for a in self.f.attachments}
        self.assertEqual(marks, {107885: False, 107886: True, 107887: False,
                                 107928: True, 107929: False})

    def test_empty_page(self):
        self.assertIsNone(parse_filing(1, "<html><body><h4>Document Detail</h4></body></html>"))


class TradeSecretNames(unittest.TestCase):
    def test_marks(self):
        for name in ["Cover TS (stamp).docx", "TS Assertion.pdf", "dkt_57171_ts.zip",
                     "Trade Secret Version.pdf", "report-TS.pdf"]:
            self.assertTrue(is_trade_secret_name(name), name)
        for name in ["dkt_57171_stf-pia-1_pd.zip", "Tests and Results.pdf",
                     "PD Report.docx", "STS memo.pdf", "Costs.xlsx"]:
            self.assertFalse(is_trade_secret_name(name), name)


class Extract(unittest.TestCase):
    def test_zip_skips_trade_secret(self):
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("answers_pd.txt", "public answer")
            z.writestr("answers_TS.txt", "secret")
        text, how = extract.text_for("x.zip", buf.getvalue())
        self.assertIn("public answer", text)
        self.assertNotIn("secret", text)
        self.assertIn("1 trade-secret", how)


if __name__ == "__main__":
    unittest.main()
