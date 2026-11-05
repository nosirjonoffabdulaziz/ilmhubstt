"""Gemini dvigateli testlari — soxta Gemini REST serveri bilan (haqiqiy API formati)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest
import requests

from app.config import Settings
from app.services.asr_service import EngineError, TranscribeRequest
from app.services.engines.gemini_engine import GeminiEngine, build_prompt, estimate_cost, parse_segments, parse_time

from .conftest import needs_ffmpeg

GOOD_KEY = "AQ.Ab8TEST_new-format_key0123456789abcdef"
SEGMENTS = [{"start": "00:00.0", "end": "00:04.5", "text": "Assalomu alaykum, hurmatli ustozlar."},
            {"start": "00:04.5", "end": "00:11.2", "text": "Hozirda olib borilayotgan onlayn sun’iy intellekt kursimiz."}]


class FakeGemini:
    def __init__(self, plan=None, models=("gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite")):
        self.plan = list(plan or [])     # navbatdagi javoblar: "ok", "429", "500", "404", "thinking400"
        self.models = models
        self.calls = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj, code=200):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.headers.get("x-goog-api-key") != GOOD_KEY:
                    return self._send({"error": {"code": 400, "message": "API key not valid",
                                                 "status": "INVALID_ARGUMENT",
                                                 "details": [{"reason": "API_KEY_INVALID"}]}}, 400)
                self._send({"models": [{"name": "models/" + m} for m in outer.models]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                model = self.path.split("/models/")[1].split(":")[0]
                outer.calls.append({"model": model, "body": body})
                if self.headers.get("x-goog-api-key") != GOOD_KEY:
                    return self._send({"error": {"code": 400, "message": "API_KEY_INVALID"}}, 400)
                step = outer.plan.pop(0) if outer.plan else "ok"
                if step == "429":
                    return self._send({"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                                 "details": [{"retryDelay": "1s"}]}}, 429)
                if step == "500":
                    return self._send({"error": {"code": 503}}, 503)
                if step == "404" or model not in outer.models:
                    return self._send({"error": {"code": 404, "status": "NOT_FOUND"}}, 404)
                if step == "thinking400" and "thinkingConfig" in body["generationConfig"]:
                    return self._send({"error": {"code": 400, "message": "thinking_level is not supported"}}, 400)
                part = body["contents"][0]["parts"][0]["inline_data"]
                assert part["mime_type"] in ("audio/ogg", "audio/flac") and len(part["data"]) > 100
                self._send({"candidates": [{"content": {"parts": [{"text": json.dumps(SEGMENTS, ensure_ascii=False)}]},
                                            "finishReason": "STOP"}],
                            "usageMetadata": {"promptTokenCount": 3900, "candidatesTokenCount": 120,
                                              "thoughtsTokenCount": 30}})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1beta"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


def settings(tmp_path, url, key=GOOD_KEY, **kw):
    s = Settings()
    s.data_dir = tmp_path
    s.gemini_api_key = key
    s.gemini_base_url = url
    s.gemini_max_wait = 30
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def req(**kw):
    base = dict(language="uz", prompt=None, terms=["ILMHUB"], quality="balanced", user_language="uz", offset=600.0)
    base.update(kw)
    return TranscribeRequest(**base)


AUDIO = (0.2 * np.sin(np.linspace(0, 2000, 16000 * 12))).astype(np.float32)


def test_parse_time_and_segments():
    assert parse_time("01:02.5") == 62.5 and parse_time("1:00:03") == 3603 and parse_time(4) == 4.0
    assert parse_time("abc") is None
    segs = parse_segments("```json\n" + json.dumps(SEGMENTS) + "\n```", 12.0)
    assert segs[0] == {"start": 0.0, "end": 4.5, "text": "Assalomu alaykum, hurmatli ustozlar."}
    assert segs[1]["start"] == 4.5 and segs[1]["end"] == 11.2
    # vaqtsiz / tartibsiz -> matn uzunligi bo'yicha taqsimlanadi, 0..duration ichida
    bad = parse_segments(json.dumps([{"start": "x", "end": "", "text": "Bir"}, {"start": "99:00", "text": "Ikki gap"}]), 10)
    assert bad[0]["start"] == 0 and bad[-1]["end"] <= 10 and bad[0]["start"] <= bad[1]["start"]
    assert parse_segments("oddiy matn", 5) == [{"start": 0.0, "end": 5, "text": "oddiy matn"}]


def test_prompt_rules():
    p = build_prompt("uz", "clean", ["ILMHUB", "Samarqand"])
    assert "o‘zbek lotin" in p and "Tarjima QILMA" in p and "ILMHUB, Samarqand" in p and "JSON" in p
    assert "kirill" in build_prompt("kk", "verbatim", []) and "So‘zma-so‘z" in build_prompt("kk", "verbatim", [])


@needs_ffmpeg
def test_transcribe_success_offsets_usage(tmp_path):
    srv = FakeGemini()
    try:
        eng = GeminiEngine(settings(tmp_path, srv.url))
        assert eng.available() == (True, "")
        prog = []
        out = eng.transcribe(AUDIO, req(on_progress=prog.append))
        assert [s["start"] for s in out.segments] == [600.0, 604.5]
        assert out.segments[1]["text"].startswith("Hozirda olib")
        assert out.meta["model"] == "gemini-3-flash-preview" and out.meta["output_tokens"] == 150
        body = srv.calls[0]["body"]
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
        assert "ILMHUB" in body["contents"][0]["parts"][1]["text"]
        assert prog == [12.0]
        assert not list(tmp_path.glob("stt-gem-*"))   # vaqtinchalik fayllar o'chirilgan
    finally:
        srv.close()


@needs_ffmpeg
def test_rate_limit_and_server_errors_retried(tmp_path):
    srv = FakeGemini(plan=["429", "500", "ok"])
    try:
        statuses = []
        out = GeminiEngine(settings(tmp_path, srv.url)).transcribe(AUDIO, req(on_status=lambda s, d: statuses.append(s)))
        assert len(out.segments) == 2 and len(srv.calls) == 3
        assert "rate_limited_wait" in statuses and "cloud_retry" in statuses
    finally:
        srv.close()


@needs_ffmpeg
def test_rate_limit_gives_up_after_max_wait(tmp_path):
    srv = FakeGemini(plan=["429"] * 50)
    try:
        eng = GeminiEngine(settings(tmp_path, srv.url, gemini_max_wait=3))
        with pytest.raises(EngineError) as e:
            eng.transcribe(AUDIO, req())
        assert e.value.code == "cloud_rate_limited"
    finally:
        srv.close()


@needs_ffmpeg
def test_model_fallback_and_thinking_retry(tmp_path):
    srv = FakeGemini(plan=["thinking400"], models=("gemini-2.5-flash",))
    try:
        out = GeminiEngine(settings(tmp_path, srv.url)).transcribe(AUDIO, req())
        assert out.meta["model"] == "gemini-2.5-flash"
        assert "thinkingConfig" not in srv.calls[-1]["body"]["generationConfig"]
    finally:
        srv.close()


@needs_ffmpeg
def test_invalid_key(tmp_path):
    srv = FakeGemini()
    try:
        eng = GeminiEngine(settings(tmp_path, srv.url, key="AIzaWRONG_key_000000000000"))
        assert eng.check_key("AIzaWRONG_key_000000000000")[1] == "cloud_auth_failed"
        with pytest.raises(EngineError) as e:
            eng.transcribe(AUDIO, req())
        assert e.value.code == "cloud_auth_failed"
        assert GeminiEngine(settings(tmp_path, srv.url, key="")).available() == (False, "api_key_missing")
    finally:
        srv.close()


def test_disabled_api_and_old_key_format(tmp_path):
    from app.api.settings_api import _KEY_RE
    assert _KEY_RE.match("AIzaSyA1b2C3d4E5f6G7h8I9j0KlMnOpQrStUv") and _KEY_RE.match(GOOD_KEY)
    assert not _KEY_RE.match("bad key with spaces") and not _KEY_RE.match("short")

    class R:
        status_code = 403
        text = ""

        def json(self):
            return {"error": {"code": 403, "message": "Generative Language API has not been used in project 1 "
                                                      "before or it is disabled.", "status": "PERMISSION_DENIED",
                              "details": [{"reason": "SERVICE_DISABLED"}]}}

    class S:
        def get(self, *a, **k):
            return R()
    eng = GeminiEngine(settings(tmp_path, "http://x"), session=S())
    ok, code, detail = eng.check_key(GOOD_KEY)
    assert not ok and code == "cloud_api_disabled" and "disabled" in detail[0]


def test_cost_estimate():
    s = Settings()
    assert estimate_cost("gemini-3-flash-preview", 115_200, 25_000, s) == pytest.approx(0.1902, abs=1e-3)
    assert estimate_cost("gemini-2.5-flash-lite", 1_000_000, 0, s) == pytest.approx(0.30)


@needs_ffmpeg
def test_api_key_via_settings_and_full_job(make_server, media):
    srv_g = FakeGemini()
    try:
        srv = make_server(GEMINI_BASE_URL=srv_g.url, CHUNK_MINUTES="2")
        cfg = requests.get(srv.url + "/api/v1/config").json()
        g = [e for e in cfg["engines"] if e["id"] == "gemini"][0]
        assert g["available"] is False and g["key_set"] is False
        r = requests.post(srv.url + "/api/v1/settings/gemini", json={"api_key": "AIzaWRONG_key_000000000000"})
        assert r.status_code == 400 and r.json()["error"] == "cloud_auth_failed"
        assert requests.post(srv.url + "/api/v1/settings/gemini", json={"api_key": "x"}).json()["error"] == \
            "invalid_key_format"
        r = requests.post(srv.url + "/api/v1/settings/gemini", json={"api_key": GOOD_KEY})
        assert r.status_code == 200 and r.json()["available"] is True and r.json()["key_hint"] == "…cdef"
        # nusxalashda qo'shilib qolgan bo'shliq/qator va qo'shtirnoqlar tozalanadi
        r2 = requests.post(srv.url + "/api/v1/settings/gemini", json={"api_key": f'  "{GOOD_KEY}"\n'})
        assert r2.status_code == 200
        assert f"GEMINI_API_KEY={GOOD_KEY}" in (srv.data_dir / "test.env").read_text()
        cfg = requests.get(srv.url + "/api/v1/config").json()
        assert [e for e in cfg["engines"] if e["id"] == "gemini"][0]["available"] is True
        # 4 daqiqalik fayl -> 2 bo'lak -> 2 ta Gemini so'rovi
        j = srv.upload(media["long4"], language="uz", engine="gemini", vocabulary="ILMHUB").json()
        done = srv.wait(j["job_id"], j["token"], timeout=120)
        assert done["status"] == "completed", done
        res = requests.get(f"{srv.url}/api/v1/jobs/{j['job_id']}/result", headers={"x-job-token": j["token"]}).json()
        assert res["model"].startswith("Google gemini-3-flash-preview")
        assert res["cloud_usage"]["input_tokens"] == 3900 * len(srv_g.calls) and res["cloud_usage"]["cost_usd"] > 0
        assert "Assalomu alaykum, hurmatli ustozlar." in res["latin_text"]
        assert len(srv_g.calls) >= 2
        starts = [s["start"] for s in res["segments"]]
        assert starts == sorted(starts) and starts[-1] > 100   # ikkinchi bo'lak offset bilan
        # kalitni o'chirish
        assert requests.delete(srv.url + "/api/v1/settings/gemini").json()["key_set"] is False
        assert "GEMINI_API_KEY" not in (srv.data_dir / "test.env").read_text()
    finally:
        srv_g.close()


@needs_ffmpeg
def test_settings_blocked_when_proxied(make_server):
    srv = make_server(TRUST_PROXY="1")
    r = requests.post(srv.url + "/api/v1/settings/gemini", json={"api_key": GOOD_KEY},
                      headers={"X-Forwarded-For": "8.8.8.8"})
    assert r.status_code == 403 and r.json()["error"] == "settings_local_only"
