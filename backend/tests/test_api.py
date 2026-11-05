"""To'liq API integratsiya testi: haqiqiy server jarayoni + haqiqiy FFmpeg + demo dvigatel."""
import time

import pytest
import requests

from .conftest import needs_ffmpeg

pytestmark = needs_ffmpeg


def H(token):
    return {"x-job-token": token}


@pytest.mark.parametrize("key", ["mp3", "wav", "m4a", "ogg", "opus", "flac", "aac", "webm", "video_mp4",
                                 "video_mov"])
def test_full_flow_each_format(server, media, key):
    r = server.upload(media[key], language="uz")
    assert r.status_code == 201, r.text
    j = r.json()
    done = server.wait(j["job_id"], j["token"])
    assert done["status"] == "completed", done
    assert done["progress"] == 100.0
    res = requests.get(f"{server.url}/api/v1/jobs/{j['job_id']}/result", headers=H(j["token"])).json()
    assert res["raw_text"] and res["latin_text"] and res["edited_text"] == res["latin_text"]
    assert res["segments"][0]["words"]
    txt = requests.get(f"{server.url}/api/v1/jobs/{j['job_id']}/export?format=txt", headers=H(j["token"]))
    assert txt.headers["content-type"].startswith("text/plain") and "charset=utf-8" in txt.headers["content-type"]
    assert "attachment" in txt.headers["content-disposition"]
    assert "o‘" in txt.content.decode("utf-8")


def test_options_reach_engine(server, media):
    r = server.upload(media["mp3"], language="kk", script="original", mode="verbatim", punctuation="false",
                      paragraphs="false", quality="fast", vocabulary="ILMHUB, Samarqand").json()
    job = requests.get(f"{server.url}/api/v1/jobs/{r['job_id']}", headers=H(r["token"])).json()
    assert job["options"] == {"language": "kk", "script": "original", "mode": "verbatim", "punctuation": False,
                              "paragraphs": False, "spellfix": True, "ai_proofread": False, "quality": "fast", "engine": "dummy",
                              "vocabulary": "ILMHUB, Samarqand"}
    server.wait(r["job_id"], r["token"])
    res = requests.get(f"{server.url}/api/v1/jobs/{r['job_id']}/result", headers=H(r["token"])).json()
    assert "Домла" in res["latin_text"]           # asl yozuv saqlangan
    assert "," not in res["latin_text"]            # tinish belgilari o'chirilgan
    assert " ee " in f" {res['latin_text'].lower()} "  # so'zma-so'z: "ee" saqlangan


def test_errors_are_clear(server, media):
    for key, code in (("pdf", "unsupported_format"), ("fake_mp3", "unsupported_format"),
                      ("noaudio", "no_audio_track")):
        r = server.upload(media[key])
        assert r.status_code == 422 and r.json()["error"] == code
    r = server.upload(media["mp3"], language="fr")
    assert r.status_code == 400 and r.json()["error"] == "invalid_language"
    r = requests.post(server.url + "/api/v1/jobs", data={"language": "uz"})
    assert r.status_code == 415
    r = requests.post(server.url + "/api/v1/jobs", files={"x": ("a", b"1")})
    assert r.json()["error"] == "file_missing"
    # rad etilgan yuklamalardan diskda hech narsa qolmaydi
    assert list((server.data_dir / "jobs").iterdir()) == []


def test_token_required_and_isolated(server, media):
    a = server.upload(media["mp3"]).json()
    b = server.upload(media["mp3"]).json()
    url = f"{server.url}/api/v1/jobs/{a['job_id']}"
    assert requests.get(url).status_code == 404
    assert requests.get(url, headers=H(b["token"])).status_code == 404   # boshqa ishning tokeni
    assert requests.get(url, headers=H(a["token"])).status_code == 200
    assert requests.get(f"{server.url}/api/v1/jobs/../../etc/passwd").status_code in (404,)
    assert requests.get(f"{server.url}/api/v1/jobs/zzz", headers=H(a["token"])).status_code == 404


def test_edit_export_delete(server, media):
    j = server.upload(media["mp3"]).json()
    server.wait(j["job_id"], j["token"])
    base = f"{server.url}/api/v1/jobs/{j['job_id']}"
    new = "Tahrirlangan matn: o‘zbekcha g‘alaba, ma’no.\r\nIkkinchi qator."
    r = requests.patch(base + "/result", json={"edited_text": new}, headers=H(j["token"]))
    assert r.status_code == 200
    res = requests.get(base + "/result", headers=H(j["token"])).json()
    assert res["edited_text"] == new.replace("\r\n", "\n")
    assert res["raw_text"] != res["edited_text"] and res["latin_text"] != res["edited_text"]
    txt = requests.get(base + "/export?format=txt", headers=H(j["token"])).content.decode("utf-8")
    assert txt == new.replace("\r\n", "\n") + "\n"
    for fmt in ("srt", "vtt", "txt_ts", "json"):
        assert requests.get(base + f"/export?format={fmt}", headers=H(j["token"])).status_code == 200
    assert requests.get(base + "/export?format=exe", headers=H(j["token"])).status_code == 400
    audio = requests.get(base + "/audio", params={"token": j["token"]}, headers={"Range": "bytes=0-99"})
    assert audio.status_code == 206 and len(audio.content) == 100
    assert requests.delete(base, headers=H(j["token"])).json()["deleted"]
    assert requests.get(base, headers=H(j["token"])).status_code == 404
    assert not (server.data_dir / "jobs" / j["job_id"]).exists()


def test_cancel_running_job(make_server, media):
    srv = make_server(DUMMY_SPEED="3")
    j = srv.upload(media["long4"]).json()
    srv.wait(j["job_id"], j["token"], until=("transcribing",))
    r = requests.post(f"{srv.url}/api/v1/jobs/{j['job_id']}/cancel", headers=H(j["token"]))
    assert r.json()["status"] == "cancelling"
    done = srv.wait(j["job_id"], j["token"], timeout=30)
    assert done["status"] == "cancelled"


def test_queue_positions(make_server, media):
    srv = make_server(DUMMY_SPEED="5")
    jobs = [srv.upload(media["mp3"]).json() for _ in range(3)]
    third = requests.get(f"{srv.url}/api/v1/jobs/{jobs[2]['job_id']}", headers=H(jobs[2]["token"])).json()
    assert third["status"] == "queued" and third["queue_position"] in (1, 2)
    for j in jobs:
        assert srv.wait(j["job_id"], j["token"], timeout=60)["status"] == "completed"


def test_limits(make_server, media, tmp_path):
    srv = make_server(MAX_DURATION_MIN="3", MAX_UPLOAD_MB="1", MAX_QUEUED_JOBS="50")
    r = srv.upload(media["long4"])  # 4 daqiqa > 3, lekin <1MB
    assert r.status_code == 422 and r.json() == {"error": "too_long", "max_minutes": 3}
    big = tmp_path / "big.wav"
    big.write_bytes(media["wav"].read_bytes() * 3)  # ~1.9 MB
    r = srv.upload(big)
    assert r.status_code == 413 and r.json()["error"] == "file_too_large"


def test_server_busy(make_server, media):
    srv = make_server(MAX_QUEUED_JOBS="1", DUMMY_SPEED="2")
    srv.upload(media["long4"])
    time.sleep(1.0)
    srv.upload(media["mp3"])      # navbatda 1 ta
    r = srv.upload(media["mp3"])
    assert r.status_code == 503 and r.json()["error"] == "server_busy"


def test_rate_limit(make_server, media):
    srv = make_server(RATE_LIMIT_PER_HOUR="2")
    assert srv.upload(media["mp3"]).status_code == 201
    assert srv.upload(media["mp3"]).status_code == 201
    r = srv.upload(media["mp3"])
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"


def test_access_key(make_server, media):
    srv = make_server(APP_ACCESS_KEY="maxfiy-kalit")
    cfg = requests.get(srv.url + "/api/v1/config").json()
    assert cfg["requires_access_key"] is True
    assert srv.upload(media["mp3"]).status_code == 401
    r = srv.upload(media["mp3"], headers={"x-access-key": "maxfiy-kalit"})
    assert r.status_code == 201


def test_resume_after_crash(make_server, media):
    """Server ish o'rtasida to'satdan o'chsa, qayta yoqilganda ish davom etib tugaydi."""
    srv = make_server(DUMMY_SPEED="20", CHUNK_MINUTES="2")
    j = srv.upload(media["long4"]).json()
    end = time.time() + 30
    while time.time() < end:
        st = requests.get(f"{srv.url}/api/v1/jobs/{j['job_id']}", headers=H(j["token"])).json()
        if st["status"] == "transcribing" and st["progress"] > 60:
            break
        time.sleep(0.1)
    srv.stop(kill=True)
    chunk_files = list((srv.data_dir / "jobs" / j["job_id"]).glob("chunk_*.json"))
    assert chunk_files, "kamida bitta bo'lak saqlangan bo'lishi kerak"
    srv.start()
    done = srv.wait(j["job_id"], j["token"], timeout=60)
    assert done["status"] == "completed"
    res = requests.get(f"{srv.url}/api/v1/jobs/{j['job_id']}/result", headers=H(j["token"])).json()
    starts = [s["start"] for s in res["segments"]]
    assert starts == sorted(starts) and len(starts) == len(set(starts))  # takror yo'q
    assert res["segments"][-1]["end"] > 230


def test_security_headers_and_spa(server):
    r = requests.get(server.url + "/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert requests.get(server.url + "/api/v1/nope").status_code == 404
