import unittest
from harvester import legal


class LegalTest(unittest.TestCase):
    def test_citations(self):
        t = ("Pursuant to O.C.G.A. §§ 46-2-25; 46-2-26.1 and 46-3A-4, and Rule 515-3-4-.04, "
             "call 404-656-4501 or 515-338-0506. See also O.C.G.A. § 50-13-13 and Docket No. 44280.")
        c = legal.citations(t)
        self.assertEqual(c[:1], ["515-3-4-.04"])
        for s in ("46-2-25", "46-2-26.1", "46-3A-4", "50-13-13"):
            self.assertIn(s, c)
        self.assertFalse(any(x.startswith("515-338") or x.startswith("404") for x in c))

    def test_other_titles_need_a_marker(self):
        self.assertEqual(legal.citations("rooms 50-13-14 and 10-1-760"), [])
        self.assertEqual(legal.citations("O.C.G.A. § 50-18-70"), ["50-18-70"])

    def test_leading_zero(self):
        self.assertEqual(legal.citations("O.C.G.A. § 46-3A-05"), ["46-3A-5"])

    def test_rule_variant(self):
        self.assertEqual(legal.citations("Rule 515-2-1.06"), ["515-2-1-.06"])

    def test_hooks(self):
        rec = {"document_id": 1, "description": "Petition under O.C.G.A. § 46-2-26"}
        h = legal.legal_hooks(rec, "Staff may seek discovery under O.C.G.A. § 46-2-57 and Rule 515-3-4-.06.")
        self.assertEqual(h["legal"], ["IRP and RFP rules", "Fuel cost recovery law"])
        self.assertIn("title", h["legal_reasons"]["Fuel cost recovery law"])
        self.assertIn("text", h["legal_reasons"]["IRP and RFP rules"])
        self.assertEqual(h["procedural_cites"], 1)
        self.assertNotIn("46-2-57", h["laws_cited"])

    def test_groups(self):
        self.assertEqual(legal.law_of("46-3-11"), "Territorial Electric Service Act")
        self.assertEqual(legal.law_of("46-3-55"), "Cogeneration and Distributed Generation Act")
        self.assertIsNone(legal.law_of("46-3-65"))

    def test_proceedings(self):
        p = legal.proceedings("GEORGIA POWER COMPANY’S APPLICATION FOR THE CERTIFICATION OF THE 2029-2031 ALL-SOURCE CAPACITY RFP")
        self.assertEqual(set(p), {"Certification", "Request for proposals"})
        self.assertEqual(set(legal.proceedings("Georgia Power Company's Fuel Cost Recovery (FCR-27)")), {"Fuel cost recovery"})

    def test_links(self):
        self.assertEqual(legal.code_url("46-2-26.1"),
                         "https://law.justia.com/codes/georgia/title-46/chapter-2/article-2/section-46-2-26-1/")
        self.assertIsNone(legal.code_url("46-2-57"))
        self.assertEqual(legal.code_url("515-3-4-.04"), "https://rules.sos.ga.gov/gac/515-3-4")
