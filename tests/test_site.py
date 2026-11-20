import unittest
from harvester import site


class SiteTest(unittest.TestCase):
    def test_search_data_shape(self):
        rows = [{"document_id": 1, "filed_date": "2026-01-02", "company": "A", "dockets": [5],
                 "description": "Objection", "units": ["Electric"], "regions": ["Coastal"],
                 "counties_in_title": ["Chatham"], "disagreement": ["objection"]}]
        d = site.build_search_data(rows)
        self.assertEqual(d["units"], ["Electric"])
        self.assertEqual(d["filings"][0], [1, "2026-01-02", "A", [5], "Objection", [0], [0], ["Chatham"], 1])

    def test_page_carries_independence_and_sponsor(self):
        html = site.page("T", "<p>x</p>", "search")
        self.assertIn("not a product of the Georgia Public Service Commission", html)
        self.assertIn("GCVEF", html)


if __name__ == "__main__":
    unittest.main()
