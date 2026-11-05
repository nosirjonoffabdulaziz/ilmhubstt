import re

import pytest

from app.security.auth import RateLimiter, hash_token, new_job_id, token_matches
from app.security.validation import ValidationError, parse_options, safe_filename
from app.services.chunking import Chunk, keep_words, plan_chunks
from app.services.export_service import content_disposition, download_name, render


# ---------------- chunking ----------------
def test_short_audio_single_chunk():
    assert plan_chunks(300, []) == [Chunk(0, 0.0, 300, 0.0, 300)]


def test_two_hours_cuts_at_silences():
    silences = [(t - 0.3, t + 0.3) for t in range(590, 7200, 600)]
    chunks = plan_chunks(7200, silences, target=600)
    assert len(chunks) == 12
    for a, b in zip(chunks, chunks[1:]):
        assert a.keep_end == b.keep_start  # bo'shliqsiz
        assert a.audio_end == a.keep_end   # pauzada kesilgan -> overlap yo'q
    assert chunks[0].keep_start == 0 and chunks[-1].keep_end == 7200


def test_hard_cut_has_overlap_when_no_silence():
    chunks = plan_chunks(1800, [], target=600)
    assert len(chunks) == 3
    assert chunks[1].audio_start < chunks[1].keep_start
    assert chunks[0].audio_end > chunks[0].keep_end


def test_keep_words_dedups_overlap():
    a = Chunk(0, 0, 600, 0, 601.5)
    b = Chunk(1, 600, 1200, 598.5, 1200)
    w_before = {"w": "x", "s": 599.0, "e": 599.6}
    w_cross = {"w": "y", "s": 599.8, "e": 600.4}   # o'rtasi 600.1 -> faqat b ga
    w_after = {"w": "z", "s": 600.6, "e": 601.0}
    words = [w_before, w_cross, w_after]
    assert keep_words(words, a, False) == [w_before]
    assert keep_words(words, b, True) == [w_cross, w_after]


# ---------------- export ----------------
RESULT = {
    "edited_text": "O‘zbekcha matn: g‘alaba, ma’no.\n",
    "latin_text": "x",
    "segments": [
        {"start": 0.0, "end": 2.5, "text": "Salom, do‘stlar!", "para": True,
         "words": [{"t": "Salom,", "s": 0.0, "e": 0.8}, {"t": "do‘stlar!", "s": 0.9, "e": 2.5}]},
        {"start": 3725.2, "end": 3727.0, "text": "Ikkinchi qism.", "para": True,
         "words": [{"t": "Ikkinchi", "s": 3725.2, "e": 3726.0}, {"t": "qism.", "s": 3726.1, "e": 3727.0}]},
    ],
}


def test_txt_is_edited_text_utf8():
    out = render(RESULT, "txt")
    assert out == "O‘zbekcha matn: g‘alaba, ma’no.\n"
    assert out.encode("utf-8").decode("utf-8") == out


def test_srt_format():
    out = render(RESULT, "srt")
    assert out.startswith("1\n00:00:00,000 --> 00:00:02,500\nSalom, do‘stlar!\n")
    assert "01:02:05,200 --> 01:02:07,000" in out


def test_vtt_format():
    out = render(RESULT, "vtt")
    assert out.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:02.500")


def test_txt_with_timestamps():
    out = render(RESULT, "txt_ts")
    assert "[00:00:00] Salom, do‘stlar!" in out and "[01:02:05] Ikkinchi qism." in out


def test_long_segment_split_into_cues():
    words = [{"t": f"so‘z{i}", "s": i * 0.5, "e": i * 0.5 + 0.4} for i in range(40)]
    out = render({"segments": [{"start": 0, "end": 20, "text": "", "words": words}]}, "srt")
    for block in out.strip().split("\n\n"):
        text = " ".join(block.split("\n")[2:])
        assert len(text) <= 84


def test_download_name_and_disposition():
    name = download_name("Dars: 1/2 o‘zbek.mp3", "txt")
    assert name == "Dars_ 1_2 o‘zbek_ilmhubstt.txt"
    cd = content_disposition(name)
    assert "filename*=UTF-8''" in cd and "%E2%80%98" in cd


# ---------------- validation / auth ----------------
@pytest.mark.parametrize("raw,expected", [
    ("../../etc/passwd", "passwd"),
    ("C:\\Users\\a\\dars.mp3", "dars.mp3"),
    ("ovoz yozuvi (1).m4a", "ovoz yozuvi (1).m4a"),
    ("<script>.mp3", "_script_.mp3"),
    ("", "audio"),
    ("o‘zbekcha.mp3", "o‘zbekcha.mp3"),
])
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected


def test_safe_filename_long():
    name = safe_filename("a" * 300 + ".mp3")
    assert len(name) <= 120 and name.endswith(".mp3")


def test_parse_options_defaults_and_errors():
    o = parse_options({}, engines=["dummy"], default_engine="dummy", default_quality="balanced")
    assert o == {"language": "uz", "script": "latin", "mode": "clean", "punctuation": True,
                 "paragraphs": True, "spellfix": True, "ai_proofread": False, "quality": "balanced", "engine": "dummy", "vocabulary": ""}
    o = parse_options({"punctuation": "false", "vocabulary": "Ali,\x00 Vali"}, engines=["dummy"],
                      default_engine="dummy", default_quality="fast")
    assert o["punctuation"] is False and o["vocabulary"] == "Ali, Vali"
    for bad in ({"language": "fr"}, {"script": "arab"}, {"mode": "x"}, {"quality": "ultra"},
                {"engine": "elevenlabs"}):
        with pytest.raises(ValidationError):
            parse_options(bad, engines=["dummy"], default_engine="dummy", default_quality="balanced")


def test_tokens_and_ids():
    jid = new_job_id()
    assert re.fullmatch(r"[0-9a-f]{32}", jid)
    h = hash_token("abc")
    assert token_matches("abc", h) and not token_matches("abd", h) and not token_matches(None, h)


def test_rate_limiter():
    rl = RateLimiter(2)
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a") and rl.allow("b")
    assert RateLimiter(0).allow("x")
