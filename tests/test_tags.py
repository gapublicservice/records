import unittest
from harvester import tags


class TagsTest(unittest.TestCase):
    def test_units(self):
        u = tags.own_units({"company": "Alma Telephone Company", "description": "Lifeline report", "dockets": [36946]})
        self.assertIn(tags.TELECOM, u)
        u = tags.own_units({"company": "Staff", "description": "Data request", "dockets": [56002]})
        self.assertEqual(set(u), {tags.ELECTRIC, tags.EERE})

    def test_disagreement(self):
        self.assertEqual(tags.disagreement({"description": "CRG's Petition for Rehearing and Reconsideration"}),
                         ["rehearing or reconsideration"])
        self.assertEqual(tags.disagreement({"description": "GA Slamming Complaint for quarter"}), [])

    def test_counties(self):
        self.assertEqual(tags.counties_in("sites in Ben Hill County and DEKALB county, near Hall"),
                         {"Ben Hill", "DeKalb"})
        self.assertEqual(len(tags.COUNTIES), 159)

    def test_regions(self):
        from harvester.regions import REGIONS, REGION_OF
        self.assertEqual(len(REGIONS), 12)
        self.assertEqual(sorted(REGION_OF), sorted(tags.COUNTIES))
        pl = tags.places({"company": "Georgia Power", "description": "Plant in Bartow County"}, "Chatham County site")
        self.assertEqual(pl["regions"], ["Northwest Georgia"])
        self.assertEqual(pl["regions_in_text"], ["Coastal"])


if __name__ == "__main__":
    unittest.main()
