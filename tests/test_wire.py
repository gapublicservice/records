import unittest
from harvester import wire


def row(n, day, company, desc="Filing"):
    return {"document_id": n, "filed_date": day, "company": company, "description": desc, "dockets": [100]}


class WireTest(unittest.TestCase):
    def test_sources(self):
        self.assertEqual(wire.source_of("GPSC"), wire.COMMISSION)
        self.assertEqual(wire.source_of("Hearing Officer"), wire.COMMISSION)
        self.assertEqual(wire.source_of("Staff"), wire.STAFF)
        self.assertEqual(wire.source_of("Georgia Power Company"), wire.UTILITY)
        self.assertEqual(wire.source_of("Walton EMC Natural Gas"), wire.UTILITY)
        self.assertEqual(wire.source_of("Sustainable Newton"), wire.PARTY)

    def test_order_label(self):
        self.assertEqual(wire.filing_item(row(1, "2026-11-20", "GPSC", "FINAL ORDER"))["kind"], "Order")
        self.assertEqual(wire.filing_item(row(2, "2026-11-20", "Staff", "Order request"))["kind"], "Filing")

    def test_priority_drops_lowest_then_shows_newest_first(self):
        rows = [row(i, "2026-11-23", "Sierra Club") for i in range(1, wire.MAX_ITEMS + 5)]
        rows += [row(100, "2026-11-18", "GPSC", "Order"), row(101, "2026-11-19", "Georgia Power Company")]
        rows += [row(200, "2026-11-01", "GPSC")]  # outside the window
        its = wire.items(rows, "2026-11-24", statements=[])
        self.assertEqual(len(its), wire.MAX_ITEMS)
        ids = [x["id"] for x in its]
        self.assertIn("f100", ids)
        self.assertIn("f101", ids)
        self.assertNotIn("f200", ids)
        self.assertEqual(ids[-1], "f100")  # oldest last
        self.assertEqual(sum(1 for x in its if x["source"] == "Party"), wire.MAX_ITEMS - 2)

    def test_statement_needs_approval_in_file(self):
        st = [{"id": "s1", "date": "2026-11-23", "rank": wire.COMMISSIONER, "source": "Commissioner",
               "kind": "Statement", "who": "A", "what": "Quote", "dockets": [], "url": "https://x", "order": 0}]
        its = wire.items([], "2026-11-24", statements=st)
        self.assertEqual(its[0]["kind"], "Statement")
        self.assertIn("“Quote”", wire.item_html(its[0]))

    def test_flag_link_and_json(self):
        its = wire.items([row(5, "2026-11-23", "GPSC")], "2026-11-24", statements=[])
        j = wire.as_json(its, "note")
        self.assertEqual(j["items"][0]["flag"], "https://records.gapublicservice.org/flag.html?item=f5")
        self.assertNotIn("rank", j["items"][0])
        self.assertIn('href="flag.html?item=f5"', wire.item_html(its[0]))


if __name__ == "__main__":
    unittest.main()
