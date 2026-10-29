#!/usr/bin/env bash
# Installs what transcribe.py needs. Safe to run again and again.
set -e

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[setup] installing ffmpeg"
  if command -v brew >/dev/null 2>&1; then
    brew install ffmpeg >/dev/null 2>&1
  else
    (apt-get update -qq && apt-get install -y -qq ffmpeg) >/dev/null 2>&1 || \
      (sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg) >/dev/null 2>&1
  fi
  command -v ffmpeg >/dev/null 2>&1 || { echo "[setup] could not install ffmpeg. On Mac: install Homebrew, then 'brew install ffmpeg'"; exit 1; }
fi

if ! python3 -c "import faster_whisper, gdown, requests, numpy" >/dev/null 2>&1; then
  echo "[setup] installing python packages"
  pip install -q --break-system-packages faster-whisper gdown requests numpy 2>/dev/null || \
    pip install -q faster-whisper gdown requests numpy
fi

echo "[setup] ready"
