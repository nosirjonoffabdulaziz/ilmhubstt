"""Soxta Google Gemini REST serveri — brauzer rejimini (BYOK) internet va haqiqiy kalitsiz sinash uchun.

Haqiqiy API shaklini takrorlaydi: GET /v1beta/models, Files API (resumable yuklash), files/{id},
POST models/{m}:streamGenerateContent?alt=sse (SSE oqim). CORS sarlavhalari Google'nikiga o'xshash.

Ishga tushirish:  python scripts/fake_gemini.py --port 8765
Brauzerda:       localStorage.setItem("ilmhubstt.geminiBase", "http://127.0.0.1:8765")
Kalit:           AQ.test-key-1234567890abcdef
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

GOOD_KEY = "AQ.test-key-1234567890abcdef"
YT_DURATION = 1500   # soxta YouTube videosi: 25 daqiqa
FILE_DURATION = 2400  # yuklangan fayl: 40 daqiqa (inline bo'lsa ham)
LINES_PER_RESPONSE = 30  # shundan keyin MAX_TOKENS (uzun yozuvni bo'lib yozishni sinash)
STEP = 20
FAIL_MODELS: set[str] = set()  # shu modellar doim 503 qaytaradi (zaxira modelga o'tishni sinash)
CHUNK_DELAY = 0.03  # SSE bo'laklari orasidagi kutish (testda sekinlashtirish uchun)

STATE = {"files": {}, "sessions": {}, "requests": [], "rate_limit_once": True, "polls": {}}
LOCK = threading.Lock()


def clock(s: float) -> str:
    s = int(s)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def parse_clock(v: str) -> int:
    p = [int(x) for x in v.split(":")]
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]


def secs(v) -> float | None:
    if v is None:
        return None
    return float(str(v).rstrip("s"))


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Expose-Headers", "x-goog-upload-url, x-goog-upload-status")

    def send_json(self, code: int, obj, extra: dict | None = None):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def key_ok(self) -> bool:
        if self.headers.get("x-goog-api-key") == GOOD_KEY:
            return True
        self.send_json(400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                                       "status": "INVALID_ARGUMENT",
                                       "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]}})
        return False

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/__state":
            return self.send_json(200, {"requests": STATE["requests"], "files": list(STATE["files"])})
        if not self.key_ok():
            return
        if path == "/v1beta/models":
            return self.send_json(200, {"models": [
                {"name": "models/gemini-3-flash-preview", "supportedGenerationMethods": ["generateContent", "countTokens"]},
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-2.5-flash-preview-tts", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]},
            ]})
        m = re.match(r"^/v1beta/(files/[\w-]+)$", path)
        if m:
            f = STATE["files"].get(m.group(1))
            if not f:
                return self.send_json(404, {"error": {"code": 404, "message": "File not found", "status": "NOT_FOUND"}})
            with LOCK:
                STATE["polls"][m.group(1)] = STATE["polls"].get(m.group(1), 0) + 1
                if STATE["polls"][m.group(1)] >= 1:
                    f["state"] = "ACTIVE"
            return self.send_json(200, f)
        self.send_json(404, {"error": {"code": 404, "message": "not found"}})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if not self.key_ok():
            return
        STATE["files"].pop(path.replace("/v1beta/", ""), None)
        self.send_json(200, {})

    def do_POST(self):
        u = urlparse(self.path)
        path = u.path
        if path == "/upload/v1beta/files":
            if not self.key_ok():
                return
            meta = json.loads(self.body() or b"{}")
            sid = uuid.uuid4().hex
            STATE["sessions"][sid] = {"size": int(self.headers.get("X-Goog-Upload-Header-Content-Length") or 0),
                                      "mime": self.headers.get("X-Goog-Upload-Header-Content-Type"), "got": 0,
                                      "name": (meta.get("file") or {}).get("display_name", "")}
            host = self.headers.get("Host")
            return self.send_json(200, {}, {"x-goog-upload-url": f"http://{host}/upload-session/{sid}",
                                            "x-goog-upload-status": "active"})
        m = re.match(r"^/upload-session/(\w+)$", path)
        if m:
            sess = STATE["sessions"].get(m.group(1))
            data = self.body()
            if not sess:
                return self.send_json(404, {"error": {"code": 404, "message": "session"}})
            off = int(self.headers.get("X-Goog-Upload-Offset") or 0)
            if off != sess["got"]:
                return self.send_json(400, {"error": {"code": 400, "message": "bad offset"}})
            sess["got"] += len(data)
            cmd = self.headers.get("X-Goog-Upload-Command", "")
            if "finalize" in cmd:
                fid = "files/" + uuid.uuid4().hex[:12]
                host = self.headers.get("Host")
                f = {"name": fid, "uri": f"http://{host}/v1beta/{fid}", "mimeType": sess["mime"], "state": "PROCESSING",
                     "sizeBytes": str(sess["got"]), "displayName": sess["name"]}
                STATE["files"][fid] = f
                return self.send_json(200, {"file": f}, {"x-goog-upload-status": "final"})
            return self.send_json(200, {}, {"x-goog-upload-status": "active"})
        m = re.match(r"^/v1beta/models/([\w.\-]+):streamGenerateContent$", path)
        if m:
            if not self.key_ok():
                return
            return self.generate(m.group(1), json.loads(self.body() or b"{}"))
        self.send_json(404, {"error": {"code": 404, "message": "not found"}})

    # ---------------- generateContent ----------------
    def generate(self, model: str, req: dict):
        parts = req["contents"][0]["parts"]
        gen = req.get("generationConfig", {})
        text = "\n".join(p.get("text", "") for p in parts if "text" in p)
        media = next((p for p in parts if "fileData" in p or "inlineData" in p or "file_data" in p), None)
        with LOCK:
            STATE["requests"].append({"model": model, "media": {k: v for k, v in (media or {}).items() if k != "inlineData"},
                                      "inline_bytes": len((media or {}).get("inlineData", {}).get("data", "")),
                                      "json": gen.get("responseMimeType"), "prompt_head": text[:160]})
            first = STATE["rate_limit_once"]
            STATE["rate_limit_once"] = False
        if model in FAIL_MODELS:
            return self.send_json(503, {"error": {"code": 503, "message": "The model is overloaded. Please try again later.", "status": "UNAVAILABLE"}})
        if first:
            return self.send_json(429, {"error": {"code": 429, "message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED",
                                                  "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "1s"}]}})
        if gen.get("responseMimeType") == "application/json":
            return self.stream([json.dumps(SUMMARY, ensure_ascii=False)], "STOP", {"promptTokenCount": 9000, "candidatesTokenCount": 1500})
        fd = (media or {}).get("fileData") or {}
        uri = fd.get("fileUri", "")
        youtube = "youtube.com" in uri
        if youtube and "BADVIDEO" in uri:
            return self.send_json(400, {"error": {"code": 400, "message": "The YouTube video is not available (private).", "status": "INVALID_ARGUMENT"}})
        duration = YT_DURATION if youtube else FILE_DURATION
        vm = (media or {}).get("videoMetadata") or {}
        start = secs(vm.get("startOffset")) or 0.0
        end = secs(vm.get("endOffset"))
        clipped = (not youtube) and end is not None
        if not clipped:
            cont = re.search(r"Continue from (\d\d:\d\d:\d\d)", text)
            start = parse_clock(cont.group(1)) if cont else 0
            end = duration
        else:
            end = min(end, duration)
        lines = []
        t = start
        i = int(start // STEP)
        while t < end and len(lines) < LINES_PER_RESPONSE + 1:
            ts = (t - start) if clipped else t
            word = "Ma’lumot" if i % 7 else "[eshitilmadi] so‘z"
            lines.append(f"[{clock(ts)}] Bu {i}-gap: o‘zbekcha nutq sinovi, {word} va g‘oya.")
            if i % 5 == 4:
                lines.append("")
            t += STEP
            i += 1
        finish = "STOP"
        if len(lines) > LINES_PER_RESPONSE:
            lines = lines[:LINES_PER_RESPONSE]
            lines[-1] = lines[-1][: len(lines[-1]) // 2]  # yarim qolgan satr
            finish = "MAX_TOKENS"
        out = "\n".join(lines)
        audio_tokens = int(((end - start) if clipped else duration) * 32)
        usage = {"promptTokenCount": audio_tokens + 400, "candidatesTokenCount": len(out) // 3,
                 "promptTokensDetails": [{"modality": "AUDIO", "tokenCount": audio_tokens}, {"modality": "TEXT", "tokenCount": 400}]}
        chunks = [out[k:k + 200] for k in range(0, len(out), 200)] or [""]
        self.stream(chunks, finish, usage)

    def stream(self, chunks: list[str], finish: str, usage: dict):
        self.send_response(200)
        self.cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for n, c in enumerate(chunks):
            ev = {"candidates": [{"content": {"role": "model", "parts": [{"text": c}]}}]}
            if n == len(chunks) - 1:
                ev["candidates"][0]["finishReason"] = finish
                ev["usageMetadata"] = usage
            try:
                self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\r\n\r\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break  # brauzer so'rovni bekor qildi
            time.sleep(CHUNK_DELAY)
        self.close_connection = True


SUMMARY = {
    "title": "O‘zbekcha nutq sinovi", "genre": "Podkast", "overview": "Yozuvda o‘zbekcha nutqni matnga aylantirish sinovi haqida gap boradi.",
    "audience": "Dasturchilar va jurnalistlar", "main_idea": "Aniq transkripsiya vaqtni tejaydi.",
    "sections": [{"start": "00:00:00", "title": "Kirish", "summary": "Mavzu tanishtiriladi."},
                 {"start": "00:10:00", "title": "Asosiy qism", "summary": "Misollar keltiriladi."}],
    "key_points": ["Matn vaqt belgilari bilan yoziladi", "Noaniq joylar belgilanadi"],
    "facts": [{"fact": "Yozuv 25 daqiqa davom etadi", "time": "00:00:20", "check": False},
              {"fact": "Aniqlik 95% deb aytildi", "time": "00:05:00", "check": True}],
    "real_life": [{"idea": "Ma’ruzalarni yozib olish", "how": "Talaba darsni yozib, keyin matnini o‘qiydi"}],
    "actions": [{"step": "Ovozli yozuvlaringizni matnga aylantiring", "why": "Qidirish oson bo‘ladi", "when": "Bugun"}],
    "quotes": [{"text": "Bu 3-gap: o‘zbekcha nutq sinovi", "time": "00:01:00", "speaker": ""}],
    "terms": [{"term": "Transkripsiya", "meaning": "Nutqni yozma matnga aylantirish"}],
    "questions": ["Siz qaysi yozuvlarni matnga aylantirgan bo‘lardingiz?"],
    "conclusion": "Sinov muvaffaqiyatli o‘tdi.",
}


def serve(port: int) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    serve(a.port)
    print(f"Soxta Gemini: http://127.0.0.1:{a.port}  (kalit: {GOOD_KEY})")
    while True:
        time.sleep(3600)
