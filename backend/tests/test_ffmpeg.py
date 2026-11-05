"""Haqiqiy FFmpeg bilan formatlar va konvertatsiya testi."""
import wave

import pytest

from app.services import ffmpeg_service as ff
from .conftest import needs_ffmpeg

pytestmark = needs_ffmpeg

FORMATS = ["wav", "mp3", "m4a", "ogg", "opus", "flac", "aac", "webm", "video_mp4", "video_mov", "video_mkv"]


@pytest.mark.parametrize("key", FORMATS)
def test_probe_formats(media, key):
    info = ff.probe(media[key])
    assert 19.0 < info["duration"] < 21.5, info


def test_probe_no_audio_video(media):
    with pytest.raises(ff.MediaError) as e:
        ff.probe(media["noaudio"])
    assert e.value.code == "no_audio_track"


@pytest.mark.parametrize("key", ["pdf", "fake_mp3"])
def test_probe_rejects_non_media(media, key):
    with pytest.raises(ff.MediaError) as e:
        ff.probe(media[key])
    assert e.value.code == "unsupported_format"


def test_probe_blocks_playlist_reference(tmp_path, media):
    """Boshqa fayllarga ishora qiluvchi playlist (SSRF/fayl o'qish) bloklanadi."""
    m3u = tmp_path / "x.m3u8"
    m3u.write_text(f"#EXTM3U\n#EXTINF:20,\n{media['mp3']}\n")
    with pytest.raises(ff.MediaError):
        ff.probe(m3u)


@pytest.mark.parametrize("key", ["mp3", "video_mp4", "opus"])
def test_convert(media, tmp_path, key):
    info = ff.probe(media[key])
    wav, prev = tmp_path / "a.wav", tmp_path / "p.mp3"
    seen = []
    ff.convert(media[key], wav, prev, info["duration"], progress=seen.append)
    with wave.open(str(wav)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
    assert abs(ff.wav_duration(wav) - info["duration"]) < 0.3
    assert prev.stat().st_size > 1000
    assert seen and seen[-1] > 0.8
    seg = ff.read_wav(wav, 5.0, 7.5)
    assert seg.dtype.name == "float32" and len(seg) == 40000
    peaks = ff.waveform_peaks(wav, 100)
    assert len(peaks) == 100 and max(peaks) == 1.0


def test_detect_silences(media, tmp_path):
    wav = tmp_path / "a.wav"
    ff.convert(media["wav"], wav, tmp_path / "p.mp3", 20)
    sil = ff.detect_silences(wav)
    assert len(sil) >= 3  # signalda har 4 soniyada pauza bor
    for s, e in sil:
        assert e > s


def test_weird_filename(media, tmp_path):
    odd = tmp_path / "-i dars: ‘1’.mp3"
    odd.write_bytes(media["mp3"].read_bytes())
    assert ff.probe(odd)["duration"] > 19
