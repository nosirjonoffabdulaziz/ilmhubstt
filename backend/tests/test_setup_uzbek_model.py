from setup_uzbek_model import set_env_value


def test_set_env_value_replaces_commented_line(tmp_path):
    env = tmp_path / ".env"
    env.write_text("PORT=8000\n# WHISPER_MODEL_UZ=C:\\models\\x\nASR_ENGINE=faster-whisper\n", encoding="utf-8")
    set_env_value(env, "WHISPER_MODEL_UZ", r"D:\ilmhubstt\models\rubaistt-v2-medium-ct2")
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines == ["PORT=8000", r"WHISPER_MODEL_UZ=D:\ilmhubstt\models\rubaistt-v2-medium-ct2", "ASR_ENGINE=faster-whisper"]


def test_set_env_value_appends_and_dedups(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nWHISPER_MODEL_UZ=old\nWHISPER_MODEL_UZ=older\n", encoding="utf-8")
    set_env_value(env, "WHISPER_MODEL_UZ", "new")
    assert env.read_text(encoding="utf-8") == "A=1\nWHISPER_MODEL_UZ=new\n"
    env2 = tmp_path / "e2"
    set_env_value(env2, "WHISPER_MODEL_UZ", "x")
    assert env2.read_text(encoding="utf-8") == "WHISPER_MODEL_UZ=x\n"


def test_override_used_and_described(tmp_path, monkeypatch):
    import os
    from app.config import load_settings
    monkeypatch.setenv("WHISPER_MODEL_UZ", str(tmp_path / "rubaistt-v2-medium-ct2"))
    s = load_settings()
    from app.services.engines.faster_whisper_engine import FasterWhisperEngine
    e = FasterWhisperEngine(s)
    assert e.model_name("fast", "uz").endswith("rubaistt-v2-medium-ct2")
    assert e.model_name("fast", "kk") == s.whisper_models["fast"]
    assert e.describe()["language_models"] == {"uz": "rubaistt-v2-medium-ct2"}
