"""AI'siz o'zbekcha imlo tuzatuvchi testlari (haqiqiy umumiy-Whisper chiqishi asosida)."""
import time

import pytest

from app.services.text_pipeline import build_result
from app.services.transliteration_service import normalize_latin
from app.services.uz_corrector import Corrector, normalize_chars
from app.services.uz_morph import Analyzer

GARBLED = ("Majburiyat noma kyuzgi tatil davrida ukuçinin khayatı, vasagligi, khafsizligini tamillash doğrısı da. "
           "Men sent ukuçisinin ota anasi yoki konuni vakili sifatı da. Kyuzgi tatil davrida farzandim nin khayatı, "
           "vasagligini muhafaza qilish, khafsizligini tamillash, boş vaqtini mazmunli tashkil etişxamda, khulq "
           "atvarini nazar atqilish majburiyatini o‘z zimmamga olaman. 1.- Yol xarakati qaydalarige va jamaat "
           "transporti dan faydalanish tartibi ga qati riyo ya qilish 2.- Yongin khafsizlige qaydalarige amal qilish "
           "3.- Elektrji khazlari va gaz uskünalardan faydalanishda eqtiyot qorbulish 3.- Su khavzalari, qurulish "
           "maidonlari va başqa khafli khudutlari ga barmaslik 4.- Begana xaqslar bilan mulaqatda eqtiyot qorbulish "
           "4.- Ota anasinin ruqsatisiz va xabardor qilmastan yashash jayni tarq etmaslik.")

CLEAN = [
    "Assalomu alaykum, hurmatli tinglovchilar. Bugun biz sun’iy intellektning ta’limdagi o‘rni haqida gaplashamiz.",
    "Mehmonimiz Samarqand davlat universiteti o‘qituvchisi Dilshod Rahimov. Domla, avvalo aytingchi, talabalar bu "
    "texnologiyadan qanday foydalanishyapti?",
    "Rostini aytsam, ko‘pchilik bunday narsalarni uyda o‘rganyapti, darsda esa hali kam ishlatiladi.",
    "Masalan, 2025-yilda fakultetimizda 340 nafar talaba onlayn kursni tamomladi.",
    "O‘zbekiston Respublikasi Prezidentining farmoniga muvofiq yangi qonun qabul qilindi.",
    "Bolalar maktabdan qaytib, uy vazifalarini bajarishdi va keyin futbol o‘ynashdi.",
]


@pytest.fixture(scope="module")
def analyzer():
    return Analyzer()


def run(analyzer, text, **kw):
    c = Corrector(analyzer, **kw)
    toks = normalize_latin(text, "uz").split()
    c.calibrate(toks)
    return c, c.correct_tokens(toks)


def test_garbled_document_is_repaired(analyzer):
    t0 = time.time()
    c, res = run(analyzer, GARBLED)
    assert c.aggressive
    out = " ".join(r.text for r in res)
    for expected in ["Majburiyatnoma", "kuzgi ta’til", "o‘quvchining hayoti", "xavfsizligini ta’minlash to‘g‘risida",
                     "o‘quvchisining ota-onasi", "sifatida", "farzandimning", "muhofaza qilish", "bo‘sh vaqtini",
                     "tashkil etish hamda", "xulq-atvorini nazorat qilish", "Yo‘l harakati qoidalariga",
                     "jamoat transportidan foydalanish tartibiga", "Yong‘in", "Elektr jihozlari",
                     "uskunalardan", "ehtiyotkor bo‘lish", "Suv havzalari", "qurilish maydonlari", "boshqa xavfli",
                     "bormaslik", "muloqotda", "Ota-onasining ruxsatisiz", "qilmasdan", "tark etmaslik"]:
        assert expected in out, (expected, out)
    # tuzatib bo'lmaydiganlar taxmin qilinmaydi, noaniq deb belgilanadi
    unknown = {r.text.strip(",.") for r in res if r.unknown}
    assert "vasagligi" in unknown and "xaqslar" in unknown
    assert time.time() - t0 < 30


def test_clean_text_untouched(analyzer):
    c, _ = run(analyzer, " ".join(CLEAN))
    assert not c.aggressive
    for text in CLEAN:
        res = c.correct_tokens(text.split())
        assert " ".join(r.text for r in res) == text
        assert not any(r.unknown for r in res)


def test_conservative_fixes_only_low_confidence(analyzer):
    c = Corrector(analyzer, mode="conservative")
    toks = ["Bugun", "qaydalarige", "amal", "qilamiz."]
    assert [r.text for r in c.correct_tokens(toks, [0.9, 0.95, 0.9, 0.9])] == toks      # ishonchli -> tegilmaydi
    fixed = c.correct_tokens(toks, [0.9, 0.3, 0.9, 0.9])
    assert [r.text for r in fixed] == ["Bugun", "qoidalariga", "amal", "qilamiz."]


def test_names_numbers_and_vocabulary_protected(analyzer):
    c = Corrector(analyzer, protected=["Kizhi"], mode="aggressive")
    res = c.correct_tokens(["Mehmon", "Dilshod", "Rahimov", "2025-yilda", "Kizhi", "keldi."])
    assert [r.text for r in res] == ["Mehmon", "Dilshod", "Rahimov", "2025-yilda", "Kizhi", "keldi."]


def test_char_normalization():
    assert normalize_chars("çünki başqa doğrı khayat tshundi ı") == "chunki bashqa dog‘ri xayat chundi i"


def test_detached_suffix_merge_keeps_case_and_punct(analyzer):
    c = Corrector(analyzer, mode="aggressive")
    res = c.correct_tokens(["Farzandim", "nin", "Toshkent", "da,", "transporti", "dan."])
    assert [r.text for r in res] == ["Farzandimning", "Toshkentda,", "transportidan."]
    assert res[0].src == [0, 1] and res[2].src == [4, 5]


def test_aggressive_ignores_false_confidence(analyzer):
    c = Corrector(analyzer, mode="aggressive")
    res = c.correct_tokens(["kyuzgi", "tatil", "qaydalarige"], [0.95, 0.95, 0.95])
    assert [r.text for r in res] == ["kuzgi", "ta’til", "qoidalariga"]


def test_pipeline_integration_marks_corrections(analyzer):
    words = [{"w": w, "s": i * 0.5, "e": i * 0.5 + 0.4, "p": 0.3} for i, w in enumerate(GARBLED.split()[:12])]
    seg = [{"start": 0.0, "end": 6.0, "text": " ".join(x["w"] for x in words), "words": words}]
    opts = {"script": "latin", "mode": "clean", "punctuation": True, "paragraphs": True, "spellfix": True}
    r = build_result(seg, opts, "uz", 0.5, Corrector(analyzer))
    assert r["latin_text"].startswith("Majburiyatnoma kuzgi ta’til davrida o‘quvchining hayoti")
    assert r["raw_text"].startswith("Majburiyat noma kyuzgi")       # xom matn o'zgarmaydi
    assert r["stats"]["corrected"] >= 5
    w0 = r["segments"][0]["words"][0]
    assert w0["t"] == "Majburiyatnoma" and w0["c"] == "Majburiyat noma" and w0["s"] == 0.0 and w0["e"] == 0.9
    off = build_result(seg, {**opts, "spellfix": False}, "uz", 0.5, Corrector(analyzer))
    assert off["latin_text"].startswith("Majburiyat noma") and off["stats"]["corrected"] == 0
    kk = build_result(seg, opts, "kk", 0.5, Corrector(analyzer))
    assert kk["stats"]["corrected"] == 0


def test_user_lexicon_prevents_false_fix(tmp_path):
    from app.services import uz_morph
    lex = tmp_path / "user_lexicon.txt"
    lex.write_text("startap\n", encoding="utf-8")
    uz_morph._instance = None
    a = uz_morph.get_analyzer(lex)
    assert a.is_word("startaplar") and a.is_word("startaplarimiz")
    uz_morph._instance = None
