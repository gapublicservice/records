import json
import unittest

from harvester import site


class TimelineStripTest(unittest.TestCase):
    def test_month_box_data(self):
        fs = [
            {"filed_date": "2026-01-05", "document_id": 1, "company": "Staff", "description": "Data request"},
            {"filed_date": "2026-03-02", "document_id": 2, "company": "GPSC", "description": "ORDER </script>"},
        ]
        ev = [{"date": "2026-03-02", "kind": "order", "label": "Commission order", "text": "",
               "href": site.PSC_DOC + "2"},
              {"date": "2026-02-10", "kind": "meeting", "label": "On the agenda: Energy committee", "text": "", "href": ""}]
        out = site.timeline_strip(fs, ev)
        self.assertIn('data-m="2026-02"', out)  # empty month still pickable
        blob = out.split('class="tl-data">', 1)[1].split("</script>", 1)[0]
        data = json.loads(blob)
        self.assertEqual(data["2026-03"]["f"][0][4], "Commission order")
        self.assertEqual(data["2026-02"]["m"][0][1], "On the agenda: Energy committee")
        self.assertEqual(data["2026-01"]["f"][0][3], 1)


if __name__ == "__main__":
    unittest.main()
