import unittest
from harvester import dockets

PAGE = """<html><body><div>Docket Detail</div><div>Docket</div><div> Docket #56002 </div>
<div>Title:</div><div> Georgia Power Company's 2025 Integrated Resource Plan</div>
<div>Industry:</div><div> Electric </div><div>Date:</div><div> 11/13/2024 </div>
<div>Status:</div><div> Open </div><div>Doc</div></body></html>"""


class DocketsTest(unittest.TestCase):
    def test_parse(self):
        r = dockets.parse_docket(56002, PAGE)
        self.assertEqual(r["title"], "Georgia Power Company's 2025 Integrated Resource Plan")
        self.assertEqual(r["industry"], "Electric")
        self.assertEqual(r["date"], "2024-11-13")
        self.assertEqual(r["status"], "Open")

    def test_no_docket(self):
        self.assertIsNone(dockets.parse_docket(1, "<p>nothing</p>"))


if __name__ == "__main__":
    unittest.main()
