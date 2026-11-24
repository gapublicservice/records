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


if __name__ == "__main__":
    unittest.main()
