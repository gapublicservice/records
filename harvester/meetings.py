"""Unofficial transcripts of Commission administrative sessions and committee
meetings, made by speech-to-text from the Commission's own YouTube stream.

Hearings are left out: the Commission files a court reporter's transcript for
each hearing in its docket, and that is the record. Sessions and committee
meetings get no filed transcript, so this is the only text of what was said.

    python -m harvester.meetings find [--since 2026-07-01] [--limit 3]
    python -m harvester.meetings pull <youtube url> --date 2026-11-17 --kind session
    python -m harvester.meetings transcribe --id 2026-11-17-session [--model small.en]

Only the audio is downloaded, to transcribe it; no copy of the video is kept or
posted. Each transcript records the stream's address, its title as posted, and
the SHA-256 of the audio that was transcribed.

data/meetings/<id>/meta.json        source page, title, date, kind, duration, audio sha256
data/meetings/<id>/transcript.json  segments with start and end seconds
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from .run import DATA, now_utc, save_json

MEETINGS = DATA / "meetings"
CHANNEL = "https://www.youtube.com/@GeorgiaPSC/streams"
NOTE = ("Unofficial machine transcript, made by speech-to-text from the Commission's "
        "video. It will contain mistakes, and speakers are not identified. Check any "
        "quote against the video at its time mark.")

# Titles as the channel posts them: "PSC Administrative Session 11-17-2026",
# "PSC Committee Hearings - 11/24/2026".
TITLES = [
    ("session", re.compile(r"^PSC Administrative Session\s+(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s*$", re.I)),
    ("committee", re.compile(r"^PSC Committee Hearings?\s*-?\s*(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s*$", re.I)),
]


def meeting_of(title: str) -> tuple[str, str] | None:
    """(kind, ISO date) for a session or committee stream title, else None."""
    for kind, rx in TITLES:
        m = rx.match((title or "").strip())
        if m:
            mo, d, y = map(int, m.groups())
            try:
                return kind, dt.date(y, mo, d).isoformat()
            except ValueError:
                return None
    return None


def mid(date: str, kind: str) -> str:
    return f"{date}-{kind}"


def done(vid: str) -> bool:
    return (MEETINGS / vid / "transcript.json").exists()


def find(since: str, limit: int) -> list[dict]:
    """Session and committee streams on the channel not yet transcribed, oldest first."""
    out = subprocess.run(["yt-dlp", "--flat-playlist", "--dump-json", "--playlist-end", "80", CHANNEL],
                         check=True, capture_output=True, text=True).stdout
    todo = []
    for line in out.splitlines():
        v = json.loads(line)
        got = meeting_of(v.get("title") or "")
        if not got:
            continue
        kind, date = got
        if date < since or done(mid(date, kind)) or v.get("live_status") in ("is_live", "is_upcoming"):
            continue
        todo.append({"url": f"https://www.youtube.com/watch?v={v['id']}", "date": date, "kind": kind,
                     "title": v.get("title")})
    todo.sort(key=lambda x: x["date"])
    return todo[:limit]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pull(url: str, date: str, kind: str, work: Path) -> dict:
    vid = mid(date, kind)
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(["yt-dlp", "--no-playlist", "-f", "bestaudio[ext=m4a]/bestaudio", "--write-info-json",
                    "-o", str(work / f"{vid}.%(ext)s"), url], check=True)
    audio = next(p for p in work.glob(f"{vid}.*") if not p.name.endswith(".json"))
    info = json.loads((work / f"{vid}.info.json").read_text())
    meta = {"id": vid, "date": date, "kind": kind, "source_page": info.get("webpage_url") or url,
            "title": info.get("title"), "duration": info.get("duration"), "audio_file": audio.name,
            "audio_sha256": sha256(audio), "pulled": now_utc()}
    save_json(MEETINGS / vid / "meta.json", meta)
    return meta


def transcribe(vid: str, work: Path, model: str) -> dict:
    from faster_whisper import WhisperModel

    audio = next(p for p in work.glob(f"{vid}.*") if not p.name.endswith(".json"))
    m = WhisperModel(model, device="cpu", compute_type="int8")
    segments, info = m.transcribe(str(audio), vad_filter=True, beam_size=5)
    segs = [{"start": round(s.start, 1), "end": round(s.end, 1), "text": s.text.strip()}
            for s in segments if s.text.strip()]
    rec = {"id": vid, "model": f"faster-whisper {model}", "language": info.language,
           "made": now_utc(), "note": NOTE, "segments": segs}
    save_json(MEETINGS / vid / "transcript.json", rec)
    return rec


def all_meetings() -> list[dict]:
    """Every transcribed meeting, newest first: meta plus segments."""
    out = []
    for d in sorted(MEETINGS.glob("*/transcript.json")):
        try:
            meta = json.loads((d.parent / "meta.json").read_text())
            tr = json.loads(d.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        out.append({**meta, "segments": tr.get("segments") or [], "model": tr.get("model"),
                    "made": tr.get("made")})
    out.sort(key=lambda m: (m["date"], m["kind"]), reverse=True)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find"); f.add_argument("--since", default="2026-07-01")
    f.add_argument("--limit", type=int, default=3)
    p = sub.add_parser("pull"); p.add_argument("url"); p.add_argument("--date", required=True)
    p.add_argument("--kind", choices=["session", "committee"], required=True)
    p.add_argument("--work", default="_audio")
    t = sub.add_parser("transcribe"); t.add_argument("--id", required=True)
    t.add_argument("--work", default="_audio"); t.add_argument("--model", default="small.en")
    a = ap.parse_args(argv)
    if a.cmd == "find":
        print(json.dumps(find(a.since, a.limit)))
    elif a.cmd == "pull":
        print(json.dumps(pull(a.url, a.date, a.kind, Path(a.work)), indent=1))
    elif a.cmd == "transcribe":
        print(f'{len(transcribe(a.id, Path(a.work), a.model)["segments"])} segments')
    return 0


if __name__ == "__main__":
    sys.exit(main())
