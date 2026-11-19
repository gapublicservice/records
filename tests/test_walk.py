import json
import os
import tempfile
import unittest
from unittest import mock


class Walk(unittest.TestCase):
    def test_nightly_walk(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["RECORDS_ROOT"] = d
            import importlib
            from harvester import run, psc
            importlib.reload(run)
            present = {100, 101, 103, 106}  # 102, 104, 105 skipped

            def fake(self, doc_id):
                if doc_id in present:
                    return psc.Filing(document_id=doc_id, url="u", filed_date="2026-11-19",
                                      description="d", dockets=[57171]), ""
                return None, ""

            with mock.patch.object(psc.Fetcher, "filing", fake):
                run.main(["--pause", "0", "nightly", "--seed", "100"])
                state = json.loads(run.STATE.read_text())
                self.assertEqual(state["highest_found"], 106)
                self.assertEqual(sorted(state["empty"]), ["102", "104", "105"])
                present.add(104)  # filled in late
                run.main(["--pause", "0", "nightly"])
                state = json.loads(run.STATE.read_text())
                self.assertEqual(sorted(state["empty"]), ["102", "105"])
                self.assertTrue(run.filing_path(104).exists())
            del os.environ["RECORDS_ROOT"]
