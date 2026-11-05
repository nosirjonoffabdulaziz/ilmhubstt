"""FFmpeg/FFprobe bilan ishlash: haqiqiy formatni tekshirish, 16 kHz mono PCM tayyorlash,
pauzalarni topish va brauzer uchun yengil audio nusxa yaratish.

Xavfsizlik: faqat lokal fayl protokoli va ma'lum media konteynerlari ruxsat etiladi
(playlist/concat kabi boshqa fayllarga murojaat qiluvchi formatlar bloklanadi).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np

SAMPLE_RATE = 16000

INPUT_FORMATS = ",".join([
    "mov", "mp4", "m4a", "3gp", "3g2", "mj2", "matroska", "webm", "mp3", "wav", "w64", "ogg",
    "flac", "aac", "amr", "asf", "avi", "flv", "mpeg", "mpegts", "caf", "aiff", "au", "ape",
    "wv", "tta", "mpc", "ac3", "eac3", "dts", "dv", "rm", "voc",
])
_SAFE_INPUT = ["-protocol_whitelist", "file", "-format_whitelist", INPUT_FORMATS]
_IMAGE_CODECS = {"ansi", "png", "mjpeg", "bmp", "gif", "tiff", "webp", "jpeg2000", "text"}

_kwargs: dict = {}
if hasattr(subprocess, "CREATE_NO_WINDOW"):  # Windows'da qora oyna ochilmasin
    _kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]


class MediaError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class Cancelled(Exception):
    pass


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def check_tools() -> dict:
    return {"ffmpeg": ffmpeg_path() is not None, "ffprobe": ffprobe_path() is not None}


@lru_cache(maxsize=1)
def _encoders() -> str:
    exe = ffmpeg_path()
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True,
                             timeout=30, **_kwargs)
        return out.stdout
    except Exception:
        return ""


def preview_codec() -> tuple[str, str, str]:
    """(kodek, kengaytma, mime) — brauzerda ijro uchun yengil nusxa."""
    if "libmp3lame" in _encoders():
        return "libmp3lame", "mp3", "audio/mpeg"
    return "aac", "m4a", "audio/mp4"


def _fwd(path: Path) -> str:
    # "file:" prefiksi '-' yoki ':' bilan boshlanadigan nomlarni opsiya/protokol deb o'qilishidan saqlaydi
    return "file:" + str(path)


def probe(path: Path, timeout: int = 120) -> dict:
    exe = ffprobe_path()
    if not exe:
        raise MediaError("ffmpeg_missing", "FFprobe topilmadi")
    cmd = [exe, "-v", "error", *_SAFE_INPUT, "-print_format", "json", "-show_format", "-show_streams", _fwd(path)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **_kwargs)
    except subprocess.TimeoutExpired as exc:
        raise MediaError("unsupported_format", "ffprobe timeout") from exc
    if res.returncode != 0:
        raise MediaError("unsupported_format", res.stderr.strip()[:300])
    try:
        info = json.loads(res.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaError("unsupported_format", "ffprobe json") from exc

    streams = info.get("streams") or []
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    video = [s for s in streams if s.get("codec_type") == "video" and s.get("codec_name") not in _IMAGE_CODECS
             and not (s.get("disposition") or {}).get("attached_pic")]
    if not audio:
        raise MediaError("no_audio_track" if video else "unsupported_format")

    duration = _to_float((info.get("format") or {}).get("duration"))
    if duration <= 0:
        duration = max((_to_float(s.get("duration")) for s in audio), default=0.0)
    if duration <= 0:
        duration = _measure_duration(path)
    if duration <= 0.05:
        raise MediaError("empty_audio")
    return {
        "duration": duration,
        "format": (info.get("format") or {}).get("format_name", ""),
        "audio_codec": audio[0].get("codec_name", ""),
        "has_video": bool(video),
    }


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _measure_duration(path: Path) -> float:
    """Ba'zi fayllarda (masalan, oqim sifatida yozilgan webm) davomiylik sarlavhada bo'lmaydi."""
    exe = ffmpeg_path()
    if not exe:
        return 0.0
    cmd = [exe, "-nostdin", "-v", "error", *_SAFE_INPUT, "-i", _fwd(path), "-map", "0:a:0",
           "-f", "null", "-progress", "pipe:1", "-nostats", "-"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=900, **_kwargs)
    except subprocess.TimeoutExpired:
        return 0.0
    times = re.findall(r"out_time_us=(\d+)", res.stdout)
    return int(times[-1]) / 1e6 if times else 0.0


def convert(src: Path, wav_out: Path, preview_out: Path, duration: float,
            progress: Callable[[float], None] | None = None,
            cancelled: Callable[[], bool] | None = None) -> None:
    """Bitta FFmpeg chaqiruvida ikki natija: ASR uchun 16 kHz mono WAV va ijro uchun yengil nusxa."""
    exe = ffmpeg_path()
    if not exe:
        raise MediaError("ffmpeg_missing", "FFmpeg topilmadi")
    codec, _, _ = preview_codec()
    tmp_wav = wav_out.with_suffix(".part.wav")
    tmp_prev = preview_out.with_name(preview_out.stem + ".part" + preview_out.suffix)
    cmd = [
        exe, "-nostdin", "-y", "-v", "error", *_SAFE_INPUT, "-i", _fwd(src),
        "-map", "0:a:0", "-vn", "-sn", "-dn", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-c:a", "pcm_s16le", "-f", "wav", _fwd(tmp_wav),
        "-map", "0:a:0", "-vn", "-sn", "-dn", "-ac", "1", "-ar", "24000", "-c:a", codec, "-b:a", "48k",
        _fwd(tmp_prev),
        "-progress", "pipe:1", "-nostats",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", **_kwargs)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancelled and cancelled():
                proc.kill()
                raise Cancelled()
            if line.startswith("out_time_us=") and progress and duration > 0:
                try:
                    progress(min(1.0, int(line.split("=", 1)[1]) / 1e6 / duration))
                except ValueError:
                    pass
        proc.wait()
        err = proc.stderr.read() if proc.stderr else ""
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        for p in (tmp_wav, tmp_prev):
            p.unlink(missing_ok=True)
        raise MediaError("conversion_failed", err.strip()[:300])
    tmp_wav.replace(wav_out)
    tmp_prev.replace(preview_out)


def detect_silences(wav: Path, noise_db: int = -35, min_dur: float = 0.4) -> list[tuple[float, float]]:
    exe = ffmpeg_path()
    if not exe:
        return []
    cmd = [exe, "-nostdin", "-v", "info", "-i", _fwd(wav), "-af",
           f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                             encoding="utf-8", errors="replace", **_kwargs)
    except subprocess.TimeoutExpired:
        return []
    silences: list[tuple[float, float]] = []
    start = None
    for line in res.stderr.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and start is not None:
            silences.append((start, float(m.group(1))))
            start = None
    return silences


def wav_duration(wav: Path) -> float:
    with wave.open(str(wav), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def read_wav(wav: Path, start: float, end: float) -> np.ndarray:
    """WAV faylning bir qismini float32 massiv sifatida o'qish (butun 2 soatni xotiraga olmasdan)."""
    with wave.open(str(wav), "rb") as w:
        sr = w.getframerate()
        total = w.getnframes()
        a = max(0, int(start * sr))
        b = min(total, int(end * sr))
        if b <= a:
            return np.zeros(0, dtype=np.float32)
        w.setpos(a)
        raw = w.readframes(b - a)
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def waveform_peaks(wav: Path, bins: int = 400) -> list[float]:
    """Pleyer uchun yengil to'lqin shakli (0..1)."""
    try:
        with wave.open(str(wav), "rb") as w:
            total = w.getnframes()
            if total == 0:
                return []
            per = max(1, total // bins)
            peaks = []
            for _ in range(bins):
                raw = w.readframes(per)
                if not raw:
                    break
                arr = np.frombuffer(raw, dtype="<i2").astype(np.float32)
                peaks.append(float(np.sqrt(np.mean(arr * arr))) if arr.size else 0.0)
    except (wave.Error, OSError):
        return []
    top = max(peaks) if peaks else 0
    if top <= 0:
        return [0.0 for _ in peaks]
    return [round(min(1.0, p / top), 3) for p in peaks]


def encode_for_cloud(wav: Path, out: Path) -> Path:
    """Bulut servisiga yuborish uchun siqilgan nusxa (16 kHz mono Opus/Ogg)."""
    exe = ffmpeg_path()
    if not exe:
        raise MediaError("ffmpeg_missing")
    codec = "libopus" if "libopus" in _encoders() else "flac"
    if codec == "flac":
        out = out.with_suffix(".flac")
        args = ["-c:a", "flac"]
    else:
        args = ["-c:a", "libopus", "-b:a", "40k"]
    cmd = [exe, "-nostdin", "-y", "-v", "error", "-i", _fwd(wav), "-ac", "1", *args, _fwd(out)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, **_kwargs)
    if res.returncode != 0:
        raise MediaError("conversion_failed", res.stderr.strip()[:300])
    return out
