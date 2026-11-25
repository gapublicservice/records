import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from harvester import meetings, site


class MeetingTitles(unittest.TestCase):
    def test_titles(self):
        self.assertEqual(meetings.meeting_of("PSC Administrative Session 11-17-2026"), ("session", "2026-11-17"))
        self.assertEqual(meetings.meeting_of("PSC Committee Hearings - 11/24/2026"), ("committee", "2026-11-24"))
        self.assertIsNone(meetings.meeting_of("PSC GUFPA Hearing 10-21-2026"))
        self.assertIsNone(meetings.meeting_of("PSC Docket No. 57171 Hearings 09-01-2026"))


class TranscriptPage(unittest.TestCase):
    def test_page_is_labeled_and_escaped(self):
        m = {"id": "2026-11-17-session", "date": "2026-11-17", "kind": "session",
             "source_page": "https://www.youtube.com/watch?v=abc", "duration": 120, "made": "2026-11-25T01:00+00:00",
             "segments": [{"start": 0, "end": 3, "text": "Good morning."},
                          {"start": 65, "end": 70, "text": "Item <one>."}]}
        html = site.transcript_page(m, None, {})
        self.assertIn("unofficial transcript", html)
        self.assertIn("not a Commission record", html)
        self.assertIn("watch?v=abc&amp;t=0s", html)
        self.assertIn("&lt;one&gt;", html)

    def test_link_only_when_transcribed(self):
        by = site.meeting_by_day([{"id": "2026-11-17-session", "date": "2026-11-17", "kind": "session"}])
        self.assertIn("transcript/2026-11-17-session/", site.transcript_link({"date": "2026-11-17", "kind": "session"}, by))
        self.assertEqual(site.transcript_link({"date": "2026-11-17", "kind": "committee"}, by), "")


def _meeting(mid, title, url="https://www.youtube.com/watch?v=Ab3_-xyz12"):
    date, kind = mid[:10], mid[11:]
    meta = {"id": mid, "date": date, "kind": kind, "source_page": url, "title": title, "duration": 60,
            "audio_file": f"{mid}.m4a", "audio_sha256": "a" * 64, "pulled": "2026-11-25T00:00:00Z",
            "made_with": "tools/transcribe_meetings.py", "extra": "dropped"}
    tr = {"id": mid, "model": "faster-whisper small.en", "language": "en", "made": "2026-11-25T00:00:00Z",
          "note": "something else", "segments": [{"start": 0, "end": 2.04, "text": " Call to order. "},
                                                   {"start": 3, "end": 4, "text": " "}]}
    return meta, tr


class TakeZip(unittest.TestCase):
    def test_take_checks_and_cleans(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            z = tmp / "t.zip"
            good = _meeting("2026-11-17-session", "PSC Administrative Session 11-17-2026")
            wrong_title = _meeting("2026-11-18-committee", "PSC Docket No. 57171 Hearings 11-18-2026")
            bad_url = _meeting("2026-11-24-committee", "PSC Committee Hearings - 11/24/2026",
                               url="https://evil.example/watch?v=abc")
            with zipfile.ZipFile(z, "w") as zf:
                for meta, tr in (good, wrong_title, bad_url):
                    zf.writestr(f"meetings/{meta['id']}/meta.json", json.dumps(meta))
                    zf.writestr(f"meetings/{meta['id']}/transcript.json", json.dumps(tr))
                zf.writestr("meetings/../../evil/meta.json", "{}")
            with mock.patch.object(meetings, "MEETINGS", tmp / "meetings"):
                self.assertEqual(meetings.take(z), ["2026-11-17-session"])
                meta = json.loads((tmp / "meetings/2026-11-17-session/meta.json").read_text())
                tr = json.loads((tmp / "meetings/2026-11-17-session/transcript.json").read_text())
                self.assertNotIn("extra", meta)
                self.assertEqual(tr["note"], meetings.NOTE)
                self.assertEqual(tr["segments"], [{"start": 0, "end": 2.0, "text": "Call to order."}])
                self.assertEqual(meetings.take(z), [])  # already there
                self.assertFalse((tmp / "evil").exists())


if __name__ == "__main__":
    unittest.main()
