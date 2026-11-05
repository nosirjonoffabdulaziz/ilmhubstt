"""Lokal AI muharrir (Ollama) testlari — soxta Ollama HTTP serveri bilan."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from app.services.llm_proofread import OllamaProofreader, proofread_segments, rebuild_text, remap

from .conftest import needs_ffmpeg

FIXES = {"khafsizligini": "xavfsizligini", "tamillash": "ta’minlash", "dogrisida": "to‘g‘risida",
         "kyuzgi": "kuzgi", "tatil": "ta’til", "ukuchinin": "o‘quvchining", "vasagligi": "salomatligi",
         "majburiyat": "Majburiyatnoma", "noma": "", "farzandim": "farzandimning", "nin": ""}


def fake_llm(text: str, mode: str) -> str:
    words = []
    for w in text.split():
        core = w.strip(".,").lower()
        tail = w[len(w.rstrip(".,")):]
        if core in FIXES:
            if FIXES[core]:
                words.append(FIXES[core] + tail)
            elif words and tail:
                words[-1] += tail
        else:
            words.append(w)
    out = " ".join(words)
    if mode == "hallucinate":
        return out + " Bu juda muhim hujjat bo‘lib, uni har bir ota-ona imzolashi shart va majburiydir."
    if mode == "cyrillic":
        return "Мажбуриятнома " + out
    if mode == "prefix":
        return "Tuzatilgan matn: «" + out + "»"
    if mode == "numbers":
        return out.replace("3", "4")
    return out


class FakeOllama:
    def __init__(self, mode="good", models=("gemma3:12b",)):
        self.mode = mode
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
                if self.path == "/api/tags":
                    self._send({"models": [{"name": m, "model": m} for m in outer.models]})
                else:
                    self._send({}, 404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.calls.append(body)
                user = body["messages"][-1]["content"]
                self._send({"message": {"role": "assistant", "content": fake_llm(user, outer.mode)}})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def ollama():
    srv = FakeOllama()
    yield srv
    srv.close()


def segs_from(text, per=6, start=0.0):
    words = text.split()
    segs = []
    t = start
    for k in range(0, len(words), per):
        chunk = words[k:k + per]
        ws = [{"t": w, "s": round(t + i * 0.5, 2), "e": round(t + i * 0.5 + 0.4, 2), "p": 0.9, "u": False}
              for i, w in enumerate(chunk)]
        segs.append({"id": len(segs), "start": ws[0]["s"], "end": ws[-1]["e"], "text": " ".join(chunk),
                     "para": k == 0, "words": ws})
        t += len(chunk) * 0.5 + 0.3
    return segs


TEXT = "Majburiyat noma kyuzgi tatil davrida ukuchinin hayoti, vasagligi, khafsizligini tamillash dogrisida."


def test_status(ollama):
    pr = OllamaProofreader(ollama.url, "gemma3:12b")
    assert pr.status() == {"available": True, "model": "gemma3:12b", "reason": ""}
    assert OllamaProofreader(ollama.url, "qwen3:8b").status()["reason"] == "model_not_pulled"
    assert OllamaProofreader("http://127.0.0.1:9", "x").status()["reason"] == "ollama_not_running"


def test_proofread_and_remap_keeps_timings(ollama):
    pr = OllamaProofreader(ollama.url, "gemma3:12b")
    segs = segs_from(TEXT)
    st = proofread_segments(pr, segs, "uz", "ILMHUB")
    assert st["accepted"] == 1 and st["rejected"] == 0 and st["changed_words"] >= 8
    text = rebuild_text(segs)
    assert text == ("Majburiyatnoma kuzgi ta’til davrida o‘quvchining hayoti, salomatligi, xavfsizligini "
                    "ta’minlash to‘g‘risida.")
    first = segs[0]["words"][0]
    assert first["t"] == "Majburiyatnoma" and first["c"] == "Majburiyat" and first["ai"] and first["s"] == 0.0
    w = [x for s in segs for x in s["words"] if x["t"] == "salomatligi,"][0]
    assert w["c"] == "vasagligi," and w["s"] > 0
    # vaqtlar tartibi saqlangan
    starts = [x["s"] for s in segs for x in s["words"]]
    assert starts == sorted(starts)
    sys_prompt = ollama.calls[0]["messages"][0]["content"]
    assert "o‘zbek" in sys_prompt and "ILMHUB" in sys_prompt
    assert ollama.calls[0]["options"]["temperature"] <= 0.2


@pytest.mark.parametrize("mode,reason", [("hallucinate", "length"), ("cyrillic", "script"), ("numbers", "numbers")])
def test_unsafe_answers_rejected(mode, reason):
    srv = FakeOllama(mode)
    try:
        pr = OllamaProofreader(srv.url, "gemma3:12b")
        segs = segs_from(TEXT + " 3 ta band bor.")
        before = rebuild_text(segs)
        st = proofread_segments(pr, segs, "uz")
        assert st["rejected"] == 1 and st["reasons"] == {reason: 1}
        assert rebuild_text(segs) == before        # asl matn o'zgarmadi
    finally:
        srv.close()


def test_prefix_and_quotes_cleaned():
    srv = FakeOllama("prefix")
    try:
        segs = segs_from(TEXT)
        st = proofread_segments(OllamaProofreader(srv.url, "gemma3:12b"), segs, "uz")
        assert st["accepted"] == 1
        assert rebuild_text(segs).startswith("Majburiyatnoma kuzgi")
    finally:
        srv.close()


def test_remap_insert_and_delete():
    segs = segs_from("bu bu juda yaxshi kitob ekan")
    remap(segs, [0], "Bu juda yaxshi, qiziqarli kitob ekan.")
    words = [w["t"] for w in segs[0]["words"]]
    assert " ".join(words) == "Bu juda yaxshi, qiziqarli kitob ekan."
    assert len(words) == 5   # takror "bu" o'chirildi, "qiziqarli" oldingi so'zga qo'shildi


def test_unreachable_stops_early():
    pr = OllamaProofreader("http://127.0.0.1:9", "gemma3:12b", timeout=2)
    segs = segs_from(TEXT * 3, per=5)
    st = proofread_segments(pr, segs, "uz")
    assert st.get("error") == "ollama_unreachable"


@needs_ffmpeg
def test_api_end_to_end_with_ai(make_server, media, tmp_path):
    srv_llm = FakeOllama()
    try:
        txt = tmp_path / "garbled.txt"
        txt.write_text(TEXT, encoding="utf-8")
        srv = make_server(OLLAMA_URL=srv_llm.url, OLLAMA_MODEL="gemma3:12b", DUMMY_TEXT_FILE=str(txt))
        cfg = requests.get(srv.url + "/api/v1/config").json()
        assert cfg["proofreader"]["available"] is True and cfg["proofreader"]["model"] == "gemma3:12b"
        j = srv.upload(media["mp3"], language="uz", ai_proofread="true").json()
        done = srv.wait(j["job_id"], j["token"], timeout=60)
        assert done["status"] == "completed", done
        res = requests.get(f"{srv.url}/api/v1/jobs/{j['job_id']}/result", headers={"x-job-token": j["token"]}).json()
        assert res["proofread"]["model"] == "gemma3:12b" and res["proofread"]["accepted"] >= 1
        assert "salomatligi" in res["latin_text"] and "salomatligi" in res["edited_text"]
        assert "vasagligi" in res["raw_text"]                      # xom matn saqlanadi
        assert res["pre_ai_text"] != res["latin_text"]
        assert any(w.get("ai") for s in res["segments"] for w in s["words"])
        # AI o'chiq bo'lsa chaqirilmaydi
        n = len(srv_llm.calls)
        j2 = srv.upload(media["mp3"], language="uz").json()
        srv.wait(j2["job_id"], j2["token"], timeout=60)
        assert len(srv_llm.calls) == n
    finally:
        srv_llm.close()


@needs_ffmpeg
def test_api_ai_unavailable_still_completes(make_server, media):
    srv = make_server(OLLAMA_URL="http://127.0.0.1:9")
    assert requests.get(srv.url + "/api/v1/config").json()["proofreader"]["available"] is False
    j = srv.upload(media["mp3"], language="uz", ai_proofread="true").json()
    done = srv.wait(j["job_id"], j["token"], timeout=60)
    assert done["status"] == "completed"
    res = requests.get(f"{srv.url}/api/v1/jobs/{j['job_id']}/result", headers={"x-job-token": j["token"]}).json()
    assert "proofread_unavailable" in res["warnings"]
