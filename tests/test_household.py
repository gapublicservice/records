import io
import unittest

from harvester import extract, household as h

# The layout of Georgia Power's monthly bad debt report (Docket 42516), as
# pdftotext -layout prints it. The figures are made up.
REPORT = """
                                         PUBLIC DISCLOSURE
                                     PSC Monthly Bad Debt Report
                                   2022        2022        2022
ALL CUSTOMER CLASSES               JULY        AUGUST      SEPTEMBER
Number of customers               2,700,001   2,700,002   2,700,003
Dollar amount billed              $ 500,000   $ 600,000   REDACTED
Total number of accounts past due    400,000     410,000     420,000
30 - 60 days past due                300,000     310,000     320,000
120+ days past due                     5,000       6,000       7,000
30 - 60 days past due             $ 1,000,000 $ 1,100,000 $ 1,200,000
120+ days past due                $    90,000 $    95,000 $    99,000
Number of disconnection notices issued 401,000   402,000     403,000
Number of disconnections for nonpayment 20,001    20,002      20,003
Number of service reconnections after disconnection for  15,001  15,002  15,003
nonpayment
Number of customers charged a late payment fee   -    -   1,234
                                                                 Page 1 of 2
                                   2022        2022        2022
RESIDENTIAL CLASS ONLY  Definition  JULY        AUGUST      SEPTEMBER
Number of customers  Number of Residential Customers  2,300,001  2,300,002  2,300,003
Number of disconnections for nonpayment  Number of Residential accounts disconnected for nonpayment  18,001  18,002  18,003
Number of disconnection notices issued  Number of Residential disconnect messages issued on bill  390,001  390,002
Bad Debt Budget  15% Risk Factor
Jun-22  $ 1,736,047  $ 260,407  $ 1,996,454  $ 31,896  $ (1,964,559)
"""


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.r = h.parse_bad_debt(REPORT, (2022, 9))

    def test_months_and_rows(self):
        a = self.r["sections"]["all"]
        self.assertEqual(sorted(a), ["2022-07", "2022-08", "2022-09"])
        self.assertEqual(a["2022-09"]["disconnections"], 20003)
        self.assertEqual(a["2022-07"]["notices"], 401000)
        self.assertEqual(a["2022-08"]["customers"], 2700002)

    def test_wrapped_label(self):
        self.assertEqual(self.r["sections"]["all"]["2022-08"]["reconnections"], 15002)

    def test_counts_and_dollars_kept_apart(self):
        a = self.r["sections"]["all"]["2022-07"]
        self.assertEqual(a["past_due_30_60"], 300000)
        self.assertEqual(a["past_due_30_60_usd"], 1000000)
        self.assertEqual(a["past_due_120_plus_usd"], 90000)

    def test_dash_is_zero_and_redacted_is_none(self):
        a = self.r["sections"]["all"]
        self.assertEqual(a["2022-07"]["late_fees"], 0)
        self.assertIsNone(a["2022-09"]["billed_usd"])

    def test_residential_with_definition_column(self):
        r = self.r["sections"]["residential"]
        self.assertEqual(r["2022-09"]["disconnections"], 18003)

    def test_short_row_is_left_out_not_guessed(self):
        r = self.r["sections"]["residential"]
        self.assertNotIn("notices", r["2022-07"])
        self.assertTrue(any("disconnection notices" in p for p in self.r["problems"]))

    def test_budget_table_is_not_read_as_rows(self):
        self.assertNotIn("2022-06", self.r["sections"]["residential"])

    def test_years_counted_back_only_when_last_column_is_the_report_month(self):
        text = "\n".join(l for l in REPORT.split("\n") if not h._years_in(l.strip()))
        self.assertEqual(sorted(h.parse_bad_debt(text, (2022, 9))["sections"]["all"]),
                         ["2022-07", "2022-08", "2022-09"])
        r = h.parse_bad_debt(text, (2022, 10))
        self.assertEqual(r["sections"].get("all", {}), {})
        self.assertTrue(r["problems"])

    def test_month_across_new_year(self):
        self.assertEqual(h._backward([11, 12, 1, 2], (2021, 2)), [(2020, 11), (2020, 12), (2021, 1), (2021, 2)])

    def test_report_month_from_file_name(self):
        self.assertEqual(h.report_month("dkt_42516_incr__bad_debt_sep_2022_pd.zip"), (2022, 9))
        self.assertEqual(h.report_month("x.zip", "Incremental Bad Debt Report for June"), None)
        self.assertEqual(h.report_month("Cover.docx", "Incremental Bad Debt Oct 2025 PD"), (2025, 10))


class SpreadsheetTest(unittest.TestCase):
    def test_xlsx_copy_parses_like_the_pdf(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed")
        import datetime as dt
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["ALL CUSTOMER CLASSES", dt.date(2022, 8, 1), dt.date(2022, 9, 1)])
        ws.append(["Number of disconnections for nonpayment", 20002, 20003])
        ws.append(["30 - 60 days past due", 310000, 320000])
        ws.append(["30 - 60 days past due", 1100000.0, 1200000.0])
        buf = io.BytesIO()
        wb.save(buf)
        text, how = extract.text_for("report.xlsx", buf.getvalue())
        self.assertEqual(how, "xlsx")
        a = h.parse_bad_debt(text, (2022, 9))["sections"]["all"]
        self.assertEqual(a["2022-09"]["disconnections"], 20003)
        self.assertEqual(a["2022-08"]["past_due_30_60_usd"], 1100000)


SURVEY = """<form id="filterForm" method="get" action="/utilities/electric/residential-rate-survey/">
<select name="s"><option value="w26">Winter 2026</option><option value="s26" selected>Summer 2026</option></select>
<input type="hidden" name="c" value="1000"></form>
<table><tr><th>Provider</th><th>Charges</th><th>Cents/kWh</th></tr>
<tr><td>Georgia Power</td><td>$182.93</td><td>$0.1829</td></tr>
<tr><td>Some EMC</td><td>$140.00</td><td>$0.1400</td></tr>
<tr><td>Average</td><td>$148.14</td><td>$0.1481</td></tr></table>"""


class PagesTest(unittest.TestCase):
    def test_survey(self):
        s = h.parse_survey(SURVEY)
        self.assertEqual(s["survey"], "Summer 2026")
        self.assertEqual(s["georgia_power"], 182.93)
        self.assertEqual(s["average"], 148.14)
        form, opts = h.survey_options(SURVEY)
        self.assertEqual(form["select"], "s")
        self.assertEqual([o["text"] for o in opts], ["Winter 2026", "Summer 2026"])

    def test_gas_links_use_the_link_text_not_the_address(self):
        page = ('<a href="/utilities/natural-gas/marketers-pricing-index/september-2027/">September 2026</a>'
                '<a href="/x/">Contact us</a>')
        self.assertEqual(h.gas_month_links(page),
                         [("2026-09", "https://psc.ga.gov/utilities/natural-gas/marketers-pricing-index/september-2027/")])

    def test_gas_table(self):
        text = ("Marketer   Total Monthly Bill   Price per Therm\n"
                "Alpha Gas   $ 70.10   $0.90\nBeta Energy   $ 95.25   $1.20\n"
                "* Based on 23 therms. The AGL base charge for a typical customer is $39.71.\n")
        g = h.parse_gas_pdf_text(text)
        self.assertEqual(g["agl_base_charge"], 39.71)
        self.assertEqual(g["therms"], 23)
        self.assertEqual(g["lowest"], {"marketer": "Alpha Gas", "bill": 70.10})
        self.assertEqual(g["highest"]["bill"], 95.25)

    def test_page_builds_with_no_data_and_marks_gaps(self):
        from harvester import site
        b = h.body(site)
        self.assertIn("Bills and disconnections", b)
        self.assertIn("[to confirm]", b)
        self.assertIn("Docket 42516", b)


class BillChangesTest(unittest.TestCase):
    def test_each_quote_is_in_the_order_it_cites(self):
        import re
        from harvester.run import ROOT, text_path
        for c in h.load_bill_changes():
            for src in c["sources"]:
                p = text_path(src["document_id"], src["attachment_id"])
                if not p.exists():
                    continue
                text = re.sub(r"\s+", " ", p.read_text())
                for key in ("quote", "effective_quote"):
                    if src.get(key):
                        self.assertIn(src[key], text, f'{src["document_id"]}: {key}')


if __name__ == "__main__":
    unittest.main()
