"""ilmhubstt sozlamalari.

Barcha qiymatlar muhit o'zgaruvchilaridan yoki loyiha ildizidagi `.env` faylidan o'qiladi.
`.env` uchun qo'shimcha kutubxona kerak emas: oddiy KEY=VALUE qatorlari o'qiladi.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


def _load_dotenv() -> None:
    custom = os.environ.get("ENV_FILE", "").strip()
    for candidate in ((Path(custom),) if custom else (PROJECT_DIR / ".env", BACKEND_DIR / ".env")):
        if not candidate.is_file():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = re.split(r"\s+#", value.strip(), maxsplit=1)[0].strip().strip('"').strip("'")
            # Haqiqiy muhit o'zgaruvchisi .env dan ustun turadi
            os.environ.setdefault(key, value)


def set_env_value(env_path: Path, key: str, value: str | None) -> None:
    """.env faylidagi KEY=... qatorini yangilash/qo'shish (value=None -> o'chirish)."""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    pattern = re.compile(rf"^\s*#?\s*{re.escape(key)}\s*=")
    out, done = [], False
    for line in lines:
        if pattern.match(line):
            if not done and value is not None:
                out.append(f"{key}={value}")
                done = True
            elif line.lstrip().startswith("#") and value is None:
                out.append(line)
            continue
        out.append(line)
    if not done and value is not None:
        out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def env_file_path() -> Path:
    custom = os.environ.get("ENV_FILE", "").strip()
    return Path(custom) if custom else PROJECT_DIR / ".env"


def _env(name: str, default: str) -> str:
    # "QIYMAT   # izoh" ko'rinishidagi qatorlardan izohni olib tashlash
    return re.split(r"\s+#", os.environ.get(name, default), maxsplit=1)[0].strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = PROJECT_DIR / "data"
    model_dir: Path = PROJECT_DIR / "models"
    frontend_dist: Path = PROJECT_DIR / "frontend" / "dist"

    max_upload_mb: int = 1024
    max_duration_min: int = 180
    retention_hours: int = 24
    max_queued_jobs: int = 50
    rate_limit_per_hour: int = 30
    workers: int = 1

    default_engine: str = "faster-whisper"
    default_quality: str = "balanced"
    whisper_models: dict = field(default_factory=dict)
    whisper_lang_overrides: dict = field(default_factory=dict)
    whisper_model_overrides: dict = field(default_factory=dict)
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    whisper_cpu_threads: int = 0
    whisper_beam_size: int = 5
    chunk_minutes: int = 10
    uncertain_word_prob: float = 0.5

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3-flash-preview"
    gemini_fallback_models: list = field(default_factory=lambda: ["gemini-3-flash-preview", "gemini-2.5-flash",
                                                                  "gemini-2.5-flash-lite"])
    gemini_base_url: str = ""
    gemini_max_wait: float = 900.0
    gemini_price_in: float = 0.0
    gemini_price_out: float = 0.0
    elevenlabs_api_key: str = ""
    elevenlabs_model: str = "scribe_v2"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma3:12b"
    ollama_timeout: float = 900.0
    ai_proofread_default: bool = True
    enable_dummy_engine: bool = False
    dummy_speed: float = 50.0

    access_key: str = ""
    cors_origins: list = field(default_factory=list)
    trust_proxy: bool = False

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ilmhubstt.sqlite3"


def load_settings() -> Settings:
    _load_dotenv()
    s = Settings()
    s.host = _env("HOST", s.host)
    s.port = _env_int("PORT", s.port)
    data = _env("DATA_DIR", "")
    if data:
        s.data_dir = Path(data).expanduser().resolve()
    models = _env("MODEL_DIR", "")
    if models:
        s.model_dir = Path(models).expanduser().resolve()
    s.max_upload_mb = max(1, _env_int("MAX_UPLOAD_MB", s.max_upload_mb))
    s.max_duration_min = max(1, _env_int("MAX_DURATION_MIN", s.max_duration_min))
    s.retention_hours = max(1, _env_int("RETENTION_HOURS", s.retention_hours))
    s.max_queued_jobs = max(1, _env_int("MAX_QUEUED_JOBS", s.max_queued_jobs))
    s.rate_limit_per_hour = max(0, _env_int("RATE_LIMIT_PER_HOUR", s.rate_limit_per_hour))
    s.workers = max(1, _env_int("WORKERS", s.workers))

    s.default_engine = _env("ASR_ENGINE", s.default_engine)
    s.default_quality = _env("DEFAULT_QUALITY", s.default_quality)
    s.whisper_models = {
        "fast": _env("WHISPER_MODEL_FAST", "small"),
        "balanced": _env("WHISPER_MODEL_BALANCED", "medium"),
        "best": _env("WHISPER_MODEL_BEST", "large-v3-turbo"),
    }
    # Til bo'yicha alohida model (masalan, o'zbekchaga fine-tune qilingan CTranslate2 model papkasi)
    s.whisper_model_overrides = {
        lang: _env(f"WHISPER_MODEL_{lang.upper()}", "")
        for lang in ("uz", "kk", "ky")
        if _env(f"WHISPER_MODEL_{lang.upper()}", "")
    }
    # Whisper qirg'iz tilini rasmiy qo'llamaydi: standart holatda eng yaqin til (qozoq) bilan ishlaydi
    s.whisper_lang_overrides = {"ky": _env("WHISPER_LANG_KY", "kk")}
    s.whisper_device = _env("WHISPER_DEVICE", s.whisper_device)
    s.whisper_compute_type = _env("WHISPER_COMPUTE_TYPE", s.whisper_compute_type)
    s.whisper_cpu_threads = max(0, _env_int("WHISPER_CPU_THREADS", s.whisper_cpu_threads))
    s.whisper_beam_size = max(1, _env_int("WHISPER_BEAM_SIZE", s.whisper_beam_size))
    s.chunk_minutes = min(30, max(2, _env_int("CHUNK_MINUTES", s.chunk_minutes)))
    s.uncertain_word_prob = min(0.99, max(0.01, _env_float("UNCERTAIN_WORD_PROB", s.uncertain_word_prob)))

    s.gemini_api_key = _env("GEMINI_API_KEY", "")
    s.gemini_model = _env("GEMINI_MODEL", s.gemini_model)
    fb = _env("GEMINI_FALLBACK_MODELS", "")
    if fb:
        s.gemini_fallback_models = [m.strip() for m in fb.split(",") if m.strip()]
    s.gemini_base_url = _env("GEMINI_BASE_URL", "")
    s.gemini_max_wait = max(30.0, _env_float("GEMINI_MAX_WAIT", s.gemini_max_wait))
    s.gemini_price_in = max(0.0, _env_float("GEMINI_PRICE_IN", 0.0))
    s.gemini_price_out = max(0.0, _env_float("GEMINI_PRICE_OUT", 0.0))
    s.elevenlabs_api_key = _env("ELEVENLABS_API_KEY", "")
    s.elevenlabs_model = _env("ELEVENLABS_MODEL", s.elevenlabs_model)
    s.ollama_url = _env("OLLAMA_URL", s.ollama_url)
    s.ollama_model = _env("OLLAMA_MODEL", s.ollama_model)
    s.ollama_timeout = max(30.0, _env_float("OLLAMA_TIMEOUT", s.ollama_timeout))
    s.ai_proofread_default = _env_bool("AI_PROOFREAD_DEFAULT", True)
    s.enable_dummy_engine = _env_bool("ENABLE_DUMMY_ENGINE", False)
    s.dummy_speed = max(1.0, _env_float("DUMMY_SPEED", s.dummy_speed))

    s.access_key = _env("APP_ACCESS_KEY", "")
    s.cors_origins = [o.strip() for o in _env("CORS_ORIGINS", "").split(",") if o.strip()]
    s.trust_proxy = _env_bool("TRUST_PROXY", False)
    dist = _env("FRONTEND_DIST", "")
    if dist:
        s.frontend_dist = Path(dist).expanduser().resolve()
    return s
