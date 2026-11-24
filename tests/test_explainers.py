import unittest

from harvester import explainers

DRAFT = {"dockets": [57171], "category": "Fuel", "text": "A draft.", "approved": False}
OK = {"dockets": [56298, 56310], "category": "Certification", "text": "Approved text <b>.",
      "scope_contested": "One side disputes the scope.", "approved": True, "approved_on": "2026-11-30",
      "sources": [{"document_id": 224953, "label": "Order, Dec 30, 2025"}]}


class ExplainerTest(unittest.TestCase):
    def test_draft_is_never_shown(self):
        self.assertEqual(explainers.block(57171, [DRAFT]), "")

    def test_approved_needs_a_date(self):
        self.assertEqual(explainers.block(56298, [dict(OK, approved_on="")]), "")

    def test_approved_entry_shows_on_each_docket_it_names(self):
        for d in (56298, "56310"):
            html = explainers.block(d, [OK])
            self.assertIn("Approved text &lt;b&gt;.", html)
            self.assertIn("One side disputes the scope.", html)
            self.assertIn("documentId=224953", html)
            self.assertIn("Checked 2026-11-30", html)

    def test_no_entry_no_block(self):
        self.assertEqual(explainers.block(44280, [OK]), "")

    def test_public_file_holds_no_unapproved_text(self):
        self.assertTrue(all(explainers.shown(x) for x in explainers.load()))

    def test_auto_line_is_off_by_default(self):
        self.assertFalse(explainers.AUTO_ON)
        self.assertEqual(explainers.auto_block({"title": "x", "industry": "Gas"}, None), "")

    def test_auto_categories(self):
        c = explainers.auto_category
        self.assertEqual(c("Warner Excavation, LLC", "GUFPA"), "Utility facility protection")
        self.assertEqual(c("Liberty 2020 Rate Case.", "Gas"), "Rate case")
        self.assertEqual(c("2025 - 2028 AGL's Capacity Supply Plan", "Gas"), "Fuel")
        self.assertEqual(c("Application for Natural Gas Certificate of Authority", "Gas"), "Certification")
        self.assertEqual(c("Georgia Power Company", "Electric"), "Other")

    def test_auto_line_says_it_is_not_reviewed(self):
        explainers.AUTO_ON = True
        try:
            h = explainers.auto_block({"title": "Tariff Revision", "industry": "Gas", "date": "2019-06-29",
                                       "status": "Open"}, {"company": "Atlanta Gas Light Company", "filed_date": "2022-09-15"})
            self.assertIn("not reviewed", h)
            self.assertIn("Tariff or rule change", h)
            self.assertNotIn("2019", h)  # bulk listing date left out
            self.assertIn("Status open", h)
            self.assertIn("Earliest filing in this record: Atlanta Gas Light Company, Sep 15, 2022.", h)
        finally:
            explainers.AUTO_ON = False


if __name__ == "__main__":
    unittest.main()
