import unittest

from harvester import positions


class NormTest(unittest.TestCase):
    def test_norm_joins_hyphenated_lines_and_quotes(self):
        self.assertEqual(positions._norm("the Com-\n mission’s  order"), "the commission's order")

    def test_missing_text_is_not_found(self):
        self.assertFalse(positions.found({"document_id": 1, "file_id": 1, "check": "anything"}))

    def test_sponsor_disclosure(self):
        d = {"shown": [{"party": "Georgia Conservation Voters Education Fund"}], "parties_without_stated_position": []}
        self.assertTrue(positions.has_sponsor(d))
        self.assertFalse(positions.has_sponsor({"shown": [{"party": "Sierra Club"}]}))


if __name__ == "__main__":
    unittest.main()
