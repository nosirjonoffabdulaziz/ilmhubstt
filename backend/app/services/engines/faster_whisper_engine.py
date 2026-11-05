"""Lokal, tekin dvigatel: faster-whisper (CTranslate2). CPU uchun int8, GPU uchun float16.

Model birinchi ishlatilganda internetdan yuklanadi va MODEL_DIR ichida keshlanadi.
Yuklash jarayoni (MB, tezlik) ish holatida ko'rsatiladi.

GPU: WHISPER_DEVICE=auto bo'lsa, NVIDIA GPU avval ALOHIDA jarayonda sinab ko'riladi
(Windows'da cuBLAS/cuDNN yo'q bo'lsa, CTranslate2 butun jarayonni yopib qo'yishi mumkin).
Sinov o'tmasa, avtomatik CPU (int8) ishlatiladi.
"""
from __future__ import annotations

import inspect
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

from ..asr_service import BaseEngine, EngineError, EngineOutput, TranscribeRequest
from .cuda_dll import add_nvidia_dll_dirs

log = logging.getLogger("ilmhubstt.asr")

# Taxminiy hajmlar (MB) — yuklash foizini ko'rsatish uchun
MODEL_SIZES_MB = {
    "tiny": 75, "base": 145, "small": 484, "medium": 1530, "large-v1": 3090, "large-v2": 3090,
    "large-v3": 3090, "large": 3090, "large-v3-turbo": 1620, "turbo": 1620, "distil-large-v3": 1510,
}
BACKEND_DIR = Path(__file__).resolve().parents[3]


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


class FasterWhisperEngine(BaseEngine):
    name = "faster-whisper"
    supports_chunks = True

    def __init__(self, settings):
        self.s = settings
        self._models: dict[tuple, object] = {}
        self._paths: dict[str, str] = {}
        self._lock = threading.Lock()
        self._cuda_ok: bool | None = None
        # hf-xet ba'zi Windows tizimlarida osilib qoladi va progress bermaydi: oddiy HTTP yuklash ishonchliroq
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

    # ---------- holat ----------
    def available(self) -> tuple[bool, str]:
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            return False, "faster_whisper_not_installed"
        return True, ""

    def describe(self) -> dict:
        d = super().describe()
        d["models"] = dict(self.s.whisper_models)
        d["device"] = self.s.whisper_device
        d["cuda_ok"] = self._cuda_ok
        d["language_models"] = {lang: os.path.basename(str(m).rstrip("/\\")) or str(m)
                                for lang, m in self.s.whisper_model_overrides.items()}
        return d

    def _compute(self, device: str) -> str:
        compute = self.s.whisper_compute_type.lower()
        if compute == "auto":
            compute = "float16" if device == "cuda" else "int8"
        return compute

    def _device(self) -> tuple[str, str]:
        device = self.s.whisper_device.lower()
        if device == "auto":
            device = "cuda" if self._cuda_ok else "cpu"
        return device, self._compute(device)

    def model_name(self, quality: str, user_language: str) -> str:
        if user_language in self.s.whisper_model_overrides:
            return self.s.whisper_model_overrides[user_language]
        return self.s.whisper_models.get(quality) or self.s.whisper_models["balanced"]

    # ---------- model yuklab olish ----------
    def ensure_model(self, name: str, on_status=None) -> str:
        """Model fayllari diskda bo'lishini ta'minlaydi va mahalliy yo'lni qaytaradi."""
        if name in self._paths:
            return self._paths[name]
        if os.path.isdir(name):
            self._paths[name] = name
            return name
        try:
            from faster_whisper.utils import download_model
        except Exception:
            return name  # eski/soxta versiya: WhisperModel o'zi yuklaydi
        cache = self.s.model_dir
        cache.mkdir(parents=True, exist_ok=True)
        try:
            path = download_model(name, cache_dir=str(cache), local_files_only=True)
            self._paths[name] = path
            return path
        except Exception:
            pass  # keshda yo'q -> internetdan yuklaymiz

        total = MODEL_SIZES_MB.get(name.split("/")[-1].replace("faster-whisper-", ""), 0) * 1024 * 1024
        before = _dir_size(cache)
        stop = threading.Event()
        log.info("Model internetdan yuklanmoqda: %s (~%d MB). Bu bir martalik.", name, total // 1048576)

        def watch():
            t0, last_b, last_t, speed = time.time(), 0, time.time(), 0.0
            while not stop.wait(1.5):
                done = max(0, _dir_size(cache) - before)
                now = time.time()
                inst = (done - last_b) / max(0.1, now - last_t)
                speed = inst if speed == 0 else speed * 0.7 + inst * 0.3
                last_b, last_t = done, now
                eta = (total - done) / speed if total and speed > 1024 else None
                if on_status:
                    on_status("downloading_model", {"model": name, "done_mb": round(done / 1048576, 1),
                                                    "total_mb": round(total / 1048576) if total else None,
                                                    "speed_mbs": round(speed / 1048576, 2),
                                                    "eta": None if eta is None else int(eta),
                                                    "elapsed": int(now - t0)})

        if on_status:
            on_status("downloading_model", {"model": name, "done_mb": 0, "total_mb": round(total / 1048576) if total else None,
                                            "speed_mbs": 0, "eta": None, "elapsed": 0})
        th = threading.Thread(target=watch, daemon=True)
        th.start()
        try:
            path = download_model(name, cache_dir=str(cache))
        except Exception as exc:
            raise EngineError("model_download_failed", str(exc)[:300]) from exc
        finally:
            stop.set()
            th.join(timeout=3)
        log.info("Model yuklab olindi: %s", path)
        self._paths[name] = path
        return path

    # ---------- GPU tekshiruvi ----------
    def _check_cuda(self, model_path: str, on_status=None) -> bool:
        if self._cuda_ok is not None:
            return self._cuda_ok
        try:
            import ctranslate2
            add_nvidia_dll_dirs()
            count = ctranslate2.get_cuda_device_count()
        except Exception:
            count = 0
        if count <= 0:
            self._cuda_ok = False
            return False
        if on_status:
            on_status("checking_gpu", {})
        cmd = [sys.executable, "-m", "app.services.engines.cuda_check", model_path, self._compute("cuda")]
        kw = {}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        try:
            res = subprocess.run(cmd, cwd=str(BACKEND_DIR), capture_output=True, text=True, timeout=300, **kw)
            ok = res.returncode == 0 and "CUDA_OK" in res.stdout
            if not ok:
                tail = (res.stderr or res.stdout or "").strip().splitlines()[-3:]
                log.warning("GPU (CUDA) ishlamadi, CPU ishlatiladi. Sabab: %s", " | ".join(tail) or res.returncode)
        except Exception as exc:
            ok = False
            log.warning("GPU tekshiruvi muvaffaqiyatsiz (%s), CPU ishlatiladi", exc)
        self._cuda_ok = ok
        if ok:
            log.info("GPU (CUDA) ishlayapti — tezlashtirilgan rejim")
        return ok

    def _load(self, name: str, on_status=None):
        path = self.ensure_model(name, on_status)
        if self.s.whisper_device.lower() == "auto" and self._cuda_ok is None:
            self._check_cuda(path, on_status)
        device, compute = self._device()
        key = (path, device, compute)
        with self._lock:
            if key in self._models:
                return self._models[key]
            try:
                from faster_whisper import WhisperModel
            except Exception as exc:
                raise EngineError("engine_not_installed", str(exc)) from exc
            if device == "cuda":
                add_nvidia_dll_dirs()
            if on_status:
                on_status("loading_model", {"model": name, "device": device})
            log.info("Model ishga tushirilmoqda: %s (%s, %s)", name, device, compute)
            try:
                model = WhisperModel(path, device=device, compute_type=compute,
                                     cpu_threads=self.s.whisper_cpu_threads,
                                     download_root=str(self.s.model_dir))
            except MemoryError as exc:
                raise EngineError("out_of_memory", str(exc)) from exc
            except Exception as exc:
                msg = str(exc)
                code = "out_of_memory" if "memory" in msg.lower() or "bad_alloc" in msg else "model_load_failed"
                raise EngineError(code, msg[:300]) from exc
            # Bir vaqtda faqat bitta model xotirada turadi (RAM tejash)
            self._models.clear()
            self._models[key] = model
            return model

    # ---------- transkripsiya ----------
    def transcribe(self, audio: np.ndarray, req: TranscribeRequest) -> EngineOutput:
        model = self._load(self.model_name(req.quality, req.user_language), req.on_status)
        if req.on_status:
            req.on_status("transcribing", {})
        kwargs = dict(
            language=req.language,
            task="transcribe",
            beam_size=self.s.whisper_beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 300},
            word_timestamps=True,
            condition_on_previous_text=False,  # uzun audioda "aylanib qolish"ni kamaytiradi
            initial_prompt=req.prompt,
            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
            hallucination_silence_threshold=2.0,
            hotwords=", ".join(req.terms) if req.terms else None,
        )
        try:
            params = inspect.signature(model.transcribe).parameters
            kwargs = {k: v for k, v in kwargs.items() if k in params}
        except (TypeError, ValueError):
            pass
        try:
            segments_iter, info = model.transcribe(audio, **kwargs)
            out = EngineOutput(language=getattr(info, "language", None),
                               language_probability=getattr(info, "language_probability", None))
            for seg in segments_iter:
                if req.cancelled and req.cancelled():
                    break
                words = [
                    {"w": w.word, "s": float(w.start) + req.offset, "e": float(w.end) + req.offset,
                     "p": float(w.probability)}
                    for w in (getattr(seg, "words", None) or [])
                ]
                out.segments.append({
                    "start": float(seg.start) + req.offset,
                    "end": float(seg.end) + req.offset,
                    "text": seg.text,
                    "words": words,
                    "avg_logprob": float(getattr(seg, "avg_logprob", 0.0)),
                    "no_speech_prob": float(getattr(seg, "no_speech_prob", 0.0)),
                    "compression_ratio": float(getattr(seg, "compression_ratio", 1.0)),
                })
                if req.on_progress:
                    req.on_progress(float(seg.end))
            return out
        except EngineError:
            raise
        except MemoryError as exc:
            raise EngineError("out_of_memory", str(exc)) from exc
        except Exception as exc:
            msg = str(exc)
            code = "out_of_memory" if "memory" in msg.lower() or "bad_alloc" in msg else "engine_error"
            raise EngineError(code, msg[:300]) from exc
