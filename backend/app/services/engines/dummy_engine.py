"""Test va namoyish dvigateli. Haqiqiy nutqni TANIMAYDI — faqat interfeys va navbatni
model o'rnatilmagan kompyuterda sinash uchun. ENABLE_DUMMY_ENGINE=1 bo'lgandagina yoqiladi.
"""
from __future__ import annotations

import os
import re
import time

import numpy as np

from ..asr_service import BaseEngine, EngineOutput, TranscribeRequest

SAMPLE = [
    "Assalomu alaykum, hurmatli tinglovchilar.",
    "Bugun biz sun’iy intellektning ta’limdagi o‘rni haqida gaplashamiz.",
    "ee Mehmonimiz Samarqand davlat universiteti o‘qituvchisi.",
    "Домла, аввало айтингчи, талабалар бу технологиядан қандай фойдаланишяпти?",
    "Rostini aytsam ko‘pchilik bunday narsalarni uyda o‘rganyapti",
    "Masalan, 2025-yilda fakultetimizda 340 nafar talaba onlayn kursni tamomladi.",
    "Shuning uchun biz o‘qituvchilar uchun alohida trening tashkil qildik.",
]


class DummyEngine(BaseEngine):
    name = "dummy"

    def __init__(self, settings):
        self.s = settings

    def transcribe(self, audio: np.ndarray, req: TranscribeRequest) -> EngineOutput:
        sample = SAMPLE
        path = os.environ.get("DUMMY_TEXT_FILE")
        if path and os.path.exists(path):
            text = open(path, encoding="utf-8").read()
            sample = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()] or SAMPLE
        duration = len(audio) / 16000.0
        out = EngineOutput(language=req.language or "uz", language_probability=0.97)
        t, i = 0.0, int(req.offset // 6)
        step_sleep = 6.0 / self.s.dummy_speed
        while t + 1.0 < duration:
            if req.cancelled and req.cancelled():
                break
            text = sample[i % len(sample)]
            seg_len = min(6.0, duration - t)
            parts = text.split()
            per = seg_len * 0.9 / len(parts)
            words = []
            for k, wtxt in enumerate(parts):
                prob = 0.35 if (i * 7 + k) % 11 == 0 else 0.93
                words.append({"w": wtxt, "s": req.offset + t + k * per, "e": req.offset + t + (k + 1) * per,
                              "p": prob})
            out.segments.append({"start": req.offset + t, "end": req.offset + t + seg_len, "text": text,
                                 "words": words, "avg_logprob": -0.3, "no_speech_prob": 0.01,
                                 "compression_ratio": 1.3})
            t += 6.0
            i += 1
            time.sleep(step_sleep)
            if req.on_progress:
                req.on_progress(min(t, duration))
        return out
