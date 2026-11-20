import unittest
from harvester import regional


class RegionalTest(unittest.TestCase):
    def test_every_region_present_and_sums_match_plants(self):
        d = regional.build()
        self.assertEqual(len(d["regions"]), 12)
        for g, v in d["regions"].items():
            self.assertAlmostEqual(v["added_mw"], sum(p["added_mw"] for p in v["plants"]), delta=1)


if __name__ == "__main__":
    unittest.main()
