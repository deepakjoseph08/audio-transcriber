#!/usr/bin/env bash
# Installs what transcribe.py needs. Safe to run again and again.
# Works on Linux (cloud sessions), Mac (Homebrew) and Windows (Git Bash + winget).
set -e

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) OS=windows ;;
  Darwin) OS=mac ;;
  *) OS=linux ;;
esac

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[setup] installing ffmpeg"
  if [ "$OS" = windows ]; then
    winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements >/dev/null 2>&1 || true
    echo "[setup] ffmpeg installed by winget. If it is still 'not found', close and reopen Claude Code so Windows picks up the new PATH."
  elif command -v brew >/dev/null 2>&1; then
    brew install ffmpeg >/dev/null 2>&1
  else
    (apt-get update -qq && apt-get install -y -qq ffmpeg) >/dev/null 2>&1 || \
      (sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg) >/dev/null 2>&1
  fi
  command -v ffmpeg >/dev/null 2>&1 || { echo "[setup] ffmpeg not found yet. Mac: 'brew install ffmpeg'. Windows: 'winget install Gyan.FFmpeg' then reopen Claude Code."; exit 1; }
fi

# On Windows the command is usually 'python' or 'py', not 'python3'
PY=""
for cand in python3 python py; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
[ -n "$PY" ] || { echo "[setup] Python 3.9+ not found. Install it from python.org (tick 'Add to PATH')."; exit 1; }

if ! "$PY" -c "import faster_whisper, gdown, requests, numpy" >/dev/null 2>&1; then
  echo "[setup] installing python packages"
  "$PY" -m pip install -q --break-system-packages faster-whisper gdown requests numpy 2>/dev/null || \
    "$PY" -m pip install -q faster-whisper gdown requests numpy
fi

echo "[setup] ready (python command: $PY)"
