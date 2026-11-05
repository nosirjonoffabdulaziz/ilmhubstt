"""2 soatlik audio bilan yuklama testi (sekin: `pytest -m slow`).

Tekshiradi: yuklash, FFmpeg konvertatsiya vaqti, bo'laklarga bo'linish, progress faqat oshib borishi,
ETA, natijaning butun davomiylikni qamrashi, eksport va server xotirasi.
"""
import json
import os
import time

import pytest
import requests

from .conftest import SPEECHY, ff, needs_ffmpeg

pytestmark = [needs_ffmpeg, pytest.mark.slow]


def rss_mb(pid: int) -> float:
    try:
        with open(f"/proc/{pid}/status") as fh:
            for line in fh:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return -1


def test_two_hour_file(make_server, tmp_path):
    src = tmp_path / "ikki_soat.mp3"
    t = time.time()
    ff("-f", "lavfi", "-i", SPEECHY.format(d=7200), "-c:a", "libmp3lame", "-b:a", "48k", str(src))
    gen_s = time.time() - t
    srv = make_server(DUMMY_SPEED="4000", MAX_UPLOAD_MB="1024", MAX_DURATION_MIN="180")

    t0 = time.time()
    r = srv.upload(src, language="uz")
    upload_s = time.time() - t0
    assert r.status_code == 201, r.text
    j = r.json()
    assert abs(j["duration"] - 7200) < 2

    seen, stages = [], []
    while True:
        st = requests.get(f"{srv.url}/api/v1/jobs/{j['job_id']}", headers={"x-job-token": j["token"]}).json()
        seen.append(st["progress"])
        if not stages or stages[-1] != st["status"]:
            stages.append(st["status"])
        if st["status"] in ("completed", "failed", "cancelled"):
            break
        assert time.time() - t0 < 900
        time.sleep(0.2)
    total_s = time.time() - t0
    assert st["status"] == "completed", st
    assert seen == sorted(seen), "progress hech qachon orqaga qaytmasligi kerak"
    assert stages[-1] == "completed" and "transcribing" in stages

    res = requests.get(f"{srv.url}/api/v1/jobs/{j['job_id']}/result", headers={"x-job-token": j["token"]}).json()
    segs = res["segments"]
    assert segs[-1]["end"] > 7150
    starts = [s["start"] for s in segs]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)
    gaps = [b["start"] - a["end"] for a, b in zip(segs, segs[1:])]
    assert max(gaps) < 10, "bo'laklar orasida matn yo'qolmasligi kerak"
    txt = requests.get(f"{srv.url}/api/v1/jobs/{j['job_id']}/export?format=txt",
                       headers={"x-job-token": j["token"]}).content.decode("utf-8")
    assert len(txt) > 50_000
    report = {
        "audio_minutes": 120, "file_mb": round(src.stat().st_size / 1e6, 1), "generate_s": round(gen_s, 1),
        "upload_s": round(upload_s, 1), "total_pipeline_s": round(total_s, 1), "segments": len(segs),
        "words": res["stats"]["words"], "txt_chars": len(txt), "server_peak_rss_mb": round(rss_mb(srv.proc.pid), 0),
        "status_samples": len(seen),
    }
    out = os.environ.get("LONG_TEST_REPORT")
    if out:
        with open(out, "w") as fh:
            json.dump(report, fh, indent=2)
    print(report)
