#!/usr/bin/env bash
# Installs what transcribe.py needs. Safe to run again and again.
set -e

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[setup] installing ffmpeg"
  (apt-get update -qq && apt-get install -y -qq ffmpeg) >/dev/null 2>&1 || \
    (sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg) >/dev/null 2>&1
fi

if ! python3 -c "import faster_whisper, gdown, requests, numpy" >/dev/null 2>&1; then
  echo "[setup] installing python packages"
  pip install -q --break-system-packages faster-whisper gdown requests numpy 2>/dev/null || \
    pip install -q faster-whisper gdown requests numpy
fi

echo "[setup] ready"
