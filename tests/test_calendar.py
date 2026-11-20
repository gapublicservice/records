import unittest

from harvester import calendar

PAGE = """
<td><a href="/agendas-calendars/commission-calendar/docket-no-57171-rtp-revenue-credit-and-allocation-methodology-hearing-11-12-2026/?date=1794494100">Docket No. 57171 RTP Revenue Credit and Allocation Methodology Hearing</a></td>
<li><a class="x" href="/agendas-calendars/commission-calendar/administrative-session-12-15-2026/?date=1797345000">Admin</a></li>
<a href="/agendas-calendars/commission-calendar/docket-57243-petition-for-expedited-declaratory-judgment-and-enforcement-against-voltagrid/?date=1796828400">Docket # 57243 Petition For Expedited Declaratory Judgment &amp; Enforcement</a>
<a href="/agendas-calendars/commission-calendar/administrative-session-11-17-2026/">no date</a>
"""


class CalendarTest(unittest.TestCase):
    def test_parse(self):
        ev = calendar.parse(PAGE)
        self.assertEqual(len(ev), 3)
        rtp = [e for e in ev if 57171 in e["dockets"]][0]
        self.assertEqual(rtp["date"], "2026-11-12")
        self.assertEqual(rtp["kind"], "hearing")
        self.assertIn("RTP Revenue Credit", rtp["title"])
        admin = [e for e in ev if e["kind"] == "session"][0]
        self.assertEqual((admin["date"], admin["time"]), ("2026-12-15", "9:30 AM"))
        self.assertEqual(admin["title"], "Administrative session")
        volta = [e for e in ev if 57243 in e["dockets"]][0]
        self.assertIn("&", volta["title"])

    def test_upcoming_hearings_only(self):
        ev = calendar.parse(PAGE)
        self.assertEqual([e["dockets"] for e in calendar.upcoming(ev, "2026-11-20")], [[57243]])


if __name__ == "__main__":
    unittest.main()
