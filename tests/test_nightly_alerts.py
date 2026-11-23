import unittest

from alerts import nightly


class NightlyAlerts(unittest.TestCase):
    def test_no_filings_means_no_groups(self):
        self.assertEqual(nightly.by_docket([]), {})

    def test_groups_by_every_docket(self):
        f = [{"document_id": 2, "dockets": [57171, 56765]}, {"document_id": 1, "dockets": [57171]}]
        g = nightly.by_docket(f)
        self.assertEqual([r["document_id"] for r in g["57171"]], [1, 2])
        self.assertEqual(len(g["56765"]), 1)

    def test_title_is_stable_for_reruns(self):
        self.assertEqual(nightly.title_for("57171", 1, "2026-11-24"), "Docket 57171: 1 new filing, November 24, 2026")
        self.assertEqual(nightly.title_for("57171", 3, "2026-11-24"), "Docket 57171: 3 new filings, November 24, 2026")

    def test_email_escapes_and_caps(self):
        f = [{"document_id": i, "description": "<b>x</b>", "company": "Co", "filed_date": "2026-11-23"} for i in range(30)]
        h = nightly.email_html("57171", f, "Real-Time Pricing")
        self.assertNotIn("<b>x</b>", h)
        self.assertEqual(h.count("<li>"), nightly.MAX_LISTED)
        self.assertIn("And 5 more", h)
        self.assertIn("not a product of the Georgia Public Service Commission", h)


if __name__ == "__main__":
    unittest.main()
