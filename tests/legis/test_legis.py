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

    def test_senate_shared_committee_needs_a_utility_topic(self):
        lic = dict(synthetic_bill(), caption="A BILL to amend Chapter 24 of Title 43, relating to massage therapists",
                   summary="", committees=[{"name": "Regulated Industries and Utilities", "chamber": "Senate"}])
        self.assertEqual(scope.reasons(lic), [])
        gas = dict(lic, caption="A BILL to authorize contracts for the sale of electric power by local governments")
        self.assertEqual(scope.reasons(gas), ["utility_committee"])
        house = dict(lic, committees=[{"name": "Energy, Utilities & Telecommunications", "chamber": "House"}])
        self.assertEqual(scope.reasons(house), ["utility_committee"])

    def test_moved_numbers_are_not_figure_changes(self):
        s = {"words_added": 1, "words_removed": 1, "unchanged": False, "sections_added": [], "sections_dropped": [],
             "numbers_changed": [{"from": ["34"], "to": []}, {"from": [], "to": ["1", "2", "3", "4"]},
                                 {"from": ["1", "2", "3"], "to": ["5", "6", "7"]}, {"from": ["90"], "to": ["60"]}],
             "code_sections_newly_touched": [], "code_sections_no_longer_touched": []}
        lines = textdiff.summary_lines(s)
        self.assertIn("A figure changed from 90 to 60.", lines)
        self.assertFalse(any("none" in l or "1 2 3" in l for l in lines))



REAL = Path(__file__).resolve().parents[2] / "data" / "legislature"


def _sb34():
    """Copy the real SB 34 record, panel and saved sources into the test folder."""
    import shutil
    for rel in ["2025_26/bills/sb34.json", "views/2025_26/sb34.json",
                "sources/sb34-georgia-recorder-2025.txt", "sources/sb34-rstreet-2026.txt"]:
        dst = TMP / "data" / "legislature" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REAL / rel, dst)
    return json.loads((REAL / "2025_26/bills/sb34.json").read_text())


def test_bill_pages_name_their_real_source():
    out = site.bill_page(_sb34())
    assert site.BILL_SOURCE in out
    assert site.COMMISSION_SOURCE not in out


def test_sb34_panel_is_live_with_disclosure_and_context():
    bill = _sb34()
    st = views.panel_status(views.load_panel("2025_26", "sb34"))
    assert st["state"] == "live", (st["reasons"], st.get("problems"))
    out = site.views_widget(bill)
    assert "lt-disclosure" in out and "priority bills" in out
    assert out.count("lt-context") == len(st["views"]) == 4


def test_no_position_line_dropped_where_disclosed():
    out = site.bill_page(_sb34())
    assert "lt-disclosure" in out
    assert site.NEUTRAL not in out


def test_word_trims_paul_approved_nov_24():
    out = site.bill_page(_sb34())
    assert "Sponsor: Chuck Hufstetler (52nd) and 20 co-sponsors" in out
    assert "<summary>Show all sponsors</summary>" in out
    assert "Why it&#x27;s tracked: Title 46 (utilities) · names the PSC · utilities committee" in out \
        or "Why it's tracked: Title 46 (utilities) · names the PSC · utilities committee" in out
    assert "Quoted from public sources and checked against them. Both sides are shown when both have one." in out
    assert "Georgia Recorder (via Rough Draft Atlanta)</a> · Feb. 10, 2025" in out
    assert "R Street Institute</a> · Jan. 27, 2026" in out
    assert 'title="R Street Testimony in Support of GA SB 34"' in out
    assert "<summary>Show the summary</summary>" in out
    assert "Full record on the General Assembly&#x27;s site</a>" in out or "Full record on the General Assembly's site</a>" in out
    # Not approved: the context lines keep their full wording.
    assert "Testimony at the Senate Regulated Industries and Utilities Committee hearing on SB 34, Feb. 6, 2025" in out


def test_member_and_date_fallbacks():
    assert site._member("Odd Name") == "Odd Name"
    assert site._ap_date("2026-09-05") == "Sept. 5, 2026"
    assert site._ap_date("soon") == "soon"


def test_single_view_needs_record_kind_and_sign_off():
    bill = _sb34()
    panel = views.load_panel("2025_26", "sb34")
    one = dict(panel, views=[v for v in panel["views"] if v["side"] == "for"])
    assert views.panel_status(one)["state"] == "held"  # no sign-off
    ok = dict(one, single_view_approved_by="Paul Glaze", single_view_approved_at="2026-11-24")
    views.EMPTY_SIDE_LINE_APPROVED = False
    assert views.panel_status(ok)["state"] == "held"  # held if the line is ever withdrawn
    views.EMPTY_SIDE_LINE_APPROVED = True
    st = views.panel_status(ok)
    assert st["state"] == "live" and st["single"]
    path = views.panel_path("2025_26", "sb34")
    path.write_text(json.dumps(ok))
    out = site.views_widget(bill)
    assert "No view against this bill or raising concerns that meets our standards has been found yet." in out
    assert out.count('class="lt-view"') == 2  # think tank counts too (any approved kind)
    path.write_text(json.dumps(panel))
