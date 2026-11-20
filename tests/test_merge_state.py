import unittest

from harvester.merge_state import merge


class MergeState(unittest.TestCase):
    def test_backfill_keeps_nightly_recheck_list_and_own_cursor(self):
        theirs = {"empty": {"230001": "2026-11-20"}, "last_nightly": "2026-11-20",
                  "backfill_cursor": {"1-2": 5}, "backfill_empty": [10, 11],
                  "highest_found": 230000}
        ours = {"empty": {}, "backfill_cursor": {"1-2": 5, "200-300": 250},
                "backfill_empty": [11, 12, 13], "highest_found": 229480}
        out = merge(theirs, ours, "backfill", "200-300", exists=lambda n: n == 13)
        self.assertEqual(out["empty"], {"230001": "2026-11-20"})
        self.assertEqual(out["backfill_cursor"], {"1-2": 5, "200-300": 250})
        self.assertEqual(out["backfill_empty"], [10, 11, 12])
        self.assertEqual(out["highest_found"], 230000)

    def test_finished_backfill_drops_its_cursor(self):
        theirs = {"backfill_cursor": {"200-300": 210}}
        out = merge(theirs, {"backfill_cursor": {}}, "backfill", "200-300", exists=lambda n: False)
        self.assertEqual(out["backfill_cursor"], {})

    def test_nightly_takes_its_own_keys(self):
        theirs = {"empty": {"1": "a"}, "backfill_cursor": {"x": 1}, "highest_found": 5}
        ours = {"empty": {}, "gaps": [3], "last_nightly": "d", "backfill_cursor": {}, "highest_found": 9}
        out = merge(theirs, ours, "nightly", exists=lambda n: False)
        self.assertEqual(out["empty"], {})
        self.assertEqual(out["gaps"], [3])
        self.assertEqual(out["backfill_cursor"], {"x": 1})
        self.assertEqual(out["highest_found"], 9)


if __name__ == "__main__":
    unittest.main()
