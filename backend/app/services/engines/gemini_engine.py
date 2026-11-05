"""Bulut dvigateli: Google Gemini API (bepul yoki pullik kalit bilan).

Uzun audio ~10 daqiqalik bo'laklarga bo'linadi (worker), har bo'lak Opus/Ogg qilib siqiladi va
inline yuboriladi. Gemini'dan vaqt belgili JSON segmentlar so'raladi. 429 (limit) va 5xx xatolarida
kutib qayta uriniladi; model topilmasa zaxira modelga o'tiladi. Sarflangan tokenlar va taxminiy narx hisoblanadi.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

from ..asr_service import BaseEngine, EngineError, EngineOutput, TranscribeRequest

log = logging.getLogger("ilmhubstt.gemini")

DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"
# USD / 1M token (audio kirish, chiqish) — taxminiy, .env orqali o'zgartirish mumkin
PRICES = {
    "gemini-3-flash": (1.00, 3.00), "gemini-3.1-flash-lite": (0.50, 1.50), "gemini-2.5-flash-lite": (0.30, 0.40),
    "gemini-2.5-flash": (1.00, 2.50), "gemini-2.5-pro": (1.25, 10.0), "gemini-3-pro": (2.0, 12.0),
}
LANG_NAMES = {"uz": "o‘zbek", "kk": "qozoq", "ky": "qirg‘iz"}

SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "start": {"type": "STRING", "description": "segment boshi, MM:SS.s"},
            "end": {"type": "STRING", "description": "segment oxiri, MM:SS.s"},
            "text": {"type": "STRING"},
        },
        "required": ["start", "end", "text"],
    },
}


def build_prompt(lang: str, mode: str, terms: list[str]) -> str:
    if lang in ("uz", None, "", "auto"):
        target = ("Audio o‘zbek tilida (ba’zan qirg‘iz yoki qozoq bo‘lishi mumkin). O‘zbekcha nutqni o‘zbek lotin "
                  "alifbosining rasmiy imlosida yoz: o‘ va g‘ uchun ‘ belgisi, tutuq uchun ’ belgisi (ta’til, ma’no).")
        if lang in ("auto", None, ""):
            target += " Agar audio qozoq yoki qirg‘iz tilida bo‘lsa, o‘sha tilning kirill yozuvida yoz."
    else:
        target = (f"Audio {LANG_NAMES.get(lang, lang)} tilida. Nutqni shu tilning rasmiy kirill yozuvida, "
                  "imlo qoidalariga muvofiq yoz.")
    style = ("Toza matn: «ee», «mm» kabi to‘ldiruvchi tovushlarni va keraksiz takrorlarni yozma."
             if mode == "clean" else "So‘zma-so‘z: har bir aytilgan so‘z va tovushni saqla.")
    lines = [
        "Sen professional transkripsiya mutaxassisisan. Berilgan audioni BOSHIDAN OXIRIGACHA to‘liq matnga aylantir.",
        target,
        style,
        "To‘g‘ri tinish belgilari (. , ? ! :) va bosh harflarni qo‘y. Raqamlarni raqam bilan yoz (2025-yil, 340 nafar).",
        "Tarjima QILMA, qisqartirma, xulosa yozma, o‘zingdan so‘z qo‘shma. Eshitilmagan joyni [eshitilmadi] deb yoz.",
        "Natijani JSON massiv qilib qaytar: har bir element bitta gap yoki qisqa fikr (5–25 soniya): "
        "{\"start\": \"MM:SS.s\", \"end\": \"MM:SS.s\", \"text\": \"...\"}. Vaqtlar shu audio boshidan hisoblanadi.",
    ]
    if terms:
        lines.append("Bu ism va atamalarni aynan shunday yoz: " + ", ".join(terms) + ".")
    return "\n".join(lines)


_TIME = re.compile(r"^\s*(?:(\d+):)?(\d+):(\d+(?:[.,]\d+)?)\s*$")


def parse_time(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    try:
        return float(s.replace(",", "."))
    except ValueError:
        pass
    m = _TIME.match(s)
    if not m:
        return None
    h = int(m.group(1) or 0)
    return h * 3600 + int(m.group(2)) * 60 + float(m.group(3).replace(",", "."))


def parse_segments(raw: str, duration: float) -> list[dict]:
    """Gemini JSON javobini xavfsiz segmentlarga aylantirish (vaqtlar 0..duration ichida, o'suvchi)."""
    txt = raw.strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", txt)
    try:
        data = json.loads(txt)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", txt, re.S)
        if not m:
            return [{"start": 0.0, "end": duration, "text": txt}] if txt else []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return [{"start": 0.0, "end": duration, "text": txt}]
    if isinstance(data, dict):
        data = data.get("segments") or data.get("items") or [data]
    items = []
    for it in data if isinstance(data, list) else []:
        if not isinstance(it, dict):
            continue
        text = " ".join(str(it.get("text", "")).split())
        if not text:
            continue
        items.append({"s": parse_time(it.get("start")), "e": parse_time(it.get("end")), "text": text})
    if not items:
        return []
    # vaqtlarni tekshirish: yo'q yoki noto'g'ri bo'lsa matn uzunligi bo'yicha taqsimlash
    bad = sum(1 for x in items if x["s"] is None or x["s"] < 0 or x["s"] > duration + 2)
    ordered = all((a["s"] or 0) <= (b["s"] or 0) for a, b in zip(items, items[1:]))
    if bad > len(items) * 0.3 or not ordered:
        total = sum(len(x["text"]) for x in items) or 1
        t = 0.0
        for x in items:
            d = duration * len(x["text"]) / total
            x["s"], x["e"] = t, t + d
            t += d
    out = []
    for i, x in enumerate(items):
        s = max(0.0, min(duration, x["s"] if x["s"] is not None else (out[-1]["end"] if out else 0.0)))
        nxt = items[i + 1]["s"] if i + 1 < len(items) and items[i + 1]["s"] is not None else duration
        e = x["e"] if x["e"] is not None and x["e"] > s else min(duration, max(s + 0.5, nxt))
        e = max(s + 0.2, min(duration, e))
        if out and s < out[-1]["start"]:
            s = out[-1]["start"]
        out.append({"start": round(s, 2), "end": round(e, 2), "text": x["text"]})
    return out


class GeminiEngine(BaseEngine):
    name = "gemini"
    supports_chunks = True
    is_cloud = True

    def __init__(self, settings, session=None):
        self.s = settings
        self._session = session
        self._lock = threading.Lock()
        self._models_cache: tuple[float, str, list[str]] | None = None
        self.usage = {"input": 0, "output": 0}

    # ---------- holat ----------
    @property
    def key(self) -> str:
        return (self.s.gemini_api_key or "").strip()

    @property
    def base(self) -> str:
        return (self.s.gemini_base_url or DEFAULT_BASE).rstrip("/")

    def available(self) -> tuple[bool, str]:
        if not self.key:
            return False, "api_key_missing"
        try:
            import requests  # noqa: F401
        except Exception:
            return False, "requests_not_installed"
        return True, ""

    def describe(self) -> dict:
        d = super().describe()
        d["model"] = self.s.gemini_model
        d["key_set"] = bool(self.key)
        d["key_hint"] = ("…" + self.key[-4:]) if self.key else ""
        return d

    def _http(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def _headers(self, key: str | None = None) -> dict:
        return {"x-goog-api-key": key or self.key, "Content-Type": "application/json"}

    def check_key(self, key: str) -> tuple[bool, str, list[str]]:
        """Kalitni tekshirish: modellar ro'yxatini olish. (ok, xato kodi, modellar)"""
        try:
            r = self._http().get(f"{self.base}/models?pageSize=200", headers=self._headers(key), timeout=20)
        except Exception as exc:
            return False, "cloud_unreachable", [str(exc)[:200]]
        if r.status_code in (400, 401, 403):
            try:
                err = r.json().get("error", {})
                msg = str(err.get("message", ""))
                blob = json.dumps(err)
            except ValueError:
                msg, blob = r.text[:300], r.text[:2000]
            if "SERVICE_DISABLED" in blob or "has not been used" in msg or "is disabled" in msg:
                return False, "cloud_api_disabled", [msg]
            if "location" in msg.lower() or "region" in msg.lower():
                return False, "cloud_region", [msg]
            if "API_KEY_SERVICE_BLOCKED" in blob or "blocked" in msg.lower():
                return False, "cloud_key_restricted", [msg]
            return False, "cloud_auth_failed", [msg]
        if r.status_code >= 400:
            return False, "cloud_error", [f"{r.status_code}"]
        try:
            models = [m.get("name", "").replace("models/", "") for m in r.json().get("models", [])]
        except ValueError:
            models = []
        return True, "", models

    def _model_candidates(self) -> list[str]:
        prefs = [self.s.gemini_model] + [m for m in self.s.gemini_fallback_models if m != self.s.gemini_model]
        now = time.time()
        if not self._models_cache or now - self._models_cache[0] > 3600 or self._models_cache[1] != self.key:
            ok, _, models = self.check_key(self.key)
            self._models_cache = (now, self.key, models if ok else [])
        models = self._models_cache[2]
        if not models:
            return prefs
        chosen = [m for m in prefs if m in models]
        if not chosen:
            # nomi o'zgargan bo'lsa: eng yangi "flash" modelini tanlash
            flash = sorted([m for m in models if "flash" in m and "tts" not in m and "image" not in m
                            and "live" not in m and "embedding" not in m], reverse=True)
            chosen = flash[:1]
        return chosen or prefs

    # ---------- transkripsiya ----------
    def _encode(self, audio: np.ndarray) -> tuple[bytes, str]:
        from .. import ffmpeg_service as ff
        tmpdir = Path(tempfile.mkdtemp(prefix="stt-gem-", dir=str(self.s.data_dir)))
        try:
            wav = tmpdir / "c.wav"
            pcm = np.clip(audio, -1.0, 1.0)
            with wave.open(str(wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes((pcm * 32767).astype("<i2").tobytes())
            out = ff.encode_for_cloud(wav, tmpdir / "c.ogg")
            mime = "audio/ogg" if out.suffix == ".ogg" else "audio/flac"
            return out.read_bytes(), mime
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _body(self, model: str, b64: str, mime: str, prompt: str, thinking: bool) -> dict:
        gen: dict = {"responseMimeType": "application/json", "responseSchema": SCHEMA, "maxOutputTokens": 32768}
        if thinking:
            if model.startswith("gemini-2.5"):
                gen["thinkingConfig"] = {"thinkingBudget": 0 if "flash" in model else 128}
            elif model.startswith("gemini-3"):
                gen["thinkingConfig"] = {"thinkingLevel": "low"}
        if model.startswith("gemini-2"):
            gen["temperature"] = 0.2
        return {
            "contents": [{"role": "user", "parts": [{"inline_data": {"mime_type": mime, "data": b64}},
                                                   {"text": prompt}]}],
            "generationConfig": gen,
        }

    def _retry_delay(self, resp, attempt: int) -> float:
        try:
            for d in resp.json().get("error", {}).get("details", []):
                rd = d.get("retryDelay")
                if rd:
                    return min(120.0, float(str(rd).rstrip("s")) + 1)
        except Exception:
            pass
        return min(90.0, 5.0 * (2 ** attempt))

    def transcribe(self, audio: np.ndarray, req: TranscribeRequest) -> EngineOutput:
        if not self.key:
            raise EngineError("cloud_auth_failed", "GEMINI_API_KEY yo'q")
        duration = len(audio) / 16000.0
        data, mime = self._encode(audio)
        b64 = base64.b64encode(data).decode("ascii")
        prompt = build_prompt(req.user_language, req.mode or "clean", req.terms)
        models = self._model_candidates()
        last_err: EngineError | None = None
        for model in models:
            thinking = True
            attempt = 0
            waited = 0.0
            while True:
                if req.cancelled and req.cancelled():
                    return EngineOutput(segments=[], language=req.language)
                try:
                    resp = self._http().post(f"{self.base}/models/{model}:generateContent",
                                             headers=self._headers(), data=json.dumps(self._body(model, b64, mime,
                                                                                                prompt, thinking)),
                                             timeout=(30, 900))
                except Exception as exc:
                    attempt += 1
                    if attempt > 4:
                        raise EngineError("cloud_unreachable", str(exc)[:300]) from exc
                    time.sleep(min(30, 3 * attempt))
                    continue
                code = resp.status_code
                if code == 200:
                    return self._parse(resp, model, duration, req)
                text = resp.text[:500]
                if code == 400 and thinking and "thinking" in text.lower():
                    thinking = False
                    continue
                if code in (400, 401, 403) and ("API_KEY" in text or "PERMISSION" in text or code != 400):
                    if "location" in text.lower() or "region" in text.lower():
                        raise EngineError("cloud_region", text)
                    raise EngineError("cloud_auth_failed", text)
                if code == 404:
                    last_err = EngineError("cloud_model_not_found", f"{model}: {text}")
                    break
                if code == 429 or code >= 500:
                    attempt += 1
                    delay = self._retry_delay(resp, attempt)
                    waited += delay
                    limit = self.s.gemini_max_wait
                    if waited > limit:
                        raise EngineError("cloud_rate_limited" if code == 429 else "cloud_error", text)
                    if req.on_status:
                        req.on_status("rate_limited_wait" if code == 429 else "cloud_retry",
                                      {"wait": int(delay), "attempt": attempt, "model": model})
                    log.warning("Gemini %s (%s), %.0f s kutib qayta urinish", code, model, delay)
                    t_end = time.time() + delay
                    while time.time() < t_end:
                        if req.cancelled and req.cancelled():
                            return EngineOutput(segments=[], language=req.language)
                        time.sleep(0.5)
                    if req.on_status:
                        req.on_status("transcribing", {"model": model})
                    continue
                raise EngineError("cloud_error", f"{code}: {text}")
        raise last_err or EngineError("cloud_model_not_found")

    def _parse(self, resp, model: str, duration: float, req: TranscribeRequest) -> EngineOutput:
        try:
            payload = resp.json()
        except ValueError as exc:
            raise EngineError("cloud_error", "javob JSON emas") from exc
        um = payload.get("usageMetadata") or {}
        inp = int(um.get("promptTokenCount") or 0)
        outp = int(um.get("candidatesTokenCount") or 0) + int(um.get("thoughtsTokenCount") or 0)
        with self._lock:
            self.usage["input"] += inp
            self.usage["output"] += outp
        cands = payload.get("candidates") or []
        if not cands:
            reason = (payload.get("promptFeedback") or {}).get("blockReason", "empty")
            raise EngineError("cloud_blocked", str(reason))
        parts = (cands[0].get("content") or {}).get("parts") or []
        raw = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        segs = parse_segments(raw, duration)
        out = EngineOutput(language=req.language)
        out.meta = {"model": model, "input_tokens": inp, "output_tokens": outp,  # type: ignore[attr-defined]
                    "finish": cands[0].get("finishReason")}
        for sg in segs:
            out.segments.append({"start": sg["start"] + req.offset, "end": sg["end"] + req.offset,
                                 "text": sg["text"], "words": []})
        if req.on_progress:
            req.on_progress(duration)
        return out


def price_for(model: str, settings) -> tuple[float, float]:
    if settings.gemini_price_in > 0 or settings.gemini_price_out > 0:
        return settings.gemini_price_in, settings.gemini_price_out
    for prefix, p in sorted(PRICES.items(), key=lambda kv: -len(kv[0])):
        if model.startswith(prefix):
            return p
    return PRICES["gemini-3-flash"]


def estimate_cost(model: str, inp: int, outp: int, settings) -> float:
    pi, po = price_for(model, settings)
    return round(inp / 1e6 * pi + outp / 1e6 * po, 4)

