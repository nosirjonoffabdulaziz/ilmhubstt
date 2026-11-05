"""ilmhubstt — ASGI ilova (Starlette + Uvicorn).

Ishga tushirish:  python run.py   (yoki: uvicorn app.main:app --port 8000)
"""
from __future__ import annotations

import contextlib
import hashlib
import logging
import time
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .api import exports, jobs, settings_api
from .config import load_settings
from .security.auth import RateLimiter, access_key_ok
from .services import ffmpeg_service as ff
from .services.asr_service import build_engines
from .storage.repository import JobRepository
from .workers.transcription_worker import TranscriptionWorker

VERSION = "1.0.0"
log = logging.getLogger("ilmhubstt")


class Context:
    def __init__(self, settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.repo = JobRepository(settings.db_path, settings.jobs_dir)
        self.engines = build_engines(settings)
        self.worker = TranscriptionWorker(self.repo, self.engines, settings)
        self.limiter = RateLimiter(settings.rate_limit_per_hour)
        from .services.llm_proofread import OllamaProofreader
        self.proofreader = OllamaProofreader(settings.ollama_url, settings.ollama_model, settings.ollama_timeout)
        self.worker.proofreader = self.proofreader

    def available_engines(self) -> list[str]:
        return [name for name, e in self.engines.items() if e.available()[0]]

    def default_engine(self) -> str:
        avail = self.available_engines()
        if self.settings.default_engine in avail:
            return self.settings.default_engine
        return avail[0] if avail else self.settings.default_engine

    def client_ip(self, request: Request) -> str:
        ip = request.client.host if request.client else "unknown"
        if self.settings.trust_proxy:
            fwd = request.headers.get("x-forwarded-for", "")
            if fwd:
                ip = fwd.split(",")[0].strip()
        return hashlib.sha256(ip.encode()).hexdigest()[:16]


# ---------------- ASGI middleware ----------------
class SecurityMiddleware:
    """Xavfsizlik sarlavhalari, kirish kaliti, yuklama hajmi chegarasi va so'rovlar logi
    (logga so'rov parametrlari — tokenlar — va audio mazmuni yozilmaydi)."""

    # Brauzer rejimi: Gemini API (BYOK), YouTube pleeri/oEmbed va to'g'ridan-to'g'ri havolalar (https)
    CSP = ("default-src 'self'; img-src 'self' data: blob: https://i.ytimg.com https://*.ytimg.com; media-src 'self' blob:; "
           "style-src 'self' 'unsafe-inline'; script-src 'self' https://www.youtube.com https://s.ytimg.com; "
           "connect-src 'self' https:; frame-src https://www.youtube.com https://www.youtube-nocookie.com; "
           "font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")

    def __init__(self, app, settings):
        self.app = app
        self.s = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        start = time.time()
        status_holder = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                h = list(message.get("headers", []))
                extra = {
                    b"x-content-type-options": b"nosniff",
                    b"referrer-policy": b"strict-origin-when-cross-origin",  # YouTube pleeri Referer talab qiladi
                    b"x-frame-options": b"DENY",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
                }
                if not path.startswith("/api/"):
                    extra[b"content-security-policy"] = self.CSP.encode()
                present = {k.lower() for k, _ in h}
                h.extend((k, v) for k, v in extra.items() if k not in present)
                message["headers"] = h
            await send(message)

        if path.startswith("/api/") and path not in ("/api/v1/health", "/api/v1/config") and method != "OPTIONS":
            provided = headers.get("x-access-key") or _query_value(scope, "key")
            if not access_key_ok(provided, self.s.access_key):
                resp = JSONResponse({"error": "access_key_required"}, status_code=401)
                return await resp(scope, receive, send_wrapper)

        if method == "POST" and path == "/api/v1/jobs":
            limit = self.s.max_upload_bytes + 2 * 1024 * 1024
            received = {"n": 0}

            async def limited_receive():
                message = await receive()
                if message["type"] == "http.request":
                    received["n"] += len(message.get("body", b""))
                    if received["n"] > limit:
                        raise _TooLarge()
                return message

            try:
                await self.app(scope, limited_receive, send_wrapper)
            except _TooLarge:
                resp = JSONResponse({"error": "file_too_large", "max_mb": self.s.max_upload_mb}, status_code=413)
                with contextlib.suppress(Exception):
                    await resp(scope, receive, send_wrapper)
        else:
            await self.app(scope, receive, send_wrapper)
        if path.startswith("/api/"):
            log.info("%s %s -> %s (%.0f ms)", method, _redact(path), status_holder["code"], (time.time() - start) * 1000)


class _TooLarge(Exception):
    pass


def _query_value(scope, key: str) -> str | None:
    from urllib.parse import parse_qs
    qs = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    vals = qs.get(key)
    return vals[0] if vals else None


def _redact(path: str) -> str:
    parts = path.split("/")
    return "/".join(p[:8] + "…" if len(p) == 32 else p for p in parts)


# ---------------- marshrutlar ----------------
async def health(request: Request):
    ctx = request.app.state.ctx
    tools = ff.check_tools()
    return JSONResponse({"ok": all(tools.values()), "version": VERSION, "tools": tools,
                         "engines": [e.describe() for e in ctx.engines.values()],
                         "proofreader": ctx.proofreader.status(),
                         "queued": ctx.repo.count_status("queued"),
                         "active": ctx.repo.count_status("converting", "transcribing", "normalizing")})


async def config(request: Request):
    ctx = request.app.state.ctx
    s = ctx.settings
    return JSONResponse({
        "version": VERSION,
        "languages": ["uz", "ky", "kk", "auto"],
        "scripts": ["latin", "original"],
        "modes": ["clean", "verbatim"],
        "qualities": ["fast", "balanced", "best"],
        "default_quality": s.default_quality,
        "engines": [e.describe() for e in ctx.engines.values()],
        "default_engine": ctx.default_engine(),
        "max_upload_mb": s.max_upload_mb,
        "max_duration_min": s.max_duration_min,
        "retention_hours": s.retention_hours,
        "requires_access_key": bool(s.access_key),
        "export_formats": ["txt", "txt_ts", "srt", "vtt", "json"],
        "proofreader": {**ctx.proofreader.status(), "default_on": s.ai_proofread_default},
        "ffmpeg": ff.check_tools(),
        "transliteration_profiles": {
            "uz": "O‘zbek lotin (1995, rasmiy)",
            "kk": "Qozoq lotin (2021 loyihasi)",
            "ky": "Qirg‘iz lotin (loyiha profili)",
        },
    })


def spa_routes(settings) -> list:
    dist: Path = settings.frontend_dist
    index = dist / "index.html"
    routes = []
    if (dist / "assets").is_dir():
        routes.append(Mount("/assets", app=StaticFiles(directory=dist / "assets"), name="assets"))

    async def spa(request: Request):
        rel = request.path_params.get("path", "")
        candidate = (dist / rel).resolve() if rel else index
        try:
            candidate.relative_to(dist.resolve())
        except ValueError:
            candidate = index
        if rel and candidate.is_file():
            return FileResponse(candidate)
        if index.exists():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return Response("Frontend topilmadi: frontend/dist yo'q. README'ga qarang.", status_code=503,
                        media_type="text/plain; charset=utf-8")

    async def api_404(request: Request):
        return JSONResponse({"error": "not_found"}, status_code=404)

    routes.append(Route("/api/{path:path}", api_404, methods=["GET", "POST", "PATCH", "DELETE", "PUT"]))
    routes.append(Route("/{path:path}", spa))
    return routes


def create_app(settings=None) -> Starlette:
    settings = settings or load_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @contextlib.asynccontextmanager
    async def lifespan(app):
        ctx = app.state.ctx
        tools = ff.check_tools()
        if not all(tools.values()):
            log.error("FFmpeg/FFprobe topilmadi! O'rnating va PATH ga qo'shing (README).")
        requeued = ctx.repo.requeue_interrupted()
        if requeued:
            log.info("Uzilib qolgan %d ta ish navbatga qaytarildi", len(requeued))
        for name, e in ctx.engines.items():
            ok, reason = e.available()
            log.info("Dvigatel %s: %s %s", name, "tayyor" if ok else "mavjud emas", reason)
        ctx.worker.start()
        yield
        ctx.worker.stop()
        ctx.repo.close()

    api = [
        Route("/api/v1/health", health),
        Route("/api/v1/config", config),
        Route("/api/v1/jobs", jobs.create_job, methods=["POST"]),
        Route("/api/v1/jobs/{job_id}", jobs.get_job, methods=["GET"]),
        Route("/api/v1/jobs/{job_id}", jobs.delete_job, methods=["DELETE"]),
        Route("/api/v1/jobs/{job_id}/cancel", jobs.cancel_job, methods=["POST"]),
        Route("/api/v1/jobs/{job_id}/result", jobs.get_result, methods=["GET"]),
        Route("/api/v1/jobs/{job_id}/result", jobs.patch_result, methods=["PATCH"]),
        Route("/api/v1/jobs/{job_id}/export", exports.export_job, methods=["GET"]),
        Route("/api/v1/jobs/{job_id}/audio", jobs.get_audio, methods=["GET"]),
        Route("/api/v1/settings/gemini", settings_api.get_gemini, methods=["GET"]),
        Route("/api/v1/settings/gemini", settings_api.set_gemini, methods=["POST"]),
        Route("/api/v1/settings/gemini", settings_api.delete_gemini, methods=["DELETE"]),
    ]
    middleware = [Middleware(SecurityMiddleware, settings=settings)]
    if settings.cors_origins:
        middleware.insert(0, Middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                                        allow_methods=["GET", "POST", "PATCH", "DELETE"],
                                        allow_headers=["x-job-token", "x-access-key", "content-type"]))
    app = Starlette(routes=api + spa_routes(settings), middleware=middleware, lifespan=lifespan)
    app.state.ctx = Context(settings)
    return app


_APP = None


def __getattr__(name):  # `uvicorn app.main:app` uchun dangasa yaratish
    global _APP
    if name == "app":
        if _APP is None:
            _APP = create_app()
        return _APP
    raise AttributeError(name)
