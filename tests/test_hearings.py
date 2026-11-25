import unittest

from harvester import hearings as H


def f(doc, date, company, desc, state="available"):
    return {"document_id": doc, "filed_date": date, "company": company, "description": desc,
            "dockets": [1], "files": {"state": state, "public": [1], "confidential": 0}}


EV = {"date": "2026-12-09", "time": "10:00 AM", "kind": "docket", "dockets": [1],
      "title": "Docket # 1 Petition",
      "url": "https://psc.ga.gov/agendas-calendars/commission-calendar/docket-1-petition/?date=1"}


class KindTest(unittest.TestCase):
    def test_kinds(self):
        cases = {
            "Rebuttal Testimony and Exhibits of Robert L. Trokey": "Rebuttal testimony",
            "Direct Testimony of Sara Vinson": "Testimony",
            "Notice of Hearing and Scheduling Order": "Scheduling order or notice of hearing",
            "Petitioners' Response to VoltaGrid's Emergency Appeal and Motion to Stay": "Response",
            "Responses to Staff's Data Request STF-PIA-1": "Answers to data requests",
            "DKT 57171 STF-PIA-1 Data Request Responses": "Answers to data requests",
            "Stipulation Between Georgia Power Company and Public Interest Advocacy Staff": "Stipulation",
            "Petitioners' Proposed Stipulations and Witness List": "Witness, exhibit or proposed stipulation list",
            "Return of Service - Subpoena": "Return of service",
            "Application of City of Cartersville for Full Commission Review of the Hearing Officer's Initial Decision":
                "Appeal or request for full Commission review",
            "Initial Decision of the Hearing Officer": "Hearing Officer's initial decision",
        }
        for desc, want in cases.items():
            self.assertEqual(H.kind_of(f(1, "2026-01-01", "Party", desc)), want, desc)

    def test_orders(self):
        self.assertEqual(H.kind_of(f(1, "2026-01-01", "GPSC", "Chairman's Order Temporarily Staying Hearing Officer's Order")), "Order")
        self.assertEqual(H.kind_of(f(1, "2026-01-01", "Staff", "ORDER ON RESPONDENT'S MOTION TO STAY PROCEEDINGS")), "Order")
        self.assertNotEqual(H.kind_of(f(1, "2026-01-01", "Party", "Motion for Expedited Ruling and Proposed Order")), "Order")

    def test_party(self):
        self.assertFalse(H.is_party(f(1, "2026-01-01", "GPSC", "Assignment to Hearing Officer Order")))
        self.assertFalse(H.is_party(f(1, "2026-01-01", "Staff", "Amended Scheduling Order and Notice of Hearing")))
        self.assertTrue(H.is_party(f(1, "2026-01-01", "Staff", "Staff's Response to Respondent's Motion to Dismiss")))
        self.assertTrue(H.is_party(f(1, "2026-01-01", "VoltaGrid, LLC", "Motion to Dismiss")))


class StageTest(unittest.TestCase):
    fs = [f(10, "2026-07-13", "Petitioners", "Petition For Expedited Declaratory Judgment"),
          f(11, "2026-08-24", "Staff", "Notice of Hearing and Scheduling Order"),
          f(12, "2026-10-09", "Petitioners", "Direct Testimony of A"),
          f(13, "2026-11-13", "Staff", "Rebuttal Testimony of B"),
          f(14, "2026-11-12", "GPSC", "Chairman's Order Temporarily Staying Hearing Officer's Order")]

    def test_stage_as_of(self):
        self.assertEqual(H.stage(self.fs, EV, "2026-07-01")["stage"], None)
        self.assertEqual(H.stage(self.fs, EV, "2026-09-01")["stage"]["key"], "scheduled")
        s = H.stage(self.fs, EV, "2026-11-25")
        self.assertEqual(s["stage"]["key"], "rebuttal")
        self.assertIn("filing 13", s["line"])
        self.assertIn("filing 14", s["line"])
        self.assertIn("lists the hearing for Dec 9, 2026", s["line"])

    def test_post_hearing_stage_needs_later_filing(self):
        fs = self.fs + [f(15, "2026-11-20", "Party", "Post-Hearing Brief")]
        self.assertEqual(H.stage(fs, EV, "2026-11-25")["stage"]["key"], "rebuttal")
        fs = self.fs + [f(16, "2026-12-20", "Party", "Post-Hearing Brief")]
        self.assertEqual(H.stage(fs, EV, "2026-12-21")["stage"]["key"], "briefs")
        self.assertIn("listed the hearing", H.stage(fs, EV, "2026-12-21")["line"])

    def test_week_keeps_changes_only(self):
        hist = H.week_of_lines(self.fs, EV, "2026-11-16")
        self.assertEqual(len(hist), 3)  # the start, the Nov 12 order, the Nov 13 rebuttal


class QuoteTest(unittest.TestCase):
    def test_clean(self):
        self.assertTrue(H._clean_ok("The final hearing will remain scheduled for December 9, 2026."))
        self.assertFalse(H._clean_ok("Please write to jdoe@example.com before the hearing on December 9, 2026."))
        self.assertFalse(H._clean_ok("Call (404) 656-4501 about the hearing on December 9, 2026, at the Commission."))
        self.assertFalse(H._clean_ok("Comm’n Aug. 12, 2026). 24 PSO ¶ 4. 6 stipulations and hearing on December 9."))
        self.assertFalse(H._clean_ok("Moreover, it noted that “moving revenue will have differential impacts on customers.”16 Mr."))
        self.assertFalse(H._clean_ok("The hearing on the pre-filed testimony of the Company was held before Hearing Officer J."))
        self.assertFalse(H._clean_ok("At the hearing, Georgia Power witness Robinson explained that the project was not 27 identified by June."))
        self.assertTrue(H._clean_ok("Sierra Club filed a Motion for Continuance of Hearing, seeking to continue the hearing for 30 days."))
        self.assertTrue(H._clean_ok("The hearing on intervenor testimony is scheduled to begin October 15, 2026, at 9:30 a.m."))
        self.assertFalse(H._clean_ok("[BEGIN TRADE SECRET] 1234 [END TRADE SECRET] the hearing will address these figures."))

    def test_sentences_keep_names(self):
        got = H._sentences("At the hearing, Mr. Mallard indicated it was open. Direct Testimony of John D. Smith was filed.")
        self.assertEqual(got, ["At the hearing, Mr. Mallard indicated it was open.",
                               "Direct Testimony of John D. Smith was filed."])

    def test_strip_lead(self):
        self.assertEqual(H._strip_lead("PETITIONERS’ REQUEST FOR ISSUANCE OF SUBPOENAS Pursuant to law, it asks."),
                         "Pursuant to law, it asks.")
        self.assertEqual(H._strip_lead("Tanner: Pursuant to the order, a list."), "Pursuant to the order, a list.")

    def test_no_text_from_confidential(self):
        self.assertEqual(H.texts(f(1, "2026-01-01", "P", "Motion", state="confidential")), [])


class SlugTest(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(H.slug(EV), "docket-1-petition-2026-12-09")
        ev = dict(EV, date="2026-09-01",
                  url="https://psc.ga.gov/agendas-calendars/commission-calendar/docket-no-57171-rtp-hearing-9-1-2026/?date=1")
        self.assertEqual(H.slug(ev), "docket-no-57171-rtp-hearing-9-1-2026")
        self.assertFalse(H.is_hearing(dict(EV, dockets=[])))
        self.assertFalse(H.is_hearing(dict(EV, kind="session")))


if __name__ == "__main__":
    unittest.main()
