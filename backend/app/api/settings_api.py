"""/api/v1/settings/gemini — Gemini API kalitini saytdan kiritish, tekshirish va saqlash."""
from __future__ import annotations

import os
import re
import shutil

from starlette.requests import Request
from starlette.responses import JSONResponse

from ..config import PROJECT_DIR, env_file_path, set_env_value

_KEY_RE = re.compile(r"^[A-Za-z0-9_\-.~+/=]{20,400}$")  # AIza... (eski) va AQ.xxx (yangi) formatlar


def _local_or_authorized(request: Request) -> bool:
    ctx = request.app.state.ctx
    if ctx.settings.access_key:
        return True  # kirish kaliti middleware'da tekshirilgan
    host = request.client.host if request.client else ""
    if ctx.settings.trust_proxy and request.headers.get("x-forwarded-for"):
        return False
    return host in ("127.0.0.1", "::1", "localhost")


def _status(ctx) -> dict:
    eng = ctx.engines.get("gemini")
    d = eng.describe() if eng else {"available": False}
    return {"key_set": d.get("key_set", False), "key_hint": d.get("key_hint", ""), "model": d.get("model"),
            "available": d.get("available", False)}


async def get_gemini(request: Request):
    return JSONResponse(_status(request.app.state.ctx))


async def set_gemini(request: Request):
    ctx = request.app.state.ctx
    if not _local_or_authorized(request):
        return JSONResponse({"error": "settings_local_only"}, status_code=403)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "bad_json"}, status_code=400)
    key = "".join(str((body or {}).get("api_key", "")).split()).strip("\"'")
    if not _KEY_RE.match(key):
        return JSONResponse({"error": "invalid_key_format"}, status_code=400)
    eng = ctx.engines["gemini"]
    ok, code, models = eng.check_key(key)
    if not ok:
        return JSONResponse({"error": code, "detail": (models or [""])[0][:300]}, status_code=400)
    ctx.settings.gemini_api_key = key
    os.environ["GEMINI_API_KEY"] = key
    eng._models_cache = None
    env = env_file_path()
    if not env.exists() and (PROJECT_DIR / ".env.example").exists():
        shutil.copy(PROJECT_DIR / ".env.example", env)
    set_env_value(env, "GEMINI_API_KEY", key)
    usable = [m for m in models if "flash" in m and "tts" not in m and "image" not in m][:8]
    return JSONResponse({**_status(ctx), "models": usable, "saved": True})


async def delete_gemini(request: Request):
    ctx = request.app.state.ctx
    if not _local_or_authorized(request):
        return JSONResponse({"error": "settings_local_only"}, status_code=403)
    ctx.settings.gemini_api_key = ""
    os.environ.pop("GEMINI_API_KEY", None)
    set_env_value(env_file_path(), "GEMINI_API_KEY", None)
    return JSONResponse(_status(ctx))
