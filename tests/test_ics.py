import datetime as dt
import unittest

from harvester import ics


EV = {"date": "2026-12-01", "time": "9:30 AM", "kind": "session", "dockets": [],
      "title": "Administrative Session 12-1-2026",
      "url": "https://psc.ga.gov/agendas-calendars/commission-calendar/administrative-session-12-1-2026/?date=1796135400"}


class IcsTests(unittest.TestCase):
    def test_time(self):
        self.assertEqual(ics.parse_time("9:30 AM"), (9, 30))
        self.assertEqual(ics.parse_time("12:00 PM"), (12, 0))
        self.assertEqual(ics.parse_time("2 p.m."), (14, 0))
        self.assertIsNone(ics.parse_time("TBD"))

    def test_event(self):
        agendas = {EV["url"]: {"files": [{"label": "Administrative session", "url": "https://psc.ga.gov/site/assets/files/1/a.doc"}],
                               "dockets": [44280]}}
        cal = ics.calendar([EV], agendas, "Georgia PSC meetings", {"44280"}, now=dt.datetime(2026, 11, 20, tzinfo=dt.timezone.utc))
        self.assertIn("DTSTART;TZID=America/New_York:20261201T093000", cal)
        self.assertIn("DTEND;TZID=America/New_York:20261201T113000", cal)
        self.assertIn("SUMMARY:PSC Administrative session", cal)
        self.assertIn("BEGIN:VTIMEZONE", cal)
        unfolded = cal.replace("\r\n ", "")
        self.assertIn("records.gapublicservice.org/docket/44280/", unfolded)
        self.assertTrue(all(len(l.encode()) <= 75 for l in cal.split("\r\n")))
        self.assertEqual(ics.uid_for(EV), ics.uid_for(dict(EV)))

    def test_all_day_and_other(self):
        ev = {"date": "2026-12-03", "title": "Town hall, Macon", "other": True, "kind": "other", "dockets": []}
        cal = ics.calendar([ev], {}, "x")
        self.assertIn("DTSTART;VALUE=DATE:20261203", cal)
        self.assertIn("Not a Commission event", cal)

    def test_escape(self):
        self.assertEqual(ics._esc("a, b; c\nd"), "a\\, b\; c\\nd")


if __name__ == "__main__":
    unittest.main()
