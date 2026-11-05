"""Haqiqiy audio bilan sifat va tezlik sinovi (WER / CER).

Ishlayotgan ilmhubstt serveriga audio yuboradi, natijani etalon matn bilan solishtiradi.

  # bitta fayl
  python scripts/real_asr_check.py --audio dars.mp3 --ref dars.txt --language uz

  # papka: har bir audio yonida bir xil nomli .txt etalon bo'lsin (masalan 01.mp3 + 01.txt)
  python scripts/real_asr_check.py --dir test_audio/uz --language uz --quality balanced --csv natija.csv

Eslatma: WER uchun 1–10 daqiqalik bo'laklar tavsiya etiladi (juda uzun matnda hisoblash sekin).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac", ".aac", ".mp4", ".mov", ".webm", ".mkv"}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[`´ʻʼ'’‘]", "‘", text)            # apostroflarni bir xil qilish
    text = re.sub(r"[^\w‘\s-]", " ", text)
    text = text.replace("-", " ")
    return re.sub(r"\s+", " ", text).strip()


def edit_distance(a: list, b: list) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


def wer_cer(ref: str, hyp: str) -> tuple[float, float]:
    r, h = normalize(ref), normalize(hyp)
    rw, hw = r.split(), h.split()
    wer = edit_distance(rw, hw) / max(1, len(rw))
    cer = edit_distance(list(r.replace(" ", "")), list(h.replace(" ", ""))) / max(1, len(r.replace(" ", "")))
    return wer, cer


def transcribe(server: str, audio: Path, args) -> dict:
    headers = {"x-access-key": args.key} if args.key else {}
    with open(audio, "rb") as fh:
        r = requests.post(f"{server}/api/v1/jobs", files={"file": (audio.name, fh)}, headers=headers, timeout=3600,
                          data={"language": args.language, "quality": args.quality, "mode": args.mode,
                                "engine": args.engine or ""})
    if r.status_code != 201:
        raise RuntimeError(f"{audio.name}: {r.status_code} {r.text}")
    job = r.json()
    h = {**headers, "x-job-token": job["token"]}
    t0 = time.time()
    while True:
        st = requests.get(f"{server}/api/v1/jobs/{job['job_id']}", headers=h, timeout=30).json()
        if st["status"] in ("completed", "failed", "cancelled"):
            break
        print(f"\r  {audio.name}: {st['status']} {st['progress']:.0f}%   ", end="", flush=True)
        time.sleep(2)
    print()
    if st["status"] != "completed":
        raise RuntimeError(f"{audio.name}: {st['status']} {st.get('error')}")
    res = requests.get(f"{server}/api/v1/jobs/{job['job_id']}/result", headers=h, timeout=60).json()
    res["_wall"] = time.time() - t0
    if not args.keep:
        requests.delete(f"{server}/api/v1/jobs/{job['job_id']}", headers=h, timeout=30)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--audio", type=Path)
    ap.add_argument("--ref", type=Path)
    ap.add_argument("--dir", type=Path)
    ap.add_argument("--language", default="uz", choices=["uz", "ky", "kk", "auto"])
    ap.add_argument("--quality", default="balanced", choices=["fast", "balanced", "best"])
    ap.add_argument("--mode", default="clean", choices=["clean", "verbatim"])
    ap.add_argument("--engine", default="")
    ap.add_argument("--key", default="")
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--keep", action="store_true", help="natijani serverda qoldirish")
    args = ap.parse_args()

    pairs: list[tuple[Path, Path | None]] = []
    if args.dir:
        for a in sorted(args.dir.iterdir()):
            if a.suffix.lower() in AUDIO_EXT:
                ref = a.with_suffix(".txt")
                pairs.append((a, ref if ref.exists() else None))
    elif args.audio:
        pairs.append((args.audio, args.ref))
    else:
        ap.error("--audio yoki --dir kerak")

    rows = []
    for audio, ref in pairs:
        try:
            res = transcribe(args.server, audio, args)
        except Exception as exc:
            print("  XATO:", exc)
            rows.append({"file": audio.name, "error": str(exc)})
            continue
        row = {"file": audio.name, "duration_s": round(res["duration"], 1), "wall_s": round(res["_wall"], 1),
               "speed_x_realtime": round(res["duration"] / max(0.1, res["_wall"]), 2),
               "words": res["stats"]["words"], "uncertain": res["stats"]["uncertain"], "model": res["model"]}
        if ref:
            w, c = wer_cer(ref.read_text(encoding="utf-8"), res["latin_text"])
            row.update({"WER_%": round(w * 100, 1), "CER_%": round(c * 100, 1)})
        rows.append(row)
        print("  ", row)

    ok = [r for r in rows if "WER_%" in r]
    if ok:
        print(f"\nO‘rtacha WER: {sum(r['WER_%'] for r in ok) / len(ok):.1f}%   "
              f"O‘rtacha CER: {sum(r['CER_%'] for r in ok) / len(ok):.1f}%   ({len(ok)} ta fayl)")
    if args.csv and rows:
        keys = sorted({k for r in rows for k in r})
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        print("CSV:", args.csv)
    return 0 if all("error" not in r for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
