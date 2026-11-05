#!/usr/bin/env bash
# Linux / macOS o'rnatish
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
command -v ffmpeg >/dev/null || { echo "FFmpeg kerak: sudo apt install ffmpeg  (macOS: brew install ffmpeg)"; exit 1; }
[ -d backend/.venv ] || $PY -m venv backend/.venv
backend/.venv/bin/pip install --upgrade pip >/dev/null
backend/.venv/bin/pip install -r backend/requirements.txt
[ -f .env ] || cp .env.example .env
echo "OK. Ishga tushirish: scripts/run.sh   (telefon uchun: scripts/run.sh --lan)"
