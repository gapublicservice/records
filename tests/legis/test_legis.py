import json
import unittest
from pathlib import Path

from . import TMP  # noqa: F401  (sets RECORDS_ROOT first)
from legis import scope, service, site, store, textdiff, video, views

FIX = Path(__file__).parent / "fixtures"


def synthetic_bill():
    raw = json.loads((FIX / "detail_synthetic.json").read_text())
    vote = json.loads((FIX / "vote_synthetic.json").read_text())
    return service.normalize(raw, "2025_26", [vote])


OLD = """26 LC 44 2999
1 A BILL TO BE ENTITLED
2 AN ACT
3 To amend Chapter 2 of Title 46 of the Official Code of Georgia Annotated, relating
4 to the Public Service Commission.
5 SECTION 1.
6 Code Section 46-2-23 is amended by adding a report due within 90 days.
H. B. 999
- 1 -
"""
NEW = """26 LC 44 3000S
1 A BILL TO BE ENTITLED
2 AN ACT
3 To amend Chapter 2 of Title 46 of the Official Code of Georgia Annotated, relating
4 to the Public Service Commission.
5 SECTION 1.
6 Code Section 46-2-23 is amended by adding a report due within 60 days.
7 SECTION 2.
8 Code Section 46-3-1 is amended by adding large load customers.
H. B. 999 (SUB)
- 1 -
"""


class Normalize(unittest.TestCase):
    def test_fields(self):
        b = synthetic_bill()
        self.assertEqual(b["key"], "HB 999")
        self.assertEqual(b["slug"], "hb999")
        self.assertEqual(b["page"], "https://www.legis.ga.gov/legislation/69999")
        self.assertEqual([s["role"] for s in b["sponsors"]], ["author", "sponsor"])
        self.assertEqual(b["status_history"][0]["code"], "HPF")  # sorted by date
        self.assertEqual(b["versions"][1]["url"],
                         "https://www.legis.ga.gov/api/legislation/document/20252026/231500")
        v = b["votes"][0]
        self.assertEqual((v["yea"], v["nay"]), (150, 20))
        self.assertEqual(len(v["members"]), 1)  # vacant seat dropped

    def test_items_unwraps(self):
        self.assertEqual(service._items(None), [])
        self.assertEqual(service._items({"X": [1, 2]}), [1, 2])
        self.assertEqual(service._items([3]), [3])


class Scope(unittest.TestCase):
    def test_title46_and_psc_and_committee(self):
        self.assertEqual(scope.reasons(synthetic_bill()), ["title46", "psc", "utility_committee"])

    def test_statewide_election_law(self):
        b = {"caption": "A BILL to amend Chapter 2 of Title 21 of the Official Code of Georgia Annotated, "
                        "relating to elections and primaries generally", "document_type": "SB",
             "legislation_type": "GEN", "committees": []}
        self.assertEqual(scope.reasons(b), ["election_law"])

    def test_local_election_act_skipped(self):
        b = {"caption": "A BILL to create a board of elections and registration for Baldwin County; "
                        "to amend an Act (Ga. L. 1990, p. 3500)", "document_type": "HB",
             "legislation_type": "LOC", "committees": []}
        self.assertEqual(scope.reasons(b), [])

    def test_honorary_resolution_skipped(self):
        b = {"caption": "A RESOLUTION commending the Georgia Public Service Commission staff",
             "document_type": "HR", "committees": []}
        self.assertEqual(scope.reasons(b), [])


class TextDiff(unittest.TestCase):
    def test_clean_strips_margins(self):
        c = textdiff.clean(NEW)
        self.assertNotIn("LC 44", c)
        self.assertNotIn("- 1 -", c)
        self.assertTrue(c.startswith("A BILL TO BE ENTITLED"))
        self.assertIn("SECTION 2.", c)

    def test_compare_summary(self):
        s = textdiff.compare(textdiff.clean(OLD), textdiff.clean(NEW))["summary"]
        self.assertEqual(s["sections_added"], ["2"])
        self.assertEqual(s["numbers_changed"][0], {"from": ["90"], "to": ["60"]})
        self.assertEqual(s["code_sections_newly_touched"], ["46-3-1"])
        lines = textdiff.summary_lines(s)
        self.assertIn("A figure changed from 90 to 60.", lines)

    def test_html_marks(self):
        c = textdiff.compare("a b c", "a x c")
        h = textdiff.to_html(c["ops"])
        self.assertIn("<del>b</del>", h)
        self.assertIn("<ins>x</ins>", h)


def view(**kw):
    v = {"id": "v1", "side": "for", "who": "A. Expert", "role": "Professor, State University",
         "kind": "academic", "quote": "The reporting requirement gives regulators better information.",
         "source_url": "https://example.edu/report", "source_title": "A report", "source_date": "2025-02-01",
         "verified_by": "Reviewer", "verified_at": "2025-02-02", "source_copy": "src1"}
    v.update(kw)
    return v


class ExpertViews(unittest.TestCase):
    def setUp(self):
        views.SOURCES.mkdir(parents=True, exist_ok=True)
        (views.SOURCES / "src1.txt").write_text(
            "Intro. The reporting requirement gives regulators better information. More.")
        (views.SOURCES / "src2.txt").write_text(
            "Testimony. We are concerned the reports will raise costs for customers without benefit.")
        self.roster = json.loads((views.VIEWS / "roster.json").read_text())
        self.roster["approved_by"] = "Reviewer"

    def panel(self, vs, approved=True):
        return {"bill": "HB 999", "views": vs, "approved_by": "Reviewer" if approved else None,
                "approved_at": "2025-02-03" if approved else None}

    def against(self, **kw):
        base = dict(id="v2", side="against_or_concerns", who="B. Advocate", role="Director, Industry Group",
                    kind="utility_industry", source_copy="src2", source_date="2025-02-05",
                    quote="We are concerned the reports will raise costs for customers without benefit.")
        base.update(kw)
        return view(**base)

    def test_both_sides_verified_goes_live(self):
        st = views.panel_status(self.panel([self.against(), view()]), self.roster)
        self.assertEqual(st["state"], "live", st)
        self.assertEqual([v["id"] for v in st["views"]], ["v1", "v2"])  # by date

    def test_one_side_holds_with_public_note(self):
        st = views.panel_status(self.panel([view()]), self.roster)
        self.assertEqual(st["state"], "held")
        self.assertEqual(st["views"], [])
        self.assertIn("one side only", st["note"])

    def test_misquote_fails(self):
        st = views.panel_status(self.panel([view(quote="Regulators need this badly."), self.against()]), self.roster)
        self.assertEqual(st["state"], "held")
        self.assertTrue(any("not found" in p for p in st["problems"]["v1"]))

    def test_unapproved_roster_or_panel_holds(self):
        r = dict(self.roster, approved_by=None)
        self.assertEqual(views.panel_status(self.panel([view(), self.against()]), r)["state"], "held")
        self.assertEqual(views.panel_status(self.panel([view(), self.against()], approved=False),
                                            self.roster)["state"], "held")

    def test_gcv_never_a_source_and_no_call_to_action(self):
        p = views.check_view(view(who="Georgia Conservation Voters"), self.roster)
        self.assertTrue(any("never sources" in x for x in p))
        p = views.check_view(view(quote="Call your legislator today."), self.roster)
        self.assertTrue(any("call to action" in x for x in p))

    def test_video_view_needs_saved_video_and_transcript(self):
        vv = self.against(source_copy=None, video={"id": "h1", "start_seconds": None})
        p = views.check_view(vv, self.roster)
        self.assertIn("video not transcribed yet", p)
        d = views.VIDEO / "h1"
        d.mkdir(parents=True, exist_ok=True)
        store.write_json(d / "transcript.json", {"segments": [
            {"start": 10.0, "end": 14.0, "text": "Good morning."},
            {"start": 3600.5, "end": 3610.0, "text": "we are concerned the reports will raise"},
            {"start": 3610.0, "end": 3615.0, "text": "costs for customers without benefit"}]})
        store.write_json(d / "meta.json", {"webpage_url": "https://vimeo.com/123", "archive_url": None})
        vv["video"]["archive_url"] = "https://github.com/x/y/releases/download/v/h1.mp4"
        vv["video"]["start_seconds"] = 3600
        self.assertEqual(views.check_view(vv, self.roster), [])
        f = video.find("h1", vv["quote"])
        self.assertTrue(f["found"])
        self.assertEqual(f["start_seconds"], 3600)
        self.assertEqual(video.moment_link({"webpage_url": "https://vimeo.com/123"}, 3600),
                         "https://vimeo.com/123#t=3600s")
        self.assertEqual(video.moment_link({"webpage_url": "https://www.youtube.com/watch?v=abc"}, 5),
                         "https://www.youtube.com/watch?v=abc&t=5s")


class Store(unittest.TestCase):
    def test_change_log(self):
        b = synthetic_bill()
        b.update(key="HB 998", slug="hb998")
        b["scope"] = scope.reasons(b)
        self.assertEqual(store.save_bill(dict(b)), ["new"])
        self.assertEqual(store.save_bill(dict(b)), [])
        b2 = dict(b, status_history=b["status_history"] + [
            {"date": "2025-03-04T00:00:00", "code": "SFR", "action": "Senate Read and Referred", "id": 14}])
        self.assertEqual(store.save_bill(b2), ["status_history"])
        log = [l for l in (store.sess_dir("2025_26") / "changes.jsonl").read_text().splitlines()
               if '"HB 998"' in l]
        self.assertEqual(len(log), 2)


class Site(unittest.TestCase):
    def test_build_pages_neutral(self):
        b = synthetic_bill()
        b["scope"] = scope.reasons(b)
        store.save_bill(b)
        b = store.load_bill("2025_26", "hb999")
        for v, t in zip(b["versions"], (OLD, NEW)):
            p = store.version_path("2025_26", "hb999", v["doc_id"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(textdiff.clean(t))
        from legis import run
        run.capture_text(b)
        site.build("2025_26")
        page = (site.OUT / "2025_26" / "hb999" / "index.html").read_text()
        self.assertIn("A figure changed from 90 to 60.", page)
        self.assertIn("Passed first chamber", page)
        self.assertIn("takes no position", page)
        for banned in ("contact your", "call your", "urge", "petition"):
            self.assertNotIn(banned, page.lower())
        self.assertTrue((site.OUT / "embed" / "2025_26" / "hb999" / "votes.html").exists())
        self.assertEqual(site.stage_of(b), 3)


if __name__ == "__main__":
    unittest.main()
