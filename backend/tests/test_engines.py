"""Dvigatel adapterlari testi.

faster-whisper bu test muhitida o'rnatilmagan bo'lishi mumkin, shuning uchun uning ommaviy API'si
(WhisperModel, transcribe -> (segments, info), Segment/Word maydonlari) soxta modul bilan
takrorlanadi. Haqiqiy model bilan sinov `scripts/real_asr_check.py` orqali bajariladi.
"""
import sys
import types
from collections import namedtuple

import numpy as np
import pytest

from app.config import Settings
from app.services.asr_service import EngineError, TranscribeRequest
from app.services.engines.elevenlabs_engine import ElevenLabsEngine
from app.services.engines.faster_whisper_engine import FasterWhisperEngine

Word = namedtuple("Word", "start end word probability")
Segment = namedtuple("Segment", "id start end text words avg_logprob no_speech_prob compression_ratio")
Info = namedtuple("Info", "language language_probability duration")


def install_fake_fw(monkeypatch, fail_load=None, fail_run=None):
    calls = {}

    class WhisperModel:
        def __init__(self, name, device="auto", compute_type="default", cpu_threads=0, download_root=None):
            if fail_load:
                raise RuntimeError(fail_load)
            calls["init"] = dict(name=name, device=device, compute_type=compute_type, download_root=download_root)

        def transcribe(self, audio, language=None, task="transcribe", beam_size=5, vad_filter=False,
                       vad_parameters=None, word_timestamps=False, condition_on_previous_text=True,
                       initial_prompt=None, temperature=0.0, compression_ratio_threshold=2.4,
                       log_prob_threshold=-1.0, no_speech_threshold=0.6, hallucination_silence_threshold=None,
                       hotwords=None):
            calls["transcribe"] = dict(language=language, vad_filter=vad_filter, word_timestamps=word_timestamps,
                                       initial_prompt=initial_prompt, hotwords=hotwords,
                                       condition_on_previous_text=condition_on_previous_text, n=len(audio))
            if fail_run:
                raise RuntimeError(fail_run)

            def gen():
                yield Segment(0, 0.0, 2.0, " Salom dunyo.",
                              [Word(0.0, 0.8, " Salom", 0.9), Word(0.9, 2.0, " dunyo.", 0.4)], -0.3, 0.01, 1.2)
                yield Segment(1, 2.5, 4.0, " Ikkinchi.", [Word(2.5, 4.0, " Ikkinchi.", 0.95)], -0.2, 0.0, 1.1)
            return gen(), Info("uz", 0.93, 4.0)

    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    return calls


def settings(tmp_path):
    s = Settings()
    s.model_dir = tmp_path / "models"
    s.whisper_models = {"fast": "small", "balanced": "medium", "best": "large-v3-turbo"}
    s.whisper_device = "cpu"
    return s


def req(**kw):
    base = dict(language="uz", prompt="Assalomu alaykum.", terms=["ILMHUB"], quality="balanced",
                user_language="uz", offset=600.0)
    base.update(kw)
    return TranscribeRequest(**base)


def test_faster_whisper_mapping(monkeypatch, tmp_path):
    calls = install_fake_fw(monkeypatch)
    eng = FasterWhisperEngine(settings(tmp_path))
    assert eng.available() == (True, "")
    progress = []
    out = eng.transcribe(np.zeros(16000 * 4, dtype=np.float32), req(on_progress=progress.append))
    assert calls["init"]["name"] == "medium" and calls["init"]["compute_type"] == "int8"
    t = calls["transcribe"]
    assert t["language"] == "uz" and t["vad_filter"] and t["word_timestamps"]
    assert t["condition_on_previous_text"] is False and t["hotwords"] == "ILMHUB"
    assert out.language == "uz" and len(out.segments) == 2
    first = out.segments[0]
    assert first["start"] == 600.0 and first["words"][1] == {"w": " dunyo.", "s": 600.9, "e": 602.0, "p": 0.4}
    assert progress == [2.0, 4.0]


def test_faster_whisper_unknown_kwargs_filtered(monkeypatch, tmp_path):
    """Eski versiyada hotwords bo'lmasa ham xato bermasligi kerak."""
    install_fake_fw(monkeypatch)
    mod = sys.modules["faster_whisper"]
    orig = mod.WhisperModel.transcribe

    def old_transcribe(self, audio, language=None, beam_size=5, vad_filter=False, vad_parameters=None,
                       word_timestamps=False, initial_prompt=None):
        return orig(self, audio, language=language, vad_filter=vad_filter, word_timestamps=word_timestamps,
                    initial_prompt=initial_prompt)
    monkeypatch.setattr(mod.WhisperModel, "transcribe", old_transcribe)
    out = FasterWhisperEngine(settings(tmp_path)).transcribe(np.zeros(100, dtype=np.float32), req())
    assert len(out.segments) == 2


def test_model_override_per_language(monkeypatch, tmp_path):
    calls = install_fake_fw(monkeypatch)
    s = settings(tmp_path)
    s.whisper_model_overrides = {"uz": "C:/models/uz-ct2"}
    FasterWhisperEngine(s).transcribe(np.zeros(10, dtype=np.float32), req())
    assert calls["init"]["name"] == "C:/models/uz-ct2"


def test_load_failure_mapped(monkeypatch, tmp_path):
    install_fake_fw(monkeypatch, fail_load="Repository not found")
    with pytest.raises(EngineError) as e:
        FasterWhisperEngine(settings(tmp_path)).transcribe(np.zeros(10, dtype=np.float32), req())
    assert e.value.code == "model_load_failed"


def test_oom_mapped(monkeypatch, tmp_path):
    install_fake_fw(monkeypatch, fail_run="std::bad_alloc")
    with pytest.raises(EngineError) as e:
        FasterWhisperEngine(settings(tmp_path)).transcribe(np.zeros(10, dtype=np.float32), req())
    assert e.value.code == "out_of_memory"


def test_not_installed(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    eng = FasterWhisperEngine(settings(tmp_path))
    assert eng.available()[0] is False
    with pytest.raises(EngineError) as e:
        eng.transcribe(np.zeros(10, dtype=np.float32), req())
    assert e.value.code == "engine_not_installed"


# ---------------- ElevenLabs ----------------
PAYLOAD = {
    "language_code": "uzb", "language_probability": 0.98, "text": "Salom do‘stlar. Bugun dars bor.",
    "words": [
        {"text": "Salom", "start": 0.0, "end": 0.4, "type": "word", "logprob": -0.05},
        {"text": " ", "start": 0.4, "end": 0.5, "type": "spacing"},
        {"text": "do‘stlar.", "start": 0.5, "end": 1.0, "type": "word", "logprob": -1.6},
        {"text": "(kulgi)", "start": 1.0, "end": 1.5, "type": "audio_event"},
        {"text": "Bugun", "start": 3.0, "end": 3.4, "type": "word"},
        {"text": "dars", "start": 3.5, "end": 3.8, "type": "word"},
        {"text": "bor.", "start": 3.9, "end": 4.2, "type": "word"},
    ],
}


def test_elevenlabs_parse():
    out = ElevenLabsEngine.parse(PAYLOAD)
    assert out.language == "uz"
    assert len(out.segments) == 2  # 1.2 s dan katta pauza -> yangi segment
    w = out.segments[0]["words"]
    assert [x["w"] for x in w] == ["Salom", "do‘stlar."]
    assert w[0]["p"] > 0.9 and w[1]["p"] < 0.3
    assert out.segments[1]["words"][0]["p"] is None


class FakeResp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._p = payload
        self.text = "err"

    def json(self):
        return self._p


class FakeSession:
    def __init__(self, resp):
        self.resp = resp
        self.sent = None

    def post(self, url, headers=None, data=None, files=None, timeout=None):
        self.sent = dict(url=url, headers=headers, data=data, fname=files["file"][0])
        return self.resp


def test_elevenlabs_request(tmp_path):
    s = settings(tmp_path)
    s.elevenlabs_api_key = "k"
    f = tmp_path / "cloud.ogg"
    f.write_bytes(b"x")
    sess = FakeSession(FakeResp(200, PAYLOAD))
    out = ElevenLabsEngine(s, session=sess).transcribe(f, req(user_language="ky"))
    assert sess.sent["data"]["language_code"] == "kir" and sess.sent["data"]["model_id"] == "scribe_v2"
    assert sess.sent["headers"]["xi-api-key"] == "k"
    assert len(out.segments) == 2


@pytest.mark.parametrize("code,expected", [(401, "cloud_auth_failed"), (429, "cloud_rate_limited"),
                                           (500, "cloud_error")])
def test_elevenlabs_errors(tmp_path, code, expected):
    s = settings(tmp_path)
    s.elevenlabs_api_key = "k"
    f = tmp_path / "c.ogg"
    f.write_bytes(b"x")
    with pytest.raises(EngineError) as e:
        ElevenLabsEngine(s, session=FakeSession(FakeResp(code))).transcribe(f, req())
    assert e.value.code == expected


# ---------------- model yuklab olish va GPU tanlovi ----------------
def install_fake_download(monkeypatch, delay=0.5):
    import os
    import time as _t
    utils = types.ModuleType("faster_whisper.utils")
    calls = []

    def download_model(name, output_dir=None, local_files_only=False, cache_dir=None):
        calls.append(local_files_only)
        target = os.path.join(cache_dir, f"models--Systran--faster-whisper-{name}")
        if local_files_only:
            if os.path.exists(os.path.join(target, "model.bin")):
                return target
            raise RuntimeError("not cached")
        os.makedirs(target, exist_ok=True)
        with open(os.path.join(target, "model.bin.incomplete"), "wb") as fh:
            for _ in range(8):
                fh.write(b"\0" * 1024 * 1024)
                fh.flush()
                _t.sleep(delay / 2)
        os.replace(os.path.join(target, "model.bin.incomplete"), os.path.join(target, "model.bin"))
        return target

    utils.download_model = download_model
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", utils)
    return calls


def test_model_download_reports_progress(monkeypatch, tmp_path):
    calls = install_fake_fw(monkeypatch)
    dl = install_fake_download(monkeypatch)
    events = []
    eng = FasterWhisperEngine(settings(tmp_path))
    eng.transcribe(np.zeros(16000, dtype=np.float32), req(on_status=lambda st, d: events.append((st, d))))
    stages = [e[0] for e in events]
    assert stages[0] == "downloading_model" and "loading_model" in stages and stages[-1] == "transcribing"
    sizes = [e[1]["done_mb"] for e in events if e[0] == "downloading_model"]
    assert max(sizes) >= 1 and events[0][1]["total_mb"] == 1530
    assert calls["init"]["name"].endswith("faster-whisper-medium")   # mahalliy yo'l bilan yuklandi
    # ikkinchi marta: keshdan, yuklashsiz
    eng2 = FasterWhisperEngine(settings(tmp_path))
    ev2 = []
    eng2.transcribe(np.zeros(10, dtype=np.float32), req(on_status=lambda st, d: ev2.append(st)))
    assert "downloading_model" not in ev2 and dl[-1] is True


def test_download_failure_is_clear(monkeypatch, tmp_path):
    install_fake_fw(monkeypatch)
    utils = types.ModuleType("faster_whisper.utils")

    def boom(name, output_dir=None, local_files_only=False, cache_dir=None):
        raise RuntimeError("Connection error")
    utils.download_model = boom
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", utils)
    with pytest.raises(EngineError) as e:
        FasterWhisperEngine(settings(tmp_path)).transcribe(np.zeros(10, dtype=np.float32), req())
    assert e.value.code == "model_download_failed"


@pytest.mark.parametrize("rc,out,expected", [(1, "", "cpu"), (0, "CUDA_OK\n", "cuda"), (-1073741819, "", "cpu")])
def test_auto_device_checks_gpu_in_subprocess(monkeypatch, tmp_path, rc, out, expected):
    import subprocess as sp
    calls = install_fake_fw(monkeypatch)
    install_fake_download(monkeypatch, delay=0)
    ct2 = types.ModuleType("ctranslate2")
    ct2.get_cuda_device_count = lambda: 1
    monkeypatch.setitem(sys.modules, "ctranslate2", ct2)
    ran = []

    def fake_run(cmd, **kw):
        ran.append(cmd)
        return sp.CompletedProcess(cmd, rc, stdout=out, stderr="Could not locate cudnn_ops64_9.dll")
    monkeypatch.setattr(sp, "run", fake_run)
    s = settings(tmp_path)
    s.whisper_device = "auto"
    s.whisper_compute_type = "auto"
    eng = FasterWhisperEngine(s)
    eng.transcribe(np.zeros(10, dtype=np.float32), req())
    assert calls["init"]["device"] == expected
    assert calls["init"]["compute_type"] == ("float16" if expected == "cuda" else "int8")
    assert ran and ran[0][2] == "app.services.engines.cuda_check"
    eng.transcribe(np.zeros(10, dtype=np.float32), req())
    assert len(ran) == 1   # natija keshlanadi


def test_no_gpu_skips_check(monkeypatch, tmp_path):
    import subprocess as sp
    calls = install_fake_fw(monkeypatch)
    install_fake_download(monkeypatch, delay=0)
    ct2 = types.ModuleType("ctranslate2")
    ct2.get_cuda_device_count = lambda: 0
    monkeypatch.setitem(sys.modules, "ctranslate2", ct2)
    monkeypatch.setattr(sp, "run", lambda *a, **k: pytest.fail("subprocess kerak emas"))
    s = settings(tmp_path)
    s.whisper_device = "auto"
    s.whisper_compute_type = "auto"
    FasterWhisperEngine(s).transcribe(np.zeros(10, dtype=np.float32), req())
    assert calls["init"]["device"] == "cpu"
