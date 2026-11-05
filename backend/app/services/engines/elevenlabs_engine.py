"""Pullik bulut dvigatel: ElevenLabs Scribe (o'zbek, qirg'iz, qozoq tillarini qo'llaydi).

Faqat .env ichida ELEVENLABS_API_KEY berilganda yoqiladi. Foydalanuvchiga audio tashqi
servisga yuborilishi interfeysda aniq ko'rsatiladi.
"""
from __future__ import annotations

import math
from pathlib import Path

from ..asr_service import BaseEngine, EngineError, EngineOutput, TranscribeRequest
from ..punctuation_service import ends_sentence

API_URL = "https://api.elevenlabs.io/v1/speech-to-text"
ISO3 = {"uz": "uzb", "kk": "kaz", "ky": "kir"}
BACK = {"uzb": "uz", "kaz": "kk", "kir": "ky", "rus": "ru", "eng": "en", "uz": "uz", "kk": "kk",
        "ky": "ky", "ru": "ru", "en": "en"}


class ElevenLabsEngine(BaseEngine):
    name = "elevenlabs"
    supports_chunks = False
    is_cloud = True

    def __init__(self, settings, session=None):
        self.s = settings
        self._session = session

    def available(self) -> tuple[bool, str]:
        if not self.s.elevenlabs_api_key:
            return False, "api_key_missing"
        try:
            import requests  # noqa: F401
        except Exception:
            return False, "requests_not_installed"
        return True, ""

    def _http(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def transcribe(self, audio: Path, req: TranscribeRequest) -> EngineOutput:
        data = {"model_id": self.s.elevenlabs_model, "timestamps_granularity": "word",
                "tag_audio_events": "false", "diarize": "false"}
        if req.user_language in ISO3:
            data["language_code"] = ISO3[req.user_language]
        try:
            with open(audio, "rb") as fh:
                resp = self._http().post(
                    API_URL,
                    headers={"xi-api-key": self.s.elevenlabs_api_key},
                    data=data,
                    files={"file": (Path(audio).name, fh)},
                    timeout=(30, 3 * 3600),
                )
        except Exception as exc:
            raise EngineError("cloud_unreachable", str(exc)[:300]) from exc
        if resp.status_code in (401, 403):
            raise EngineError("cloud_auth_failed", resp.text[:300])
        if resp.status_code == 429:
            raise EngineError("cloud_rate_limited", resp.text[:300])
        if resp.status_code >= 400:
            raise EngineError("cloud_error", f"{resp.status_code}: {resp.text[:300]}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise EngineError("cloud_error", "javob JSON emas") from exc
        return self.parse(payload)

    @staticmethod
    def parse(payload: dict) -> EngineOutput:
        words = []
        for w in payload.get("words") or []:
            if w.get("type", "word") != "word":
                continue
            text = str(w.get("text", "")).strip()
            if not text:
                continue
            lp = w.get("logprob")
            p = None
            if isinstance(lp, (int, float)):
                p = max(0.0, min(1.0, math.exp(lp)))
            words.append({"w": text, "s": float(w.get("start") or 0), "e": float(w.get("end") or 0), "p": p})

        segments, cur = [], []
        for w in words:
            if cur and (w["s"] - cur[-1]["e"] > 1.2 or len(cur) >= 40):
                segments.append(cur)
                cur = []
            cur.append(w)
            if ends_sentence(w["w"]) and len(cur) >= 6:
                segments.append(cur)
                cur = []
        if cur:
            segments.append(cur)
        out = EngineOutput(
            language=BACK.get(str(payload.get("language_code", "")).lower()),
            language_probability=payload.get("language_probability"),
        )
        for seg in segments:
            out.segments.append({"start": seg[0]["s"], "end": seg[-1]["e"],
                                 "text": " ".join(x["w"] for x in seg), "words": seg})
        if not out.segments and payload.get("text"):
            out.segments.append({"start": 0.0, "end": 0.0, "text": payload["text"], "words": []})
        return out
