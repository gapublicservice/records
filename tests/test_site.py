import unittest
from harvester import site


class SiteTest(unittest.TestCase):
    def test_search_data_shape(self):
        rows = [{"document_id": 1, "filed_date": "2026-01-02", "company": "A", "dockets": [5],
                 "description": "Objection", "units": ["Electric"], "regions": ["Coastal"],
                 "counties_in_title": ["Chatham"], "disagreement": ["objection"]}]
        d = site.build_search_data(rows)
        self.assertEqual(d["units"], ["Electric"])
        self.assertEqual(d["filings"][0], [1, "2026-01-02", "A", [5], "Objection", [0], [0], ["Chatham"], 1, [], []])

    def test_file_marker(self):
        one = site.file_marker(7, {"state": "available", "public": [9], "confidential": 0})
        self.assertIn("DownloadFile/7/9", one)
        many = site.file_marker(7, {"state": "available", "public": [9, 10], "confidential": 1})
        self.assertIn("2 files to download", many)
        self.assertIn("1 confidential", many)
        self.assertIn("1 file marked", many)
        none = site.file_marker(7, {"state": "none", "public": [], "confidential": 0})
        self.assertIn("No file posted", none)
        self.assertIn('role="tooltip"', none)
        self.assertEqual(site.file_marker(7, None), "")

    def test_page_carries_independence_and_sponsor(self):
        html = site.page("T", "<p>x</p>", "search")
        self.assertIn("not a work product of the Georgia Public Service Commission", html)
        self.assertIn("project of Paul Glaze", html)
        self.assertIn("GCVEF", html)


if __name__ == "__main__":
    unittest.main()


def test_external_links_open_in_new_tab():
    from harvester.site import external_new_tab
    out = external_new_tab('<a href="https://psc.ga.gov/x">a</a> <a href="dockets.html">b</a> \'<a class="file ok" href="https://services.psc.ga.gov/y">c</a>\'')
    assert out.count('target="_blank" rel="noopener"') == 2
    assert '<a href="dockets.html">' in out
    assert external_new_tab(out) == out
