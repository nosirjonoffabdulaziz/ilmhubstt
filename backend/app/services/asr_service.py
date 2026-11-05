"""ASR dvigatellari uchun umumiy interfeys va ro'yxat (adapter arxitekturasi).

Yangi model (masalan, GigaAM yoki boshqa API) qo'shish uchun `BaseEngine` dan meros olib,
`transcribe` ni yozish va `build_engines` ga qo'shish kifoya.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np


class EngineError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


@dataclass
class EngineOutput:
    segments: list[dict] = field(default_factory=list)  # mutlaq vaqt bilan
    language: str | None = None
    language_probability: float | None = None
    meta: dict = field(default_factory=dict)              # bulut: model, tokenlar


@dataclass
class TranscribeRequest:
    language: str | None          # modelga beriladigan til kodi (None = avtomatik)
    prompt: str | None
    terms: list[str]
    quality: str                   # fast | balanced | best
    user_language: str             # foydalanuvchi tanlovi: uz | ky | kk | auto
    offset: float = 0.0
    on_progress: Callable[[float], None] | None = None   # bo'lak boshidan qayta ishlangan soniyalar (nisbiy)
    cancelled: Callable[[], bool] | None = None
    on_status: Callable[[str, dict], None] | None = None
    mode: str = "clean"   # bosqich: downloading_model, loading_model ...


class BaseEngine:
    name = "base"
    supports_chunks = True   # False bo'lsa, butun fayl bir marta yuboriladi
    is_cloud = False

    def available(self) -> tuple[bool, str]:
        return True, ""

    def describe(self) -> dict:
        ok, reason = self.available()
        return {"id": self.name, "available": ok, "reason": reason, "cloud": self.is_cloud,
                "chunked": self.supports_chunks}

    def transcribe(self, audio: np.ndarray | Path, req: TranscribeRequest) -> EngineOutput:  # pragma: no cover
        raise NotImplementedError


def build_engines(settings) -> dict[str, BaseEngine]:
    from .engines.faster_whisper_engine import FasterWhisperEngine
    from .engines.elevenlabs_engine import ElevenLabsEngine
    from .engines.dummy_engine import DummyEngine
    from .engines.gemini_engine import GeminiEngine

    engines: dict[str, BaseEngine] = {"faster-whisper": FasterWhisperEngine(settings)}
    engines["gemini"] = GeminiEngine(settings)   # kalit kiritilgach (Sozlamalar) ishga tushadi
    if settings.elevenlabs_api_key:
        engines["elevenlabs"] = ElevenLabsEngine(settings)
    if settings.enable_dummy_engine:
        engines["dummy"] = DummyEngine(settings)
    return engines
