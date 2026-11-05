from app.services.text_pipeline import build_result

OPTS = {"script": "latin", "mode": "clean", "punctuation": True, "paragraphs": True}


def seg(start, end, words, **kw):
    n = len(words)
    step = (end - start) / max(n, 1)
    ws = []
    for i, w in enumerate(words):
        p = 0.95
        if isinstance(w, tuple):
            w, p = w
        ws.append({"w": " " + w, "s": start + i * step, "e": start + (i + 1) * step, "p": p})
    return {"start": start, "end": end, "text": " ".join(x["w"] for x in ws), "words": ws,
            "avg_logprob": kw.get("lp", -0.2), "compression_ratio": kw.get("cr", 1.2)}


def test_clean_mode_removes_fillers_and_keeps_raw():
    r = build_result([seg(0, 3, ["ee", "bugun", "mm", "dars", "boshlanadi."])], OPTS, "uz", 0.5)
    assert r["latin_text"] == "Bugun dars boshlanadi."
    assert "ee" in r["raw_text"] and "mm" in r["raw_text"]


def test_verbatim_keeps_fillers():
    r = build_result([seg(0, 3, ["ee", "bugun", "dars."])], {**OPTS, "mode": "verbatim"}, "uz", 0.5)
    assert r["latin_text"] == "Ee bugun dars."


def test_triple_repeat_collapsed_but_double_kept():
    r = build_result([seg(0, 4, ["men", "men", "men", "keldim,", "tez", "tez", "keldim."])], OPTS, "uz", 0.5)
    assert r["latin_text"] == "Men keldim, tez tez keldim."


def test_cyrillic_transliterated_raw_preserved():
    r = build_result([seg(0, 3, ["Салом,", "дўстлар!"])], OPTS, "uz", 0.5)
    assert r["latin_text"] == "Salom, do‘stlar!"
    assert r["raw_text"] == "Салом, дўстлар!"


def test_original_script_keeps_cyrillic():
    r = build_result([seg(0, 3, ["Салом,", "дўстлар!"])], {**OPTS, "script": "original"}, "uz", 0.5)
    assert r["latin_text"] == "Салом, дўстлар!"


def test_punctuation_off_strips():
    r = build_result([seg(0, 3, ["Salom,", "do‘stlar!"])], {**OPTS, "punctuation": False}, "uz", 0.5)
    assert r["latin_text"] == "Salom do‘stlar"


def test_capitalization_after_sentence_end():
    r = build_result([seg(0, 3, ["salom.", "qalaysiz?", "yaxshi"])], OPTS, "uz", 0.5)
    assert r["latin_text"] == "Salom. Qalaysiz? Yaxshi."


def test_uncertain_words_flagged_not_replaced():
    r = build_result([seg(0, 3, ["Dilshod", ("Rahimov", 0.3), "keldi."])], OPTS, "uz", 0.5)
    words = r["segments"][0]["words"]
    assert [w["u"] for w in words] == [False, True, False]
    assert words[1]["t"] == "Rahimov"
    assert r["stats"]["uncertain"] == 1


def test_low_confidence_segment_flags_all_words():
    r = build_result([seg(0, 3, ["noaniq", "gap."], lp=-1.5)], OPTS, "uz", 0.5)
    assert all(w["u"] for w in r["segments"][0]["words"])
    assert r["segments"][0]["low"]


def test_paragraph_on_long_pause():
    r = build_result([seg(0, 3, ["Birinchi", "gap"]), seg(6, 8, ["ikkinchi", "gap."])], OPTS, "uz", 0.5)
    assert r["latin_text"] == "Birinchi gap.\n\nIkkinchi gap."
    assert r["stats"]["paragraphs"] == 2


def test_paragraphs_disabled():
    r = build_result([seg(0, 3, ["Birinchi", "gap."]), seg(6, 8, ["Ikkinchi", "gap."])],
                     {**OPTS, "paragraphs": False}, "uz", 0.5)
    assert "\n" not in r["latin_text"]


def test_hallucination_loop_removed():
    segs = [seg(i * 3, i * 3 + 2, ["Rahmat", "tomosha", "uchun."]) for i in range(5)]
    r = build_result(segs, OPTS, "uz", 0.5)
    assert r["stats"]["segments"] == 2
    assert "loop_removed" in r["warnings"]


def test_kazakh_pipeline():
    r = build_result([seg(0, 3, ["Сәлеметсіз", "бе?"])], OPTS, "kk", 0.5)
    assert r["latin_text"] == "Sälemetsız be?"


def test_empty_input():
    r = build_result([], OPTS, "uz", 0.5)
    assert r["latin_text"] == "" and r["segments"] == []
