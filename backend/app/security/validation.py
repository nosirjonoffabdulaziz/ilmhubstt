"""Kiruvchi ma'lumotlarni tekshirish: fayl nomi va transkripsiya parametrlari."""
from __future__ import annotations

import re
import unicodedata

LANGUAGES = ("uz", "ky", "kk", "auto")
SCRIPTS = ("latin", "original")
MODES = ("clean", "verbatim")
QUALITIES = ("fast", "balanced", "best")

MAX_VOCAB_CHARS = 600
_SAFE_NAME = re.compile(r"[^\w.\- ()\[\]\u2018\u2019']+", re.UNICODE)


class ValidationError(Exception):
    def __init__(self, code: str, message: str = "", status: int = 400):
        super().__init__(message or code)
        self.code = code
        self.status = status


def safe_filename(name: str | None, fallback: str = "audio") -> str:
    """Faqat ko'rsatish uchun ishlatiladigan xavfsiz nom (diskda fayl job_id bilan saqlanadi)."""
    name = unicodedata.normalize("NFC", name or "")
    name = name.replace("\\", "/").split("/")[-1]  # path traversal'ni olib tashlash
    name = name.replace("\x00", "")
    name = _SAFE_NAME.sub("_", name).strip(" .")
    name = re.sub(r"_+", "_", name)
    if not name:
        name = fallback
    if len(name) > 120:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 8:
            name = stem[: 119 - len(ext)] + "." + ext
        else:
            name = name[:120]
    return name


def _bool(value, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_options(form: dict, *, engines: list[str], default_engine: str, default_quality: str) -> dict:
    language = str(form.get("language") or "uz").strip().lower()
    if language not in LANGUAGES:
        raise ValidationError("invalid_language")
    script = str(form.get("script") or "latin").strip().lower()
    if script not in SCRIPTS:
        raise ValidationError("invalid_script")
    mode = str(form.get("mode") or "clean").strip().lower()
    if mode not in MODES:
        raise ValidationError("invalid_mode")
    quality = str(form.get("quality") or default_quality).strip().lower()
    if quality not in QUALITIES:
        raise ValidationError("invalid_quality")
    engine = str(form.get("engine") or default_engine).strip().lower()
    if engine not in engines:
        raise ValidationError("engine_unavailable")
    vocabulary = str(form.get("vocabulary") or "")
    vocabulary = unicodedata.normalize("NFC", vocabulary)
    vocabulary = re.sub(r"[\x00-\x1f\x7f]+", " ", vocabulary)
    vocabulary = re.sub(r"\s{2,}", " ", vocabulary).strip()[:MAX_VOCAB_CHARS]
    return {
        "language": language,
        "script": script,
        "mode": mode,
        "punctuation": _bool(form.get("punctuation"), True),
        "paragraphs": _bool(form.get("paragraphs"), True),
        "spellfix": _bool(form.get("spellfix"), True),
        "ai_proofread": _bool(form.get("ai_proofread"), False),
        "quality": quality,
        "engine": engine,
        "vocabulary": vocabulary,
    }
