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
every meeting since July 1, 2026 that Records doesn't have yet, newest first.
Each finished meeting gets its own zip on your Desktop right away. Later runs
only do the new ones.

To make it automatic on a Mac:

    python3 transcribe_meetings.py --install

That saves a GitHub key you make (it goes into your Mac's Keychain, never into
the chat), and sets the Mac to run this every day at 1 PM, 3 PM and 7 PM while it is
on. Each run fetches the newest copy of this script from the Records
repository, transcribes any new meeting, and sends each transcript to the
Records inbox on GitHub, where it is checked and published. A notice pops up
when one is sent. Undo it all with --uninstall.

Options:
    --limit 2          do at most this many meetings this run
    --since 2026-10-01 skip meetings before this day
    --model small.en   speech-to-text model (medium.en is more accurate, slower)

It reads YouTube and the public Records repository on GitHub. Without the key
it uploads nothing and writes files only in ~/.psc-transcripts and the zips it
names. With the key it also sends the finished transcripts to the Records
inbox. The sound file is deleted once it's transcribed.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

HOME = Path.home() / ".psc-transcripts"
ENV = HOME / "venv"
OUT = HOME / "meetings"
CHANNEL = "https://www.youtube.com/@GeorgiaPSC/streams"
REPO = "gapublicservice/records"
DONE_URL = f"https://api.github.com/repos/{REPO}/contents/data/meetings"
INBOX_URL = f"https://api.github.com/repos/{REPO}/contents/inbox/transcripts"
SCRIPT_URL = f"https://raw.githubusercontent.com/{REPO}/main/tools/transcribe_meetings.py"
KEY_SERVICE, KEY_ACCOUNT = "psc-transcripts-github", "records"
LABEL = "org.gapublicservice.psc-transcripts"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG = HOME / "log.txt"
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
    # Newest first, so the latest meetings are ready to use soonest.
    todo.sort(key=lambda x: (x["date"], x["kind"]), reverse=True)
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


def decode(path: Path):
    """The sound as 16 kHz mono samples. faster-whisper's own reader passes an
    option newer PyAV versions dropped, so the script reads the file itself."""
    import av
    import numpy as np

    rs = av.AudioResampler(format="s16", layout="mono", rate=16000)
    parts = []
    with av.open(str(path)) as c:
        for frame in c.decode(audio=0):
            frame.pts = None
            parts.extend(f.to_ndarray() for f in rs.resample(frame))
    parts.extend(f.to_ndarray() for f in rs.resample(None))
    if not parts:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(parts, axis=1).reshape(-1).astype(np.float32) / 32768.0


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
        segments, lang = model.transcribe(decode(audio), vad_filter=True, beam_size=5)
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


def _ctx():
    try:
        import certifi, ssl
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None


def github_key() -> str | None:
    """The key saved by --install, from the Mac's Keychain (or PSC_GITHUB_TOKEN)."""
    if os.environ.get("PSC_GITHUB_TOKEN"):
        return os.environ["PSC_GITHUB_TOKEN"].strip()
    if sys.platform != "darwin":
        return None
    r = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", KEY_SERVICE, "-a", KEY_ACCOUNT, "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip() or None


def gh(method: str, url: str, key: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "psc-transcripts",
                                          "Authorization": f"Bearer {key}", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=_ctx()) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.load(err)
        except Exception:
            return err.code, {}


def zip_bytes(mid: str) -> bytes:
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ("meta.json", "transcript.json"):
            zf.write(OUT / mid / name, f"meetings/{mid}/{name}")
    return buf.getvalue()


def send(mid: str, key: str) -> bool:
    """Put one meeting's zip in the Records inbox. True if it is there."""
    code, body = gh("PUT", f"{INBOX_URL}/{mid}.zip", key,
                    {"message": f"Transcript {mid} from Paul's computer (unofficial)",
                     "content": base64.b64encode(zip_bytes(mid)).decode()})
    if code in (200, 201):
        say(f"Sent {mid} to Records. It goes live once GitHub checks it.")
        return True
    if code == 422:  # already waiting in the inbox
        return True
    say(f"Couldn't send {mid} to Records (GitHub said {code}: {body.get('message', '')}).")
    return False


def notify(msg: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["/usr/bin/osascript", "-e",
                        f'display notification {json.dumps(msg)} with title "PSC transcripts"'],
                       capture_output=True)


def pack(ids: list[str], name: str | None = None) -> Path:
    desk = Path.home() / "Desktop"
    where = desk if desk.is_dir() else Path.home()
    z = where / (name or f"psc-transcripts-{dt.date.today().isoformat()}.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for mid in ids:
            for name in ("meta.json", "transcript.json"):
                zf.write(OUT / mid / name, f"meetings/{mid}/{name}")
    return z


RUNNER = """#!/bin/bash
# Run by launchd. Fetch the newest script, check it parses, then run it.
cd "$HOME/.psc-transcripts" || exit 1
if /usr/bin/curl -fsSL "{url}" -o transcribe_meetings.py.new &&
   "{py}" -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" transcribe_meetings.py.new; then
  mv transcribe_meetings.py.new transcribe_meetings.py
else
  rm -f transcribe_meetings.py.new
fi
echo "=== $(date)"
exec "{py}" transcribe_meetings.py --auto
"""

PLIST_TEXT = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>{runner}</string></array>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>19</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
  <key>ProcessType</key><string>Background</string>
  <key>Nice</key><integer>10</integer>
</dict>
</plist>
"""


def install() -> int:
    if sys.platform != "darwin":
        sys.exit("--install sets up a Mac. On another computer, run the script by hand.")
    key = github_key()
    if key and gh("GET", f"https://api.github.com/repos/{REPO}", key)[1].get("permissions", {}).get("push"):
        say("Your GitHub key is already saved and works.")
    else:
        say("""
Step 1 of 2: make a GitHub key that can only add files to the Records repository.

  1. Open https://github.com/settings/personal-access-tokens/new in your browser.
  2. Token name: PSC transcripts. Expiration: 1 year (or what you like).
  3. Resource owner: gapublicservice.
  4. Repository access: Only select repositories, then pick gapublicservice/records.
  5. Permissions: Repository permissions, Contents, set to Read and write.
  6. Generate the token and copy it.

Never paste it in the chat. When the next line asks for "password data", paste
it here instead (nothing shows as you paste), press Return, and paste it again
if asked. It is saved in your Mac's Keychain.
""")
        subprocess.run(["/usr/bin/security", "add-generic-password", "-U", "-s", KEY_SERVICE,
                        "-a", KEY_ACCOUNT, "-w"])
        key = github_key()
        if not key:
            sys.exit("The key wasn't saved. Run this again with --install.")
        code, body = gh("GET", f"https://api.github.com/repos/{REPO}", key)
        if not body.get("permissions", {}).get("push"):
            sys.exit(f"GitHub didn't accept that key for {REPO} (it said {code}). Check steps 3 to 5, "
                     "then run this again with --install.")
        say("The key works.")
    say("Step 2 of 2: setting the Mac to run this every day at 1 PM, 3 PM and 7 PM.")
    HOME.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(__file__).resolve(), HOME / "transcribe_meetings.py")
    runner = HOME / "run.sh"
    runner.write_text(RUNNER.format(url=SCRIPT_URL, py=env_python()))
    runner.chmod(0o755)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_text(PLIST_TEXT.format(label=LABEL, runner=runner, log=LOG))
    uid = str(os.getuid())
    subprocess.run(["/bin/launchctl", "bootout", f"gui/{uid}", str(PLIST)], capture_output=True)
    r = subprocess.run(["/bin/launchctl", "bootstrap", f"gui/{uid}", str(PLIST)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"The Mac didn't take the schedule: {r.stderr.strip()}. Paste this in the chat.")
    say(f"""
All set. Every day at 1 PM, 3 PM and 7 PM, while this Mac is on and awake, it checks
for new meetings and sends their transcripts to Records. If the Mac is asleep
then, it runs when it wakes. What it did is written to {LOG}.
To stop it: python3 ~/.psc-transcripts/transcribe_meetings.py --uninstall""")
    return 0


def uninstall() -> int:
    if PLIST.exists():
        subprocess.run(["/bin/launchctl", "bootout", f"gui/{os.getuid()}", str(PLIST)], capture_output=True)
        PLIST.unlink()
    subprocess.run(["/usr/bin/security", "delete-generic-password", "-s", KEY_SERVICE, "-a", KEY_ACCOUNT],
                   capture_output=True)
    say("Stopped. The schedule and the saved key are removed from this Mac. To cancel the key "
        "itself, delete \"PSC transcripts\" at https://github.com/settings/personal-access-tokens.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--since", default="2026-07-01")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default="small.en")
    ap.add_argument("--install", action="store_true", help="run it automatically on this Mac")
    ap.add_argument("--uninstall", action="store_true", help="stop running it automatically")
    ap.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.uninstall:
        return uninstall()
    if not in_env() or not os.environ.get("PSC_TRANSCRIPTS_READY"):
        setup()
        return 0
    if a.install:
        install()
        say("\nStarting the first run now. Leave this window open, or close it and the "
            "1 PM, 3 PM or 7 PM run will pick up where it stopped.\n")
    import fcntl
    HOME.mkdir(parents=True, exist_ok=True)
    lock = open(HOME / "run.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        say("Another run is already going on this computer. Leaving it to finish.")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    key = github_key()
    have = on_records()
    made_here = {p.parent.name for p in OUT.glob("*/transcript.json")}
    sent: list[str] = []
    if key:
        for mid in sorted(made_here - have, reverse=True):
            if send(mid, key):
                sent.append(mid)
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
        fails, tried, done_n = 0, set(), 0
        while todo:
            m = todo[0]
            tried.add(m["id"])
            try:
                do_one(m, model, a.model)
                if key and send(m["id"], key):
                    sent.append(m["id"])
                    notify(f"Transcript of {m['title']} sent to Records.")
                else:
                    one = pack([m["id"]], f"psc-transcript-{m['id']}.zip")
                    say(f"Ready to upload now, while the rest keep going: {one}")
                fails = 0
            except SystemExit:
                raise
            except Exception as err:
                fails += 1
                say(f"Skipped {m['id']}: {err}")
                if fails >= 2:
                    say("Two meetings in a row failed the same way, so I stopped. Copy what this "
                        "window says and paste it in the chat.")
                    notify("Transcripts stopped on an error. Details are in ~/.psc-transcripts/log.txt.")
                    break
            done_n += 1
            if a.limit and done_n >= a.limit:
                break
            # Look again after each meeting, so one posted while older ones are being
            # worked through goes next instead of waiting behind them.
            try:
                todo = find(a.since, have | {p.parent.name for p in OUT.glob("*/transcript.json")} | tried)
            except Exception as err:
                say(f"Couldn't look at the channel again ({err}); going on with the list I have.")
                todo = [t for t in todo if t["id"] not in tried]
    ids = sorted({p.parent.name for p in OUT.glob("*/transcript.json")} - have - set(sent))
    if key and not ids:
        say(f"All done. {len(sent)} transcript(s) sent to Records this run." if sent else "Nothing new this run.")
        return 0
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
