import json, os, tempfile, unittest
from pathlib import Path


class DigestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        os.environ["RECORDS_ROOT"] = str(root)
        import importlib, harvester.run, harvester.digest
        importlib.reload(harvester.run)
        self.d = importlib.reload(harvester.digest)
        f = root / "data" / "filings" / "229"
        f.mkdir(parents=True)
        good = {"document_id": 229001, "company": "Georgia Power Company", "dockets": [56002],
                "filed_date": "2026-11-19", "harvested": "2026-11-20", "description": "Testimony",
                "url": "u", "attachments": [{"attachment_id": 1, "name": "a.pdf", "sha256": "ab", "text": "pdf"}]}
        bad = {"document_id": 229002, "company": None, "dockets": [], "filed_date": "1900-01-01",
               "harvested": "2026-11-20", "description": "x", "url": "u",
               "attachments": [{"attachment_id": 2, "name": "TS.pdf", "trade_secret_marked": True}]}
        for r in (good, bad):
            (f / f"{r['document_id']}.json").write_text(json.dumps(r))
        daily = root / "data" / "daily"
        daily.mkdir(parents=True)
        (daily / "2026-11-20.json").write_text("[229001, 229002]")

    def tearDown(self):
        os.environ.pop("RECORDS_ROOT", None)
        self.tmp.cleanup()

    def test_flags_and_spot_check(self):
        text = self.d.build("2026-11-20", friday=True)
        self.assertIn("2 new filings found tonight", text)
        self.assertIn("placeholder", text)
        self.assertIn("marked trade secret", text)
        self.assertIn("## Friday spot check", text)
        self.assertIn("SHA-256 `ab`", text)

    def test_spot_check_is_repeatable(self):
        recs = list(self.d.all_filings())
        a = [r["document_id"] for r in self.d.spot_check(recs, "2026-11-20")]
        b = [r["document_id"] for r in self.d.spot_check(recs, "2026-11-20")]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
