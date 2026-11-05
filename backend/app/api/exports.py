"""/api/v1/jobs/{id}/export — TXT, vaqt belgili TXT, SRT, VTT, JSON."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from ..services.export_service import FORMATS, content_disposition, download_name, render
from ..workers.transcription_worker import read_json
from .jobs import err, load_job


async def export_job(request: Request):
    job, e = load_job(request)
    if e:
        return e
    fmt = request.query_params.get("format", "txt").lower()
    if fmt not in FORMATS:
        return err("invalid_format")
    if job["status"] != "completed":
        return err("not_ready", 409)
    path = request.app.state.ctx.repo.job_dir(job["id"]) / "result.json"
    if not path.exists():
        return err("not_found", 404)
    body = render(read_json(path), fmt)
    mime, _ = FORMATS[fmt]
    return Response(body.encode("utf-8"), media_type=mime,
                    headers={"Content-Disposition": content_disposition(download_name(job["filename"], fmt)),
                             "Cache-Control": "no-store"})
