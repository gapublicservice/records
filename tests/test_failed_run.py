import datetime as dt
import json
import os
import tempfile
import unittest
from unittest import mock


class FailedNight(unittest.TestCase):
    def test_stopped_walk_keeps_what_it_stored(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["RECORDS_ROOT"] = d
            try:
                import importlib
                from harvester import run, psc
                importlib.reload(run)
                run.save_json(run.STATE, {"highest_found": 100, "empty": {}, "backfill_empty": [],
                                          "last_nightly": "2026-11-23",
                                          "last_nightly_at": "2026-11-23T08:20+00:00"})

                def fake(self, doc_id):
                    if doc_id in (100, 101):
                        return psc.Filing(document_id=doc_id, url="u", filed_date="2026-11-24",
                                          description="d", dockets=[57171]), ""
                    raise ConnectionResetError("site went away")

                with mock.patch.object(psc.Fetcher, "filing", fake):
                    code = run.main(["--pause", "0", "nightly"])
                self.assertEqual(code, 1)
                state = json.loads(run.STATE.read_text())
                # The two filings stored before the failure are kept and counted.
                self.assertTrue(run.filing_path(100).exists())
                self.assertTrue(run.filing_path(101).exists())
                self.assertEqual(state["highest_found"], 101)
                # The last finished copy keeps its time; the failure is recorded.
                self.assertEqual(state["last_nightly_at"], "2026-11-23T08:20+00:00")
                self.assertEqual(state["last_nightly_error"]["error"], "ConnectionResetError")
                self.assertEqual(state["last_nightly_error"]["stored"], 2)
                # No half-written files are left behind.
                self.assertEqual(list(run.DATA.rglob("*.tmp")), [])

                # The next night finishes and clears the error.
                with mock.patch.object(psc.Fetcher, "filing", lambda self, i: (None, "")):
                    self.assertEqual(run.main(["--pause", "0", "nightly"]), 0)
                state = json.loads(run.STATE.read_text())
                self.assertNotIn("last_nightly_error", state)
                self.assertGreater(state["last_nightly_at"], "2026-11-23T08:20+00:00")
            finally:
                del os.environ["RECORDS_ROOT"]


class CopyStatus(unittest.TestCase):
    def setUp(self):
        from harvester import site
        self.site = site
        self.now = dt.datetime(2026, 11, 25, 15, 0, tzinfo=dt.timezone.utc)

    def test_fresh(self):
        at, warn = self.site.copy_status({"last_nightly_at": "2026-11-25T08:30+00:00"}, self.now)
        self.assertEqual(at, "2026-11-25T08:30+00:00")
        self.assertEqual(warn, "")

    def test_stopped_partway(self):
        at, warn = self.site.copy_status({
            "last_nightly_at": "2026-11-24T08:30+00:00",
            "last_nightly_error": {"at": "2026-11-25T08:40+00:00", "error": "URLError"}}, self.now)
        self.assertEqual(at, "2026-11-24T08:30+00:00")
        self.assertIn("stopped partway", warn)

    def test_old_error_is_ignored(self):
        at, warn = self.site.copy_status({
            "last_nightly_at": "2026-11-25T08:30+00:00",
            "last_nightly_error": {"at": "2026-11-24T08:40+00:00", "error": "URLError"}}, self.now)
        self.assertEqual(warn, "")

    def test_nothing_finished_for_a_day_and_a_half(self):
        at, warn = self.site.copy_status({"last_nightly_at": "2026-11-23T08:30+00:00"}, self.now)
        self.assertIn("No nightly copy has finished", warn)

    def test_date_only_from_before(self):
        at, warn = self.site.copy_status({"last_nightly": "2026-11-25"}, self.now)
        self.assertEqual((at, warn), ("2026-11-25", ""))


class MergeKeepsErrors(unittest.TestCase):
    def test_finished_run_clears_error(self):
        from harvester import merge_state
        theirs = {"highest_found": 5, "last_nightly_error": {"at": "x"}}
        ours = {"highest_found": 6, "last_nightly_at": "y", "empty": {}, "gaps": []}
        out = merge_state.merge(theirs, ours, "nightly", exists=lambda i: True)
        self.assertNotIn("last_nightly_error", out)
        self.assertEqual(out["last_nightly_at"], "y")


if __name__ == "__main__":
    unittest.main()


class AgendasKeepLastCopy(unittest.TestCase):
    def test_site_down_keeps_copy_and_time(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["RECORDS_ROOT"] = d
            try:
                import importlib
                from harvester import run, agendas
                importlib.reload(run)
                importlib.reload(agendas)
                from pathlib import Path
                # agendas reads the calendar path from harvester.calendar; point it here.
                mock.patch.object(agendas, "CALENDAR", Path(d) / "data" / "index" / "calendar.json").start()
                self.addCleanup(mock.patch.stopall)
                self.assertTrue(str(agendas.OUT).startswith(d))
                today = dt.datetime.now(agendas.EASTERN).date().isoformat()
                run.save_json(agendas.CALENDAR, {"events": [
                    {"url": "https://psc.example/ev/", "date": today, "time": "10:00 AM",
                     "title": "Administrative Session", "kind": "session"}]})
                old = {"checked": "2026-11-23T08:00:00+00:00", "events": {"https://psc.example/ev/": {"read": "x"}}}
                run.save_json(agendas.OUT, old)

                def down(self, url, max_bytes=None):
                    raise ConnectionResetError("down")

                with mock.patch.object(agendas.Fetcher, "get", down):
                    self.assertEqual(agendas.main([]), 1)
                self.assertEqual(json.loads(agendas.OUT.read_text()), old)
            finally:
                del os.environ["RECORDS_ROOT"]
                import importlib
                from harvester import run, agendas
                importlib.reload(run)
                importlib.reload(agendas)
