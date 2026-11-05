"""Modelni oldindan yuklab olish (sayt ishlatishdan oldin, terminalda progress bilan).

  .venv\Scripts\python.exe download_model.py small          # Tez (~480 MB)
  .venv\Scripts\python.exe download_model.py medium         # Muvozanat (~1.5 GB)
  .venv\Scripts\python.exe download_model.py large-v3-turbo # Eng aniq (~1.6 GB)
"""
from __future__ import annotations

import sys

from app.config import load_settings
from app.services.engines.faster_whisper_engine import FasterWhisperEngine


def main() -> int:
    names = sys.argv[1:] or ["small"]
    s = load_settings()
    eng = FasterWhisperEngine(s)
    ok, reason = eng.available()
    if not ok:
        print("faster-whisper o'rnatilmagan:", reason)
        return 1

    def show(stage, d):
        if stage == "downloading_model":
            total = f" / {d['total_mb']} MB" if d.get("total_mb") else " MB"
            eta = f"  ~{d['eta'] // 60} daq qoldi" if d.get("eta") else ""
            print(f"\r  {d['model']}: {d['done_mb']:.0f}{total}  {d['speed_mbs']:.2f} MB/s{eta}      ", end="", flush=True)

    for name in names:
        print(f"Model: {name}  (papka: {s.model_dir})")
        path = eng.ensure_model(name, show)
        print(f"\n  [OK] {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
