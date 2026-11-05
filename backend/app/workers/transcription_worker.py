"""Fon ishchisi: navbatdagi ishlarni ketma-ket bajaradi.

Bosqichlar: queued -> converting -> transcribing -> normalizing -> completed | failed | cancelled.
Progress faqat haqiqiy bosqichlardan hisoblanadi: konvertatsiya 0–5%, tanish 5–95% (qayta ishlangan
audio soniyalari bo'yicha), normallashtirish 95–99%, tugadi 100%.
Har bir bo'lak natijasi diskka yoziladi: server o'chib qolsa ish shu joydan davom etadi.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import traceback
from pathlib import Path

from ..services import ffmpeg_service as ff
from ..services.asr_service import EngineError, TranscribeRequest
from ..services.chunking import Chunk, keep_words, plan_chunks
from ..services.language_service import build_prompt, vocabulary_terms, whisper_language
from ..services.text_pipeline import build_result

log = logging.getLogger("ilmhubstt.worker")

P_CONVERT = (0.0, 5.0)
P_ASR = (5.0, 95.0)
P_NORM = (95.0, 99.0)


class JobCancelled(Exception):
    pass


def write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class TranscriptionWorker:
    def __init__(self, repo, engines: dict, settings):
        self.repo = repo
        self.engines = engines
        self.s = settings
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads: list[threading.Thread] = []
        self.proofreader = None

    # ---------- boshqaruv ----------
    def start(self) -> None:
        for i in range(self.s.workers):
            t = threading.Thread(target=self._loop, name=f"stt-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        c = threading.Thread(target=self._cleanup_loop, name="stt-cleanup", daemon=True)
        c.start()
        self._threads.append(c)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        for t in self._threads:
            t.join(timeout=5)

    def notify(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.repo.claim_next()
            if job is None:
                self._wake.wait(timeout=2.0)
                self._wake.clear()
                continue
            self.process(job)

    def _cleanup_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.cleanup()
            except Exception:
                log.exception("Tozalashda xato")
            self._stop.wait(timeout=600)

    def cleanup(self) -> int:
        cutoff = time.time() - self.s.retention_hours * 3600
        ids = self.repo.expired(cutoff)
        for job_id in ids:
            self.repo.delete(job_id)
        # Bazada yozuvi yo'q yetim papkalar (masalan, yuklash uzilib qolgan)
        known_cutoff = time.time() - 3600
        for d in self.repo.jobs_dir.iterdir() if self.repo.jobs_dir.exists() else []:
            if d.is_dir() and self.repo.get(d.name) is None and d.stat().st_mtime < known_cutoff:
                import shutil
                shutil.rmtree(d, ignore_errors=True)
        if ids:
            log.info("Muddati o'tgan %d ta ish o'chirildi", len(ids))
        return len(ids)

    # ---------- bitta ish ----------
    def _cancel_check(self, job_id: str):
        last = {"t": 0.0, "v": False}

        def check() -> bool:
            now = time.time()
            if now - last["t"] > 0.5:
                job = self.repo.get(job_id)
                last["v"] = bool(job is None or job["cancel_requested"])
                last["t"] = now
            return last["v"]
        return check

    def process(self, job: dict) -> None:
        job_id = job["id"]
        jdir = self.repo.job_dir(job_id)
        cancelled = self._cancel_check(job_id)
        t0 = time.time()
        try:
            self._run(job, jdir, cancelled)
            log.info("Ish %s tayyor (%.1f s)", job_id[:8], time.time() - t0)
        except (JobCancelled, ff.Cancelled):
            if self.repo.get(job_id):
                self.repo.update(job_id, status="cancelled", stage="cancelled", finished_at=time.time(),
                                 eta_seconds=None)
            log.info("Ish %s bekor qilindi", job_id[:8])
        except (EngineError, ff.MediaError) as exc:
            log.warning("Ish %s xato: %s", job_id[:8], exc.code)
            if self.repo.get(job_id):
                self.repo.update(job_id, status="failed", stage="failed", error_code=exc.code,
                                 error_message=str(exc)[:500], finished_at=time.time(), eta_seconds=None)
        except Exception as exc:  # kutilmagan xato — tafsilot logda, foydalanuvchiga umumiy kod
            log.error("Ish %s kutilmagan xato: %s\n%s", job_id[:8], exc, traceback.format_exc())
            if self.repo.get(job_id):
                self.repo.update(job_id, status="failed", stage="failed", error_code="internal_error",
                                 error_message=str(exc)[:300], finished_at=time.time(), eta_seconds=None)

    def _set_progress(self, job_id: str, value: float, **extra) -> None:
        self.repo.update(job_id, progress=round(min(99.0, max(0.0, value)), 1), **extra)

    def _run(self, job: dict, jdir: Path, cancelled) -> None:
        job_id = job["id"]
        opts = job["options"]
        engine = self.engines.get(opts.get("engine"))
        if engine is None:
            raise EngineError("engine_unavailable")
        ok, reason = engine.available()
        if not ok:
            raise EngineError("engine_not_installed" if "installed" in reason else "engine_unavailable", reason)

        wav = jdir / "audio.wav"
        codec, ext, _ = ff.preview_codec()
        preview = jdir / f"preview.{ext}"
        marker = jdir / "converted.ok"
        upload = jdir / "upload.bin"

        # 1) Konvertatsiya
        if not marker.exists():
            self.repo.update(job_id, status="converting", stage="converting")
            if not upload.exists():
                raise ff.MediaError("upload_missing")
            ff.convert(upload, wav, preview, job["duration"],
                       progress=lambda f: self._set_progress(job_id, P_CONVERT[0] + f * (P_CONVERT[1] - P_CONVERT[0])),
                       cancelled=cancelled)
            marker.write_text(preview.name, encoding="utf-8")
            upload.unlink(missing_ok=True)  # asl faylni darhol o'chiramiz (maxfiylik va joy)
        if cancelled():
            raise JobCancelled()
        duration = ff.wav_duration(wav)
        self.repo.update(job_id, duration=duration)

        # 2) Bo'laklar rejasi
        plan_path = jdir / "chunks.json"
        if plan_path.exists():
            chunks = [Chunk(**c) for c in read_json(plan_path)]
        else:
            silences = ff.detect_silences(wav) if engine.supports_chunks else []
            chunks = plan_chunks(duration, silences, target=self.s.chunk_minutes * 60.0) if engine.supports_chunks \
                else [Chunk(0, 0.0, duration, 0.0, duration)]
            write_json(plan_path, [c.to_dict() for c in chunks])

        # 3) Tanish
        self.repo.update(job_id, status="transcribing", stage="transcribing")
        lang_code, warns = whisper_language(opts["language"], self.s.whisper_lang_overrides) \
            if not engine.is_cloud else (opts["language"] if opts["language"] != "auto" else None, [])
        for w in warns:
            self.repo.add_warning(job_id, w)
        terms = vocabulary_terms(opts.get("vocabulary", ""))
        detected_lang, detected_prob = None, None
        clock = {"start": time.time(), "from": 0.0}  # ETA faqat model tayyor bo'lgach hisoblanadi
        done_seconds = 0.0
        all_segments: list[dict] = []
        preview_tail: list[str] = []
        usage: dict = {}

        for idx, ch in enumerate(chunks):
            cpath = jdir / f"chunk_{idx:03d}.json"
            if cpath.exists():
                data = read_json(cpath)
                all_segments.extend(data["segments"])
                detected_lang = detected_lang or data.get("language")
                detected_prob = detected_prob or data.get("language_probability")
                self._add_usage(usage, data.get("meta") or {})
                done_seconds = ch.keep_end
                continue
            if cancelled():
                raise JobCancelled()

            chunk_len = ch.audio_end - ch.audio_start
            base_done = done_seconds

            def on_progress(sec: float, _base=base_done, _len=chunk_len) -> None:
                processed = _base + max(0.0, min(_len, sec))  # sec — bo'lak boshidan hisoblangan
                frac = processed / duration if duration else 0
                elapsed = time.time() - clock["start"]
                gained = processed - clock["from"]
                eta = (elapsed / gained) * (duration - processed) if gained > 5 and elapsed > 2 else None
                self._set_progress(job_id, P_ASR[0] + frac * (P_ASR[1] - P_ASR[0]),
                                   processed_seconds=round(processed, 1),
                                   eta_seconds=None if eta is None else round(eta, 0))

            # Avtomatik rejimda til birinchi bo'lakda aniqlanadi va keyingilarida qat'iy ishlatiladi
            use_lang = lang_code if lang_code else detected_lang
            prompt = build_prompt(use_lang if use_lang else None, opts.get("vocabulary", ""))
            if opts["language"] == "ky" and not engine.is_cloud:
                prompt = build_prompt("ky", opts.get("vocabulary", ""))

            def on_status(stage: str, detail: dict, _jid=job_id, _base=base_done) -> None:
                if stage == "transcribing" and self.repo.get(_jid)["stage"] != "transcribing":
                    clock["start"], clock["from"] = time.time(), _base
                self.repo.update(_jid, stage=stage, detail=detail)

            req = TranscribeRequest(language=use_lang, prompt=prompt, terms=terms, quality=opts.get("quality", "balanced"),
                                    user_language=opts["language"], offset=ch.audio_start,
                                    on_progress=on_progress, cancelled=cancelled, on_status=on_status,
                                    mode=opts.get("mode", "clean"))
            if engine.supports_chunks:
                audio = ff.read_wav(wav, ch.audio_start, ch.audio_end)
                result = engine.transcribe(audio, req)
            else:
                self._set_progress(job_id, P_ASR[0], stage="uploading_cloud")
                cloud_file = ff.encode_for_cloud(wav, jdir / "cloud.ogg")
                try:
                    self.repo.update(job_id, stage="transcribing")
                    result = engine.transcribe(cloud_file, req)
                finally:
                    cloud_file.unlink(missing_ok=True)
            if cancelled():
                raise JobCancelled()

            is_last = idx == len(chunks) - 1
            kept = []
            for seg in result.segments:
                words = keep_words(seg.get("words") or [], ch, is_last) if seg.get("words") else []
                if seg.get("words") and not words:
                    continue
                if not seg.get("words"):
                    mid = (seg["start"] + seg["end"]) / 2
                    if mid < ch.keep_start or (mid >= ch.keep_end and not is_last):
                        continue
                if words:
                    seg = {**seg, "words": words, "start": words[0]["s"], "end": words[-1]["e"],
                           "text": " ".join(str(w["w"]).strip() for w in words)}
                kept.append(seg)
            if detected_lang is None and result.language:
                detected_lang, detected_prob = result.language, result.language_probability
            write_json(cpath, {"segments": kept, "language": result.language,
                               "language_probability": result.language_probability, "meta": result.meta})
            self._add_usage(usage, result.meta)
            all_segments.extend(kept)
            done_seconds = ch.keep_end
            for seg in kept[-3:]:
                preview_tail.append(seg.get("text", "").strip())
            preview_tail = preview_tail[-5:]
            self._set_progress(job_id, P_ASR[0] + (done_seconds / duration) * (P_ASR[1] - P_ASR[0]),
                               processed_seconds=round(done_seconds, 1),
                               preview=[{"t": round(s["start"], 1), "x": s.get("text", "").strip()[:300]}
                                        for s in kept[-5:]])

        # 4) Normallashtirish
        self.repo.update(job_id, status="normalizing", stage="normalizing", progress=P_NORM[0], eta_seconds=None, detail={})
        if opts["language"] == "auto":
            text_lang = detected_lang if detected_lang in ("uz", "kk", "ky") else "uz"
            if detected_lang and detected_lang not in ("uz", "kk", "ky"):
                self.repo.add_warning(job_id, f"detected_other_{detected_lang}")
        else:
            text_lang = opts["language"]
        corrector = None
        if opts.get("spellfix", True) and text_lang == "uz" and opts.get("script", "latin") == "latin":
            from ..services.uz_corrector import Corrector
            from ..services.uz_morph import get_analyzer
            from ..services.language_service import vocabulary_terms as _terms
            corrector = Corrector(get_analyzer(self.s.data_dir / "user_lexicon.txt"),
                                  protected=_terms(opts.get("vocabulary", "")))
        result = build_result(all_segments, opts, text_lang, self.s.uncertain_word_prob, corrector)
        if opts.get("ai_proofread") and result["segments"]:
            self._ai_proofread(job_id, result, text_lang, opts, cancelled)
        result["language"] = opts["language"] if opts["language"] != "auto" else (detected_lang or "auto")
        result["detected_language"] = detected_lang
        result["language_probability"] = detected_prob
        result["duration"] = duration
        result["options"] = opts
        result["model"] = self._model_label(engine, opts, usage)
        if usage.get("input_tokens") or usage.get("output_tokens"):
            from ..services.engines.gemini_engine import estimate_cost
            result["cloud_usage"] = {**usage, "cost_usd": estimate_cost(usage.get("model", ""), usage["input_tokens"],
                                                                        usage["output_tokens"], self.s)}
        result["processing_seconds"] = round(time.time() - (job.get("started_at") or time.time()), 1)
        result["waveform"] = ff.waveform_peaks(wav)
        result["preview_file"] = preview.name
        current = self.repo.get(job_id)
        if current:
            for w in current["warnings"]:
                if w not in result["warnings"]:
                    result["warnings"].append(w)
        if not result["segments"]:
            result["warnings"].append("no_speech_found")
        write_json(jdir / "result.json", result)
        for p in jdir.glob("chunk_*.json"):
            p.unlink(missing_ok=True)
        wav.unlink(missing_ok=True)  # 16 kHz WAV endi kerak emas; pleyer uchun yengil nusxa qoladi
        self.repo.update(job_id, status="completed", stage="completed", progress=100.0, finished_at=time.time(),
                         language=result["language"], language_probability=detected_prob,
                         warnings=result["warnings"], eta_seconds=None)

    def _ai_proofread(self, job_id: str, result: dict, lang: str, opts: dict, cancelled) -> None:
        from ..services.llm_proofread import proofread_segments, rebuild_text
        pr = self.proofreader
        st = pr.status(max_age=0) if pr else {"available": False, "reason": "not_configured"}
        if not st["available"]:
            result["warnings"].append("proofread_unavailable")
            return
        if lang not in ("uz", "kk", "ky") or (lang == "uz" and opts.get("script", "latin") != "latin"):
            return
        self.repo.update(job_id, stage="proofreading", detail={"model": pr.model, "done": 0, "total": 0})

        def prog(done: int, total: int) -> None:
            self.repo.update(job_id, detail={"model": pr.model, "done": done, "total": total},
                             progress=round(P_NORM[0] + (done / max(1, total)) * (P_NORM[1] - P_NORM[0]), 1))

        before = result["latin_text"]
        stats = proofread_segments(pr, result["segments"], lang, opts.get("vocabulary", ""), prog, cancelled)
        if cancelled():
            raise JobCancelled()
        result["pre_ai_text"] = before
        result["latin_text"] = rebuild_text(result["segments"])
        result["edited_text"] = result["latin_text"]
        result["stats"]["ai_changed"] = stats["changed_words"]
        result["stats"]["words"] = sum(len(sg["words"]) for sg in result["segments"])
        result["stats"]["uncertain"] = sum(1 for sg in result["segments"] for w in sg["words"] if w.get("u"))
        result["proofread"] = {"model": pr.model, **stats}
        if stats.get("error"):
            result["warnings"].append("proofread_failed")
        elif stats["rejected"]:
            result["warnings"].append("proofread_partial")

    @staticmethod
    def _add_usage(acc: dict, meta: dict) -> None:
        if not meta:
            return
        acc["input_tokens"] = acc.get("input_tokens", 0) + int(meta.get("input_tokens") or 0)
        acc["output_tokens"] = acc.get("output_tokens", 0) + int(meta.get("output_tokens") or 0)
        if meta.get("model"):
            acc["model"] = meta["model"]

    def _model_label(self, engine, opts, usage=None) -> str:
        if engine.name == "gemini":
            return f"Google {(usage or {}).get('model') or self.s.gemini_model} · cloud"
        if engine.name == "faster-whisper":
            device, compute = engine._device()
            return f"faster-whisper {engine.model_name(opts.get('quality', 'balanced'), opts['language'])} · {compute} · {device.upper()}"
        if engine.name == "elevenlabs":
            return f"ElevenLabs {self.s.elevenlabs_model} · cloud"
        return f"{engine.name} (demo)"
