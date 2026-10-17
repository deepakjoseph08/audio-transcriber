#!/usr/bin/env python3
"""Transcribe an audio/video file of any size.

Pipeline:
  1. Get the file (local path, Google Drive link, Dropbox link, or any direct URL).
  2. Shrink it with ffmpeg to 16 kHz mono (speech does not need more).
  3. Cut it into chunks at quiet moments (so words are not chopped in half).
  4. Transcribe each chunk with the chosen engine. Finished chunks are cached,
     so if the session dies you just re-run the same command and it resumes.
  5. Stitch everything into one timestamped transcript.

Engines:
  groq   - Whisper large-v3-turbo on Groq. Very fast. Needs GROQ_API_KEY.
  openai - OpenAI transcription API. Needs OPENAI_API_KEY.
  local  - faster-whisper on the CPU. Free, no key, slower.
  auto   - groq if its key is set, else openai if its key is set, else local.

Usage:
  python3 transcribe.py <file-or-url> [--out DIR] [--engine auto] [--language en]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CHUNK_SECONDS = 600   # aim for ~10 minute chunks
SEARCH_WINDOW = 45    # look this many seconds either side of the target for a pause
API_MAX_BYTES = 24 * 1024 * 1024  # Groq/OpenAI reject uploads over 25 MB


def log(msg):
    print(f"[transcribe] {msg}", flush=True)


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


# ---------- 1. fetch ----------

def fetch(source, workdir):
    if os.path.exists(source):
        return Path(source).resolve()
    if not re.match(r"https?://", source):
        sys.exit(f"Not a file and not a URL: {source}")

    dl_dir = workdir / "download"
    dl_dir.mkdir(parents=True, exist_ok=True)
    existing = [p for p in dl_dir.iterdir() if p.is_file() and not p.name.endswith(".part")]
    if existing:
        log(f"Using already downloaded {existing[0].name}")
        return existing[0]

    if "drive.google.com" in source or "docs.google.com" in source:
        import gdown
        m = re.search(r"/d/([\w-]{20,})", source) or re.search(r"[?&]id=([\w-]{20,})", source)
        if not m:
            sys.exit(f"Could not find a file id in this Google Drive link: {source}")
        log("Downloading from Google Drive...")
        try:
            path = gdown.download(id=m.group(1), output=str(dl_dir) + "/", quiet=False)
        except Exception as e:
            path = None
            log(f"  gdown said: {str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__}")
        if not path:
            sys.exit("Google Drive download failed. In Drive, tap Share > General access > "
                     "'Anyone with the link', then try again.")
        return Path(path)

    if "dropbox.com" in source:
        source = re.sub(r"([?&])dl=0", r"\1dl=1", source)
        if "dl=1" not in source:
            source += ("&" if "?" in source else "?") + "dl=1"

    name = re.sub(r"[^\w.\-]", "_", source.split("?")[0].rstrip("/").split("/")[-1]) or "audio"
    target = dl_dir / name
    log(f"Downloading {source} ...")
    tmp = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(source) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1024 * 1024)
    tmp.rename(target)
    return target


# ---------- 2. probe + split ----------

def duration_of(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)]).stdout.strip()
    return float(out)


def find_silences(path):
    """Return midpoints (seconds) of quiet gaps of at least 0.4 s."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
         "-af", "silencedetect=noise=-35dB:d=0.4", "-f", "null", "-"],
        capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    return [(s + e) / 2 for s, e in zip(starts, ends)]


def plan_cuts(total, silences, chunk=CHUNK_SECONDS):
    cuts, pos = [0.0], 0.0
    while total - pos > chunk * 1.3:
        target = pos + chunk
        near = [s for s in silences if abs(s - target) <= SEARCH_WINDOW and s > pos + 60]
        cut = min(near, key=lambda s: abs(s - target)) if near else target
        cuts.append(cut)
        pos = cut
    cuts.append(total)
    return cuts


def make_chunks(src, workdir, total):
    chunk_dir = workdir / "chunks"
    plan_file = workdir / "plan.json"
    if plan_file.exists():
        plan = json.loads(plan_file.read_text())
        if all((chunk_dir / c["file"]).exists() for c in plan):
            log(f"Reusing {len(plan)} chunks from earlier run")
            return plan

    chunk_dir.mkdir(parents=True, exist_ok=True)
    log("Looking for natural pauses to cut at...")
    cuts = plan_cuts(total, find_silences(src))
    plan = []
    for i, (a, b) in enumerate(zip(cuts, cuts[1:])):
        name = f"chunk_{i:03d}.ogg"
        # 16 kHz mono Opus at 24 kbps: ~1.8 MB per 10 minutes, still clear for speech
        run(["ffmpeg", "-hide_banner", "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(src),
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "24k",
             str(chunk_dir / name)])
        plan.append({"index": i, "file": name, "start": a, "end": b})
        log(f"  chunk {i + 1}/{len(cuts) - 1}: {fmt(a)} -> {fmt(b)}")
    plan_file.write_text(json.dumps(plan, indent=2))
    return plan


# ---------- 3. engines ----------

def pick_engine(name):
    if name != "auto":
        return name
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "local"


def api_transcribe(path, engine, language, prompt):
    import requests
    if engine == "groq":
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        key = os.environ["GROQ_API_KEY"]
        model = os.environ.get("GROQ_MODEL", "whisper-large-v3-turbo")
    else:
        url = "https://api.openai.com/v1/audio/transcriptions"
        key = os.environ["OPENAI_API_KEY"]
        model = os.environ.get("OPENAI_MODEL", "whisper-1")  # whisper-1 gives timestamps

    if path.stat().st_size > API_MAX_BYTES:
        sys.exit(f"{path.name} is over 24 MB, lower CHUNK_SECONDS")

    data = {"model": model, "response_format": "verbose_json", "temperature": "0"}
    if language:
        data["language"] = language
    if prompt:
        data["prompt"] = prompt[-800:]  # previous text helps keep names and spelling consistent

    for attempt in range(6):
        with open(path, "rb") as f:
            r = requests.post(url, headers={"Authorization": f"Bearer {key}"},
                              data=data, files={"file": (path.name, f, "audio/ogg")}, timeout=600)
        if r.status_code == 200:
            j = r.json()
            segs = j.get("segments") or [{"start": 0, "end": j.get("duration", 0), "text": j["text"]}]
            return [{"start": s["start"], "end": s["end"], "text": s["text"].strip()} for s in segs]
        if r.status_code in (429, 500, 502, 503, 504):
            wait = int(r.headers.get("retry-after", 0) or 0) or 2 ** (attempt + 1)
            log(f"  {engine} said {r.status_code}, waiting {wait}s and retrying")
            time.sleep(wait)
            continue
        sys.exit(f"{engine} error {r.status_code}: {r.text[:500]}")
    sys.exit(f"{engine} kept failing, try again later or use --engine local")


_local_model = None


def local_transcribe(path, language, prompt, model_size):
    global _local_model
    from faster_whisper import WhisperModel
    if _local_model is None:
        log(f"Loading local Whisper model '{model_size}' (first time downloads it)...")
        _local_model = WhisperModel(model_size, device="cpu", compute_type="int8",
                                    cpu_threads=os.cpu_count() or 4)
    # Decode with ffmpeg ourselves; faster-whisper's own decoder (PyAV) breaks across versions
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
                          "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         check=True, capture_output=True).stdout
    audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    segments, _ = _local_model.transcribe(
        audio, language=language, vad_filter=True, beam_size=1,
        initial_prompt=prompt[-800:] if prompt else None)
    return [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]


# ---------- 4. output ----------

def fmt(sec):
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def write_outputs(workdir, source_name, segments, total, engine):
    (workdir / "segments.json").write_text(json.dumps(segments, indent=1, ensure_ascii=False))
    (workdir / "transcript.txt").write_text(" ".join(s["text"] for s in segments), encoding="utf-8")

    # Group segments into ~1 minute paragraphs so the markdown is easy to read and cite
    lines = [f"# Transcript: {source_name}", "",
             f"- Duration: {fmt(total)}", f"- Engine: {engine}", ""]
    para, para_start = [], None
    for s in segments:
        if para_start is None:
            para_start = s["start"]
        para.append(s["text"])
        if s["end"] - para_start >= 60:
            lines += [f"**[{fmt(para_start)}]** " + " ".join(para), ""]
            para, para_start = [], None
    if para:
        lines += [f"**[{fmt(para_start)}]** " + " ".join(para), ""]
    (workdir / "transcript.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="local file, Google Drive link, Dropbox link, or direct URL")
    ap.add_argument("--out", help="output folder (default: transcripts/<file name>)")
    ap.add_argument("--engine", default="auto", choices=["auto", "groq", "openai", "local"])
    ap.add_argument("--language", default=None, help="e.g. en, hi. Leave empty to auto-detect")
    ap.add_argument("--local-model", default=os.environ.get("LOCAL_WHISPER_MODEL", "small"),
                    help="tiny / base / small / medium / large-v3 (bigger = better but slower)")
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} is not installed (apt-get install -y ffmpeg)")

    started = time.time()
    if args.out:
        workdir = Path(args.out)
    else:
        stem = Path(args.source.split("?")[0]).stem if os.path.exists(args.source) else \
            re.sub(r"\W+", "_", args.source)[-40:]
        workdir = Path("transcripts") / stem
    workdir.mkdir(parents=True, exist_ok=True)

    src = fetch(args.source, workdir)
    total = duration_of(src)
    log(f"File: {src.name}  size: {src.stat().st_size / 1e6:.1f} MB  length: {fmt(total)}")

    plan = make_chunks(src, workdir, total)
    engine = pick_engine(args.engine)
    log(f"Engine: {engine}" + (f" (model {args.local_model})" if engine == "local" else ""))
    if engine == "local":
        log("Tip: set GROQ_API_KEY for roughly 50x faster transcription")

    cache = workdir / f"cache_{engine}"
    cache.mkdir(exist_ok=True)
    all_segments, prev_text = [], ""
    for c in plan:
        out = cache / (c["file"] + ".json")
        if out.exists():
            segs = json.loads(out.read_text())
            log(f"  chunk {c['index'] + 1}/{len(plan)} already done")
        else:
            t0 = time.time()
            path = workdir / "chunks" / c["file"]
            if engine == "local":
                segs = local_transcribe(path, args.language, prev_text, args.local_model)
            else:
                segs = api_transcribe(path, engine, args.language, prev_text)
            out.write_text(json.dumps(segs, ensure_ascii=False))
            log(f"  chunk {c['index'] + 1}/{len(plan)} done in {time.time() - t0:.0f}s")
        for s in segs:
            all_segments.append({"start": s["start"] + c["start"], "end": s["end"] + c["start"],
                                 "text": s["text"]})
        prev_text = " ".join(s["text"] for s in segs)

    write_outputs(workdir, src.name, all_segments, total, engine)
    words = sum(len(s["text"].split()) for s in all_segments)
    log(f"DONE in {time.time() - started:.0f}s. {words} words.")
    log(f"Transcript: {workdir / 'transcript.md'}")


if __name__ == "__main__":
    main()
