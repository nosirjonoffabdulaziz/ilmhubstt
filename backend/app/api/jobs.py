"""/api/v1/jobs — ish yaratish, holat, natija, tahrir, bekor qilish, o'chirish."""
from __future__ import annotations

import json
import shutil

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from ..security.auth import hash_token, new_job_id, new_token, token_matches
from ..security.validation import ValidationError, parse_options, safe_filename
from ..services import ffmpeg_service as ff
from ..workers.transcription_worker import read_json, write_json

MAX_EDIT_CHARS = 5_000_000
_WORD_RE = None


def _learn_words(path, before: str, after: str) -> None:
    """Foydalanuvchi qo'lda yozgan/tuzatgan so'zlarni shaxsiy lug'atga qo'shish (keyingi tuzatishlar uchun)."""
    import re
    global _WORD_RE
    if _WORD_RE is None:
        _WORD_RE = re.compile(r"[A-Za-z\u2018\u2019'-]{3,40}")
    old = {w.lower() for w in _WORD_RE.findall(before)}
    new = {w.lower().strip("-'") for w in _WORD_RE.findall(after)} - old
    if not new:
        return
    try:
        known = set(path.read_text(encoding="utf-8").split()) if path.exists() else set()
        add = sorted(w for w in new if w and w not in known)[:500]
        if add:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("\n".join(add) + "\n")
    except OSError:
        pass


def err(code: str, status: int = 400, **extra) -> JSONResponse:
    return JSONResponse({"error": code, **extra}, status_code=status)


def _token(request: Request) -> str | None:
    return request.headers.get("x-job-token") or request.query_params.get("token")


def load_job(request: Request) -> tuple[dict | None, JSONResponse | None]:
    state = request.app.state.ctx
    job_id = request.path_params["job_id"]
    if not (len(job_id) == 32 and all(c in "0123456789abcdef" for c in job_id)):
        return None, err("not_found", 404)
    job = state.repo.get(job_id)
    # Ish topilmasa ham, token xato bo'lsa ham bir xil javob — boshqa ishlar borligini oshkor qilmaslik
    if job is None or not token_matches(_token(request), job["token_hash"]):
        return None, err("not_found", 404)
    return job, None


def public_job(state, job: dict) -> dict:
    return {
        "job_id": job["id"],
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "error": job["error_code"],
        "filename": job["filename"],
        "size_bytes": job["size_bytes"],
        "duration": job["duration"],
        "options": job["options"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "processed_seconds": job["processed_seconds"],
        "eta_seconds": job["eta_seconds"],
        "queue_position": state.repo.queue_position(job["id"]),
        "language": job["language"],
        "warnings": job["warnings"],
        "preview": job["preview"],
        "detail": job.get("detail") or {},
    }


async def create_job(request: Request):
    state = request.app.state.ctx
    s = state.settings
    ip = state.client_ip(request)
    if not state.limiter.allow(ip):
        return err("rate_limited", 429)
    if state.repo.count_status("queued") >= s.max_queued_jobs:
        return err("server_busy", 503)
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > s.max_upload_bytes + 1024 * 1024:
        return err("file_too_large", 413, max_mb=s.max_upload_mb)
    if "multipart/form-data" not in request.headers.get("content-type", ""):
        return err("multipart_required", 415)

    try:
        form = await request.form(max_files=1, max_fields=20)
    except Exception:
        return err("bad_upload", 400)
    try:
        upload = form.get("file")
        if upload is None or isinstance(upload, str) or not getattr(upload, "filename", None):
            return err("file_missing", 400)
        try:
            options = parse_options({k: v for k, v in form.items() if isinstance(v, str)},
                                    engines=state.available_engines(), default_engine=state.default_engine(),
                                    default_quality=s.default_quality)
        except ValidationError as exc:
            return err(exc.code, exc.status)

        job_id = new_job_id()
        token = new_token()
        jdir = state.repo.job_dir(job_id)
        jdir.mkdir(parents=True, exist_ok=False)
        dest = jdir / "upload.bin"
        size = 0
        try:
            with open(dest, "wb") as out:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > s.max_upload_bytes:
                        raise ValidationError("file_too_large", status=413)
                    out.write(chunk)
            if size == 0:
                raise ValidationError("empty_file")
            try:
                info = ff.probe(dest)
            except ff.MediaError as exc:
                raise ValidationError(exc.code, status=422 if exc.code != "ffmpeg_missing" else 500) from exc
            if info["duration"] > s.max_duration_min * 60 + 1:
                raise ValidationError("too_long", status=422)
        except ValidationError as exc:
            shutil.rmtree(jdir, ignore_errors=True)
            extra = {"max_mb": s.max_upload_mb} if exc.code == "file_too_large" else {}
            if exc.code == "too_long":
                extra = {"max_minutes": s.max_duration_min}
            return err(exc.code, exc.status, **extra)
        except Exception:
            shutil.rmtree(jdir, ignore_errors=True)
            raise

        name = safe_filename(upload.filename)
        state.repo.create(job_id, hash_token(token), name, size, info["duration"], options)
        state.worker.notify()
        return JSONResponse({"job_id": job_id, "status": "queued", "token": token,
                             "duration": info["duration"]}, status_code=201)
    finally:
        await form.close()


async def get_job(request: Request):
    job, e = load_job(request)
    if e:
        return e
    return JSONResponse(public_job(request.app.state.ctx, job))


async def get_result(request: Request):
    job, e = load_job(request)
    if e:
        return e
    if job["status"] != "completed":
        return err("not_ready", 409, status=job["status"])
    path = request.app.state.ctx.repo.job_dir(job["id"]) / "result.json"
    if not path.exists():
        return err("not_found", 404)
    data = read_json(path)
    data.pop("preview_file", None)
    data["job_id"] = job["id"]
    data["filename"] = job["filename"]
    return JSONResponse(data)


async def patch_result(request: Request):
    job, e = load_job(request)
    if e:
        return e
    if job["status"] != "completed":
        return err("not_ready", 409)
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return err("bad_json")
    text = body.get("edited_text") if isinstance(body, dict) else None
    if not isinstance(text, str):
        return err("edited_text_required")
    if len(text) > MAX_EDIT_CHARS:
        return err("text_too_long", 413)
    path = request.app.state.ctx.repo.job_dir(job["id"]) / "result.json"
    data = read_json(path)
    data["edited_text"] = text.replace("\r\n", "\n")
    write_json(path, data)
    if (data.get("options") or {}).get("language") in ("uz", "auto") and data.get("language") in ("uz", None, "auto"):
        _learn_words(request.app.state.ctx.settings.data_dir / "user_lexicon.txt",
                     data.get("latin_text", ""), data["edited_text"])
    request.app.state.ctx.repo.update(job["id"])  # updated_at
    return JSONResponse({"ok": True, "chars": len(data["edited_text"])})


async def cancel_job(request: Request):
    job, e = load_job(request)
    if e:
        return e
    repo = request.app.state.ctx.repo
    if job["status"] in ("completed", "failed", "cancelled"):
        return JSONResponse({"job_id": job["id"], "status": job["status"]})
    if job["status"] == "queued":
        repo.update(job["id"], cancel_requested=1, status="cancelled", stage="cancelled")
        shutil.rmtree(repo.job_dir(job["id"]), ignore_errors=True)
    else:
        repo.update(job["id"], cancel_requested=1)
    return JSONResponse({"job_id": job["id"], "status": "cancelling" if job["status"] != "queued" else "cancelled"})


async def delete_job(request: Request):
    job, e = load_job(request)
    if e:
        return e
    repo = request.app.state.ctx.repo
    if job["status"] in ("converting", "transcribing", "normalizing"):
        repo.update(job["id"], cancel_requested=1)
        # Ishchi to'xtagach yozuvni o'chiradi; foydalanuvchi uchun darhol "o'chirildi"
        repo.update(job["id"], status="cancelled")
    repo.delete(job["id"])
    return JSONResponse({"deleted": True, "job_id": job["id"]})


async def get_audio(request: Request):
    job, e = load_job(request)
    if e:
        return e
    jdir = request.app.state.ctx.repo.job_dir(job["id"])
    marker = jdir / "converted.ok"
    if not marker.exists():
        return err("not_ready", 409)
    name = marker.read_text(encoding="utf-8").strip()
    path = jdir / name
    if not path.exists() or path.parent != jdir:
        return err("not_found", 404)
    mime = "audio/mpeg" if path.suffix == ".mp3" else "audio/mp4"
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, max-age=3600"})
