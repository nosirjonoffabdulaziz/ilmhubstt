"""Kirill -> lotin transliteratsiya profillari.

Profillar (docs/TRANSLITERATION.md da batafsil):
  uz  — O‘zbek lotin alifbosi (1995, rasmiy). o‘ g‘ uchun U+2018 (‘), tutuq uchun U+2019 (’).
  kk  — Qozoq lotin alifbosi, 2021-yil loyihasi: Ä Ğ Ñ Ö Ū Ü Ş Ç, Ы→Y, І→I, И/Й→İ.
  ky  — Qirg‘iz tili uchun rasmiy lotin standarti yo‘q; loyiha profili: Ө→Ö, Ү→Ü, Ң→Ñ,
        Ы→I (nuqtasiz ı), И→İ (i), Ж→J, Ч→Ch, Ш→Sh.
"""
from __future__ import annotations

import re

_CYR_WORD = re.compile(r"[А-Яа-яЁёЎўҚқҒғҲҳӘәҢңӨөҰұҮүҺһІі]+")
_CYR_ANY = re.compile(r"[А-Яа-яЁёЎўҚқҒғҲҳӘәҢңӨөҰұҮүҺһІі]")

_UZ_VOWELS = set("аеёиоуўэюяАЕЁИОУЎЭЮЯ")
_UZ = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ё": "yo", "ж": "j", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s",
    "т": "t", "у": "u", "ф": "f", "х": "x", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "’", "ы": "i",
    "ь": "", "э": "e", "ю": "yu", "я": "ya", "ў": "o‘", "қ": "q", "ғ": "g‘", "ҳ": "h",
    # qozoq/qirg'iz harflari o'zbek matnida uchrab qolsa
    "ә": "a", "ң": "ng", "ө": "o‘", "ұ": "u", "ү": "u", "һ": "h", "і": "i",
}

_KK = {
    "а": "a", "ә": "ä", "б": "b", "в": "v", "г": "g", "ғ": "ğ", "д": "d", "е": "e", "ё": "io",
    "ж": "j", "з": "z", "и": "i", "й": "i", "к": "k", "қ": "q", "л": "l", "м": "m", "н": "n",
    "ң": "ñ", "о": "o", "ө": "ö", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ұ": "ū",
    "ү": "ü", "ф": "f", "х": "h", "һ": "h", "ц": "ts", "ч": "ç", "ш": "ş", "щ": "şş", "ъ": "",
    "ы": "y", "і": "ı", "ь": "", "э": "e", "ю": "iu", "я": "ia",
    "ў": "u", "ҳ": "h",
}
_KK_UPPER = {"и": "İ", "й": "İ", "і": "I"}

_KY = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ё": "yo", "ж": "j", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "ң": "ñ", "о": "o", "ө": "ö", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ү": "ü", "ф": "f", "х": "h", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch", "ъ": "", "ы": "ı", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ә": "ä", "ғ": "ğ", "қ": "q", "ұ": "u", "һ": "h", "і": "i", "ў": "u", "ҳ": "h",
}
_KY_UPPER = {"и": "İ", "ы": "I"}


def _apply_case(src: str, out: str, upper_word: bool, upper_table: dict) -> str:
    if not out:
        return out
    if src.isupper():
        low = src.lower()
        if low in upper_table:
            return upper_table[low]
        if upper_word:
            return out.upper().replace("‘", "‘")
        return out[0].upper() + out[1:]
    return out


def _uz_word(word: str) -> str:
    upper_word = len(word) > 1 and word.isupper()
    res = []
    for i, ch in enumerate(word):
        low = ch.lower()
        prev = word[i - 1] if i > 0 else ""
        if low == "е":
            out = "ye" if (i == 0 or prev in _UZ_VOWELS or prev.lower() in ("ъ", "ь")) else "e"
        elif low == "ц":
            out = "ts" if (i > 0 and prev in _UZ_VOWELS) else "s"
        else:
            out = _UZ.get(low, ch)
        res.append(_apply_case(ch, out, upper_word, {}))
    return "".join(res)


def _table_word(word: str, table: dict, upper_table: dict, initial_ye: bool) -> str:
    upper_word = len(word) > 1 and word.isupper()
    res = []
    for i, ch in enumerate(word):
        low = ch.lower()
        if low == "е" and initial_ye and i == 0:
            out = "ye"
        else:
            out = table.get(low, ch)
        res.append(_apply_case(ch, out, upper_word, upper_table))
    return "".join(res)


def has_cyrillic(text: str) -> bool:
    return bool(_CYR_ANY.search(text or ""))


def to_latin(text: str, lang: str) -> str:
    if not text or not has_cyrillic(text):
        return normalize_latin(text, lang)
    if lang == "kk":
        out = _CYR_WORD.sub(lambda m: _table_word(m.group(0), _KK, _KK_UPPER, False), text)
    elif lang == "ky":
        out = _CYR_WORD.sub(lambda m: _table_word(m.group(0), _KY, _KY_UPPER, True), text)
    else:
        out = _CYR_WORD.sub(lambda m: _uz_word(m.group(0)), text)
    return normalize_latin(out, lang)


_OG = re.compile(r"(?<=[oOgG])['`´’ʻʼ‘ʹ]")
_TUTUQ = re.compile(r"(?<=[A-Za-z])['`´ʻʼʹ](?=[A-Za-z])")


def normalize_latin(text: str, lang: str) -> str:
    """O‘zbek lotin matnidagi apostrof variantlarini yagona standartga keltirish."""
    if not text or lang != "uz":
        return text
    text = _OG.sub("‘", text)
    text = _TUTUQ.sub("’", text)
    return text
