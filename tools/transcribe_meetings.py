#!/usr/bin/env python3
"""Unofficial transcripts of Georgia PSC administrative sessions and committee
meetings, made on your own computer.

YouTube turns away the cloud computers that build Public Service Records, so
this script does the one step they can't: it reads the Commission's YouTube
channel from your computer, downloads only the sound of each new session or
committee meeting, turns the speech into text, and packs the results into one
zip file. Upload that zip in the chat and it goes onto Records.

Run it from a terminal:

    python3 transcribe_meetings.py

The first run sets itself up in ~/.psc-transcripts (it downloads the
speech-to-text model and the tools it needs, about 1 GB) and then works through
every meeting since July 1, 2026 that Records doesn't have yet. Later runs only
do the new ones. It is slow: leave the window open until it says it's done.

Options:
    --limit 2          do at most this many meetings this run
    --since 2026-10-01 skip meetings before this day
    --model small.en   speech-to-text model (medium.en is more accurate, slower)

Nothing is uploaded anywhere by this script. It reads YouTube and the public
Records repository on GitHub, and writes files only in ~/.psc-transcripts and
the zip it names at the end. The sound file is deleted once it's transcribed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HOME = Path.home() / ".psc-transcripts"
ENV = HOME / "venv"
OUT = HOME / "meetings"
CHANNEL = "https://www.youtube.com/@GeorgiaPSC/streams"
DONE_URL = "https://api.github.com/repos/gapublicservice/records/contents/data/meetings"
PACKAGES = ["yt-dlp[default]", "deno", "faster-whisper"]
NOTE = ("Unofficial machine transcript, made by speech-to-text from the Commission's "
        "video. It will contain mistakes, and speakers are not identified. Check any "
        "quote against the video at its time mark.")
TITLES = [
    ("session", re.compile(r"^PSC Administrative Session\s+(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s*$", re.I)),
    ("committee", re.compile(r"^PSC Committee Hearings?\s*-?\s*(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s*$", re.I)),
]


def say(msg: str) -> None:
    print(msg, flush=True)


def env_bin() -> Path:
    return ENV / ("Scripts" if os.name == "nt" else "bin")


def env_python() -> Path:
    return env_bin() / ("python.exe" if os.name == "nt" else "python")


def in_env() -> bool:
    try:
        return Path(sys.prefix).resolve() == ENV.resolve()
    except OSError:
        return False


# The speech-to-text parts are published ready-made only for these versions
# (Python 3.14 has none yet on Intel Macs, so pip tries to build them and fails).
OK_VERSIONS = ("3.13", "3.12", "3.11", "3.10")


def _version(py: str) -> str | None:
    try:
        r = subprocess.run([py, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def pick_python() -> str | None:
    """A Python on this computer that the speech-to-text parts support."""
    if "%d.%d" % sys.version_info[:2] in OK_VERSIONS:
        return sys.executable
    places = ["/opt/homebrew/bin", "/usr/local/bin", "/Library/Frameworks/Python.framework/Versions/Current/bin"]
    for v in OK_VERSIONS:
        for cand in [shutil.which(f"python{v}")] + [f"{d}/python{v}" for d in places]:
            if cand and Path(cand).exists() and _version(cand) == v:
                return cand
    return None


def env_version() -> str | None:
    cfg = ENV / "pyvenv.cfg"
    if not cfg.exists():
        return None
    for line in cfg.read_text().splitlines():
        k, _, val = line.partition("=")
        if k.strip() in ("version", "version_info"):
            return ".".join(val.strip().split(".")[:2])
    return None


def setup() -> None:
    """Make the private Python environment the first time, then rerun inside it."""
    if env_python().exists() and env_version() not in OK_VERSIONS:
        say("Removing an earlier setup that used an unsupported Python.")
        shutil.rmtree(ENV)
    if not env_python().exists():
        py = pick_python()
        if not py:
            have = "%d.%d" % sys.version_info[:2]
            hint = ("Run this, then run the script again:\n\n    brew install python@3.12\n"
                    if shutil.which("brew") else
                    "Install Python 3.12 from python.org, then run the script again.")
            sys.exit(f"This computer's python3 is {have}, and the speech-to-text tools need "
                     f"Python 3.10 to 3.13. {hint}")
        say(f"Setting up for the first time in ~/.psc-transcripts with Python {_version(py)}. "
            "This takes a few minutes.")
        HOME.mkdir(parents=True, exist_ok=True)
        subprocess.run([py, "-m", "venv", str(ENV)], check=True)
    say("Checking the tools are up to date.")
    try:
        subprocess.run([str(env_python()), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
        subprocess.run([str(env_python()), "-m", "pip", "install", "-q", "--upgrade", "--only-binary=av,ctranslate2,onnxruntime,tokenizers", *PACKAGES], check=True)
    except subprocess.CalledProcessError:
        sys.exit("Installing the tools failed (above). Copy what this window says and paste it in the chat.")
    os.environ["PATH"] = str(env_bin()) + os.pathsep + os.environ.get("PATH", "")
    os.environ["PSC_TRANSCRIPTS_READY"] = "1"
    args = [str(env_python()), str(Path(__file__).resolve()), *sys.argv[1:]]
    if os.name == "nt":
        sys.exit(subprocess.run(args).returncode)
    os.execv(args[0], args)


def meeting_of(title: str):
    for kind, rx in TITLES:
        m = rx.match((title or "").strip())
        if m:
            mo, d, y = map(int, m.groups())
            try:
                return kind, dt.date(y, mo, d).isoformat()
            except ValueError:
                return None
    return None


def on_records() -> set[str]:
    """Meetings Records already has, from the public repository."""
    try:
        req = urllib.request.Request(DONE_URL, headers={"Accept": "application/vnd.github+json",
                                                        "User-Agent": "psc-transcripts"})
        ctx = None
        try:
            import certifi, ssl
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return {x["name"] for x in json.load(r) if x.get("type") == "dir"}
    except Exception as err:  # 404 before the first transcript, or offline
        if getattr(err, "code", None) != 404:
            say(f"(Couldn't check which meetings Records already has: {err}. Doing all of them.)")
        return set()


def yt_dlp(*args: str, capture: bool = False) -> str:
    exe = shutil.which("yt-dlp", path=str(env_bin())) or "yt-dlp"
    r = subprocess.run([exe, *args], capture_output=capture, text=True)
    if r.returncode != 0:
        if capture and r.stderr:
            say(r.stderr.strip()[-2000:])
        raise SystemExit("YouTube didn't answer as expected (above). Copy what this window says "
                         "and paste it in the chat, and I'll fix the script.")
    return r.stdout if capture else ""


def find(since: str, skip: set[str]) -> list[dict]:
    say("Looking at the Commission's YouTube channel.")
    out = yt_dlp("--flat-playlist", "--dump-json", "--playlist-end", "120", CHANNEL, capture=True)
    todo, seen = [], set()
    for line in out.splitlines():
        try:
            v = json.loads(line)
        except json.JSONDecodeError:
            continue
        got = meeting_of(v.get("title") or "")
        if not got or v.get("live_status") in ("is_live", "is_upcoming"):
            continue
        kind, date = got
        mid = f"{date}-{kind}"
        if date < since or mid in skip or mid in seen:
            continue
        seen.add(mid)
        todo.append({"id": mid, "date": date, "kind": kind, "title": v.get("title"),
                     "url": f"https://www.youtube.com/watch?v={v['id']}"})
    todo.sort(key=lambda x: x["date"])
    return todo


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def clock(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def do_one(m: dict, model, model_name: str) -> None:
    with tempfile.TemporaryDirectory(prefix="psc-audio-") as tmp:
        work = Path(tmp)
        say(f"Downloading the sound of {m['title']}.")
        yt_dlp("--no-playlist", "-q", "--progress", "-f", "bestaudio[ext=m4a]/bestaudio",
               "--write-info-json", "-o", str(work / f"{m['id']}.%(ext)s"), m["url"])
        audio = next(p for p in work.glob(f"{m['id']}.*") if not p.name.endswith(".json"))
        info = json.loads((work / f"{m['id']}.info.json").read_text())
        dur = info.get("duration") or 0
        meta = {"id": m["id"], "date": m["date"], "kind": m["kind"],
                "source_page": info.get("webpage_url") or m["url"], "title": info.get("title"),
                "duration": info.get("duration"), "audio_file": audio.name,
                "audio_sha256": sha256(audio), "pulled": now(), "made_with": "tools/transcribe_meetings.py"}
        say(f"Transcribing {clock(dur)} of sound. It prints a time mark every few minutes.")
        segments, lang = model.transcribe(str(audio), vad_filter=True, beam_size=5)
        segs, last = [], -300.0
        for s in segments:
            if s.text.strip():
                segs.append({"start": round(s.start, 1), "end": round(s.end, 1), "text": s.text.strip()})
            if s.start - last >= 300:
                last = s.start
                say(f"  {clock(s.start)} of {clock(dur)}")
        rec = {"id": m["id"], "model": f"faster-whisper {model_name}", "language": lang.language,
               "made": now(), "note": NOTE, "segments": segs}
        d = OUT / m["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
        (d / "transcript.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n")
        say(f"Done: {m['id']}, {len(segs)} lines. The sound file is deleted.")


def pack(ids: list[str]) -> Path:
    desk = Path.home() / "Desktop"
    where = desk if desk.is_dir() else Path.home()
    z = where / f"psc-transcripts-{dt.date.today().isoformat()}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for mid in ids:
            for name in ("meta.json", "transcript.json"):
                zf.write(OUT / mid / name, f"meetings/{mid}/{name}")
    return z


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--since", default="2026-07-01")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default="small.en")
    a = ap.parse_args()
    if not in_env() or not os.environ.get("PSC_TRANSCRIPTS_READY"):
        setup()
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    have = on_records()
    made_here = {p.parent.name for p in OUT.glob("*/transcript.json")}
    todo = find(a.since, have | made_here)
    waiting = sorted(made_here - have)
    if a.limit:
        todo = todo[:a.limit]
    if not todo and not waiting:
        say("Records already has every session and committee meeting. Nothing to do.")
        return 0
    if todo:
        say(f"{len(todo)} meeting(s) to transcribe: " + ", ".join(m["id"] for m in todo))
        from faster_whisper import WhisperModel
        say("Loading the speech-to-text model (the first time, this downloads it).")
        model = WhisperModel(a.model, device="cpu", compute_type="int8")
        for m in todo:
            try:
                do_one(m, model, a.model)
            except SystemExit:
                raise
            except Exception as err:
                say(f"Skipped {m['id']}: {err}")
    ids = sorted({p.parent.name for p in OUT.glob("*/transcript.json")} - have)
    if not ids:
        say("Nothing new was made this time.")
        return 1
    z = pack(ids)
    say("")
    say(f"All done. {len(ids)} transcript(s) are in this file:")
    say(f"  {z}")
    say("Upload it in the chat and I'll put them on Records.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
