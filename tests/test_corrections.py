import unittest

from harvester import corrections


class Corrections(unittest.TestCase):
    def test_off_until_switched_on_and_written(self):
        self.assertFalse(corrections.enabled())

    def test_empty_log(self):
        self.assertIn("No corrections yet.", corrections.body([], "Policy."))

    def test_log_and_policy_escape(self):
        rows = [{"date": "2026-12-03", "page": "positions.html#d57171", "wrong": "<b>x</b>", "changed": "Fixed."}]
        h = corrections.body(rows, "## Heading\n\nA <i>para</i>.")
        self.assertIn("<h3>Heading</h3>", h)
        self.assertNotIn("<b>x</b>", h)
        self.assertNotIn("<i>para</i>", h)
        self.assertIn('href="positions.html#d57171"', h)


if __name__ == "__main__":
    unittest.main()
