"""Umumiy test vositalari: FFmpeg bilan haqiqiy media fayllar yasash va serverni ishga tushirish."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg o'rnatilmagan")


def ff(*args: str) -> None:
    subprocess.run([FFMPEG, "-v", "error", "-y", *args], check=True)


# Nutqqa o'xshash signal: pauzalar bilan almashinuvchi tovush
SPEECHY = "aevalsrc='0.4*sin(2*PI*(180+40*sin(2*PI*0.7*t))*t)*gt(sin(2*PI*0.25*t),-0.3)':s=16000:d={d}"


@pytest.fixture(scope="session")
def media(tmp_path_factory) -> dict[str, Path]:
    if FFMPEG is None:
        pytest.skip("FFmpeg yo'q")
    d = tmp_path_factory.mktemp("media")
    src = d / "src.wav"
    ff("-f", "lavfi", "-i", SPEECHY.format(d=20), "-ac", "1", str(src))
    files = {"wav": src}
    specs = {
        "mp3": ["-c:a", "libmp3lame", "-b:a", "64k"],
        "m4a": ["-c:a", "aac", "-b:a", "64k"],
        "ogg": ["-c:a", "libvorbis"],
        "opus": ["-c:a", "libopus", "-b:a", "32k"],
        "flac": ["-c:a", "flac"],
        "aac": ["-c:a", "aac", "-f", "adts"],
        "webm": ["-c:a", "libopus"],
    }
    for ext, args in specs.items():
        out = d / f"sample.{ext}"
        ff("-i", str(src), *args, str(out))
        files[ext] = out
    for ext, vcodec in (("mp4", "libx264"), ("mov", "libx264"), ("mkv", "libx264")):
        out = d / f"video.{ext}"
        try:
            ff("-f", "lavfi", "-i", "color=c=blue:s=160x120:d=20", "-i", str(src), "-shortest",
               "-c:v", vcodec, "-pix_fmt", "yuv420p", "-c:a", "aac", str(out))
        except subprocess.CalledProcessError:
            ff("-f", "lavfi", "-i", "color=c=blue:s=160x120:d=20", "-i", str(src), "-shortest",
               "-c:v", "mpeg4", "-c:a", "aac", str(out))
        files[f"video_{ext}"] = out
    noaudio = d / "noaudio.mp4"
    try:
        ff("-f", "lavfi", "-i", "color=c=red:s=160x120:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(noaudio))
    except subprocess.CalledProcessError:
        ff("-f", "lavfi", "-i", "color=c=red:s=160x120:d=3", "-c:v", "mpeg4", str(noaudio))
    files["noaudio"] = noaudio
    pdf = d / "hujjat.pdf"
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    files["pdf"] = pdf
    fake = d / "virus.mp3"
    fake.write_bytes(b"MZ" + os.urandom(4000))
    files["fake_mp3"] = fake
    long4 = d / "long4min.mp3"
    ff("-f", "lavfi", "-i", SPEECHY.format(d=240), "-c:a", "libmp3lame", "-b:a", "32k", str(long4))
    files["long4"] = long4
    return files


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, data_dir: Path, **env):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.data_dir = data_dir
        self.env = {**os.environ, "DATA_DIR": str(data_dir), "PORT": str(self.port),
                    "ENABLE_DUMMY_ENGINE": "1", "ASR_ENGINE": "dummy", "DUMMY_SPEED": "400",
                    "RATE_LIMIT_PER_HOUR": "0", "ENV_FILE": str(data_dir / "test.env"), "GEMINI_API_KEY": "",
                    "OLLAMA_URL": "http://127.0.0.1:9", **{k: str(v) for k, v in env.items()}}
        self.proc = None
        self.log = data_dir / "server.log"

    def start(self) -> "Server":
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.log, "ab")
        self.proc = subprocess.Popen([sys.executable, "run.py"], cwd=BACKEND, env=self.env,
                                     stdout=self._fh, stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                if requests.get(self.url + "/api/v1/health", timeout=1).status_code == 200:
                    return self
            except requests.RequestException:
                pass
            time.sleep(0.1)
        raise RuntimeError("server ishga tushmadi:\n" + self.log.read_text(errors="replace"))

    def stop(self, kill: bool = False) -> None:
        if self.proc and self.proc.poll() is None:
            if kill:
                self.proc.kill()
            else:
                self.proc.terminate()
            self.proc.wait(timeout=15)
        self._fh.close()

    # yordamchilar
    def upload(self, path: Path, headers=None, **fields):
        with open(path, "rb") as fh:
            return requests.post(self.url + "/api/v1/jobs", files={"file": (path.name, fh)},
                                 data=fields, headers=headers or {}, timeout=120)

    def wait(self, job_id: str, token: str, timeout: float = 120, until=("completed", "failed", "cancelled")) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            j = requests.get(f"{self.url}/api/v1/jobs/{job_id}", headers={"x-job-token": token}, timeout=10).json()
            if j.get("status") in until:
                return j
            time.sleep(0.2)
        raise TimeoutError(j)


@pytest.fixture
def server(tmp_path):
    srv = Server(tmp_path / "data").start()
    yield srv
    srv.stop()


@pytest.fixture
def make_server(tmp_path):
    started = []

    def _make(**env):
        srv = Server(tmp_path / f"data{len(started)}", **env).start()
        started.append(srv)
        return srv
    yield _make
    for s in started:
        s.stop()
