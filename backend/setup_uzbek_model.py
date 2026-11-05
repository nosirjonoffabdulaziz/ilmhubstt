"""O'zbekcha uchun maxsus modelni o'rnatish (bir martalik).

Oddiy Whisper o'zbek tilini yomon taniydi. Bu skript o'zbekchaga fine-tune qilingan
ochiq modelni (standart: islomov/rubaistt_v2_medium, Apache-2.0) yuklab oladi,
faster-whisper (CTranslate2) formatiga o'giradi va .env ga WHISPER_MODEL_UZ qilib yozadi.

  cd backend
  .venv\\Scripts\\python.exe setup_uzbek_model.py

Boshqa model:  .venv\\Scripts\\python.exe setup_uzbek_model.py --repo Kotib/uzbek_stt_v1
Kerak bo'ladi: internet (~1.5 GB model + ~0.3 GB torch CPU), diskda ~4 GB bo'sh joy.
"""
from __future__ import annotations

import argparse
import importlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from app.config import PROJECT_DIR, load_settings, set_env_value  # noqa: E402,F401

DEFAULT_REPO = "islomov/rubaistt_v2_medium"
COPY_CANDIDATES = ["tokenizer.json", "preprocessor_config.json"]


def step(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def pip_install(*args: str) -> None:
    cmd = [sys.executable, "-m", "pip", "install", *args]
    print("   ", " ".join(cmd), flush=True)
    subprocess.check_call(cmd)


def ensure_converter_deps() -> None:
    missing = []
    for mod in ("torch", "transformers"):
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(mod)
    if not missing:
        return
    step("Konvertatsiya uchun kutubxonalar o'rnatilmoqda (bir martalik): " + ", ".join(missing))
    if "torch" in missing:
        pip_install("torch", "--index-url", "https://download.pytorch.org/whl/cpu")
    if "transformers" in missing:
        pip_install("transformers>=4.40,<5")
    importlib.invalidate_caches()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO, help="Hugging Face'dagi Whisper fine-tune modeli")
    ap.add_argument("--lang", default="uz", choices=["uz", "kk", "ky"])
    ap.add_argument("--quantization", default="int8_float16", help="int8_float16 (CPU+GPU), int8, float16")
    ap.add_argument("--force", action="store_true", help="avvalgi konvertatsiyani o'chirib qayta qilish")
    args = ap.parse_args()

    settings = load_settings()
    models = settings.model_dir
    models.mkdir(parents=True, exist_ok=True)
    name = args.repo.split("/")[-1].replace("_", "-") + "-ct2"
    out_dir = models / name

    if (out_dir / "model.bin").exists() and not args.force:
        step(f"Model allaqachon tayyor: {out_dir}")
    else:
        try:
            import ctranslate2  # noqa: F401
            from huggingface_hub import snapshot_download
        except Exception as exc:
            print("faster-whisper o'rnatilmagan. Avval: .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
            print(exc)
            return 1
        ensure_converter_deps()

        step(f"Model yuklab olinmoqda: {args.repo} (~1.5 GB, internet tezligiga bog'liq)")
        t0 = time.time()
        src = snapshot_download(args.repo, cache_dir=str(models / "hf-src"),
                                allow_patterns=["*.json", "*.safetensors", "*.bin", "*.txt", "*.model"])
        print(f"    Yuklandi: {src}  ({time.time() - t0:.0f} s)")

        step(f"faster-whisper formatiga o'girilmoqda ({args.quantization})")
        from ctranslate2.converters import TransformersConverter
        copy = [f for f in COPY_CANDIDATES if (Path(src) / f).exists()]
        tmp = out_dir.with_name(out_dir.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        TransformersConverter(src, copy_files=copy or None).convert(str(tmp), quantization=args.quantization, force=True)
        if not (tmp / "tokenizer.json").exists():
            from transformers import WhisperTokenizerFast
            WhisperTokenizerFast.from_pretrained(src).save_pretrained(str(tmp))
        shutil.rmtree(out_dir, ignore_errors=True)
        tmp.replace(out_dir)
        print(f"    Tayyor: {out_dir}")
        shutil.rmtree(models / "hf-src", ignore_errors=True)  # asl (katta) fayllar endi kerak emas

    step("Model sinab ko'rilmoqda")
    import numpy as np
    from faster_whisper import WhisperModel
    m = WhisperModel(str(out_dir), device="cpu", compute_type="int8")
    segs, info = m.transcribe(np.zeros(16000, dtype=np.float32), language=args.lang, vad_filter=False)
    list(segs)
    print("    [OK] model yuklanadi va ishlaydi")

    env_path = PROJECT_DIR / ".env"
    if not env_path.exists() and (PROJECT_DIR / ".env.example").exists():
        shutil.copy(PROJECT_DIR / ".env.example", env_path)
    set_env_value(env_path, f"WHISPER_MODEL_{args.lang.upper()}", str(out_dir))
    step(f".env yangilandi: WHISPER_MODEL_{args.lang.upper()}={out_dir}")
    print("\nTAYYOR. Serverni qayta ishga tushiring:  .venv\\Scripts\\python.exe run.py")
    print("O'zbek tili tanlanganda endi shu maxsus model ishlatiladi.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print("\n[XATO] pip o'rnatish muvaffaqiyatsiz:", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nTo'xtatildi. Qayta ishga tushirsangiz, yuklash davom etadi.")
        sys.exit(130)
