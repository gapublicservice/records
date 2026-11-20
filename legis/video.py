"""Pull hearing video, transcribe it, and save both, so a view heard only on
video can be checked and linked to the moment it was said.

    python -m legis.video pull <video page url> --id <short id>
    python -m legis.video transcribe --id <short id> [--model base.en]
    python -m legis.video find --id <short id> "exact words to look for"

Committee video is on Vimeo (House) and the Public Service Commission streams
on YouTube; yt-dlp reads both. Transcripts are made with faster-whisper on the
runner's CPU. Media files are too large for the repository, so the workflow
attaches each one to a GitHub release of the public repository, and the
transcript records that copy's address and the file's SHA-256 so anyone can
confirm it is the same video.

data/legislature/video/<id>/meta.json        source page, title, date, duration, sha256, archive_url
data/legislature/video/<id>/transcript.json  segments with start and end seconds
data/legislature/video/<id>/transcript.vtt   the same, as captions
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from . import store
from .views import VIDEO, quote_in


def media_dir(vid: str) -> Path:
    return VIDEO / vid


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pull(url: str, vid: str, work: Path) -> dict:
    """Download a hearing at modest quality, plus its metadata."""
    work.mkdir(parents=True, exist_ok=True)
    out = work / f"{vid}.%(ext)s"
    subprocess.run(["yt-dlp", "--no-playlist", "-f", "bv*[height<=360]+ba/b[height<=360]/b",
                    "--merge-output-format", "mp4", "--write-info-json", "-o", str(out), url],
                   check=True)
    media = next(work.glob(f"{vid}.mp4"))
    info = json.loads(next(work.glob(f"{vid}.info.json")).read_text())
    meta = {"id": vid, "source_page": url, "title": info.get("title"),
            "uploaded": info.get("upload_date"), "duration": info.get("duration"),
            "webpage_url": info.get("webpage_url") or url, "file": media.name,
            "bytes": media.stat().st_size, "sha256": sha256(media), "pulled": store.now(),
            "archive_url": None}
    store.write_json(media_dir(vid) / "meta.json", meta)
    return meta


def transcribe(media: Path, vid: str, model: str = "base.en") -> dict:
    from faster_whisper import WhisperModel

    m = WhisperModel(model, device="cpu", compute_type="int8")
    segments, info = m.transcribe(str(media), vad_filter=True, word_timestamps=False)
    segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments]
    rec = {"id": vid, "model": model, "language": info.language, "made": store.now(),
           "note": "Machine transcript. Check a quote against the video at its timestamp.",
           "segments": segs}
    store.write_json(media_dir(vid) / "transcript.json", rec)
    (media_dir(vid) / "transcript.vtt").write_text(to_vtt(segs))
    return rec


def _ts(s: float) -> str:
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{sec:06.3f}"


def to_vtt(segs: list[dict]) -> str:
    lines = ["WEBVTT", ""]
    for s in segs:
        lines += [f'{_ts(s["start"])} --> {_ts(s["end"])}', s["text"], ""]
    return "\n".join(lines)


def find(vid: str, quote: str) -> dict:
    """Where a quote was said: start second, matching text and score."""
    segs = json.loads((media_dir(vid) / "transcript.json").read_text())["segments"]
    words, owner = [], []
    for i, s in enumerate(segs):
        for w in s["text"].split():
            words.append(w)
            owner.append(i)
    found, ratio, at = quote_in(quote, " ".join(words))
    if at < 0:
        return {"found": False, "ratio": ratio}
    seg = segs[owner[min(at, len(owner) - 1)]]
    return {"found": found, "ratio": ratio, "start_seconds": int(seg["start"]), "segment": seg["text"]}


def moment_link(meta: dict, seconds: int) -> str:
    """A link that opens the video at the moment a quote was said."""
    page = meta.get("webpage_url") or meta.get("source_page") or ""
    if "youtube.com" in page or "youtu.be" in page:
        sep = "&" if "?" in page else "?"
        return f"{page}{sep}t={seconds}s"
    if "vimeo.com" in page:
        return f"{page.split('#')[0]}#t={seconds}s"
    if meta.get("archive_url"):
        return f'{meta["archive_url"]}#t={seconds}'
    return page


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull"); p.add_argument("url"); p.add_argument("--id", required=True)
    p.add_argument("--work", default="_video")
    t = sub.add_parser("transcribe"); t.add_argument("--id", required=True)
    t.add_argument("--work", default="_video"); t.add_argument("--model", default="base.en")
    f = sub.add_parser("find"); f.add_argument("--id", required=True); f.add_argument("quote")
    r = sub.add_parser("archived"); r.add_argument("--id", required=True); r.add_argument("url")
    a = ap.parse_args(argv)
    if a.cmd == "pull":
        print(json.dumps(pull(a.url, a.id, Path(a.work)), indent=1))
    elif a.cmd == "transcribe":
        media = next(Path(a.work).glob(f"{a.id}.mp4"))
        rec = transcribe(media, a.id, a.model)
        print(f'{len(rec["segments"])} segments')
    elif a.cmd == "find":
        print(json.dumps(find(a.id, a.quote), indent=1))
    elif a.cmd == "archived":
        mp = media_dir(a.id) / "meta.json"
        meta = json.loads(mp.read_text())
        meta["archive_url"] = a.url
        store.write_json(mp, meta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
