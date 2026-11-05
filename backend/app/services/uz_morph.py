"""O'zbek so'zining to'g'riligini tekshiruvchi oddiy morfologik analizator (AI'siz, qoidaga asoslangan).

So'z = o'zak (lug'atdan) + qo'shimchalar zanjiri (grammatik ro'yxatdan).
Masalan: farzand+im+ning, xavfsiz+lig+i+ni, ta'minla+sh, tiy+il+ish, qil+ma+s+dan.
"""
from __future__ import annotations

import itertools
import os
import threading
from pathlib import Path

from . import uz_lexicon_data as D

OQ = "‘"   # o‘ g‘
TUT = "’"  # tutuq ’


def apos(word: str) -> str:
    """Lug'atdagi ASCII apostrofni standart belgilarga o'girish."""
    out = []
    for i, ch in enumerate(word):
        if ch == "'":
            prev = word[i - 1].lower() if i else ""
            out.append(OQ if prev in ("o", "g") else TUT)
        else:
            out.append(ch)
    return "".join(out)


def _expand(parts: list[list[str]]) -> set[str]:
    return {"".join(p) for p in itertools.product(*parts)}


# ---------------- qo'shimcha zanjirlari ----------------
_PLURAL = ["", "lar"]
_POSS = ["", "im", "m", "ing", "ng", "i", "si", "imiz", "miz", "ingiz", "ngiz", "lari", "ri"]
_CASE = ["", "ning", "ni", "n", "ga", "ka", "qa", "da", "dan", "dagi", "gacha", "day", "dek",
         "cha", "siz", "dek", "lik"]
_PART = ["", "mi", "ku", "da", "dir", "chi", "gina", "kina", "qina", "u", "yu", "oq", "yoq", "ham"]
_STRIP_PART = ("chi", "mi", "ku", "da", "yu", "u", "oq", "yoq", "gina", "kina", "qina", "-da", "-u", "-chi")
_DERIV = ["", "lik", "lig", "li", "siz", "chi", "dosh", "cha", "gi", "ki", "qi", "iy", "viy", "chilik", "kor",
          "xona", "goh", "noma", "simon", "dor", "ona", "garchilik", "chan", "kash"]

_VOICE = ["", "il", "in", "n", "l", "tir", "dir", "t", "giz", "kiz", "qiz", "gaz", "kaz", "qaz", "ish", "sh",
          "iz", "ar", "tiril", "diril", "ttir", "lash", "lan", "las", "ila", "til", "dil", "tiril", "lashtir",
          "lashtiril", "tirish", "dirish", "gizil", "kazil", "qazil", "ishtir", "shtir", "ib"]
_NEG = ["", "ma"]
_V_END = [
    "", "moq", "moqda", "moqdaman", "moqdamiz", "moqdasiz", "moqdalar", "moqchi", "moqchiman", "moqchimiz",
    "ib", "b", "y", "a", "ay", "aylik", "ylik", "ayin", "yin", "ing", "ng", "inglar", "nglar", "ingiz", "ngiz",
    "sin", "sinlar", "gin", "kin", "qin", "chi",
    "adi", "ydi", "aman", "yman", "asan", "ysan", "amiz", "ymiz", "asiz", "ysiz", "adilar", "ydilar", "ar", "r",
    "armi", "admi",
    "yap", "yapti", "yapman", "yapsan", "yapmiz", "yapsiz", "yaptilar", "yapmi",
    "yotir", "yotib", "yotgan", "yotibdi",
    "di", "dim", "ding", "dik", "dingiz", "dilar", "dimi", "dimi",
    "sa", "sam", "sang", "sak", "sangiz", "salar", "sada", "sa-da",
    "gach", "kach", "qach", "guncha", "kuncha", "quncha", "gani", "ganida", "gandan",
    "ibdi", "ibman", "ibmiz", "ibsiz", "ibdilar", "bdi", "bman",
    "gan", "kan", "qan", "adigan", "ydigan", "ajak", "yajak",
    "uvchi", "vchi", "ish", "sh", "maslik", "mas", "masdan", "may", "maydi", "mayman", "maymiz",
    "lik", "gani", "ganim", "ganing", "ganimiz", "ganingiz", "ganlari",
    "gudek", "gulik", "guvchi", "ishi", "uv", "v",
]
# fe'ldan yasalgan otlar keyin ot qo'shimchalarini oladi
_V_NOMINAL = ["ish", "sh", "gan", "kan", "qan", "uvchi", "vchi", "maslik", "mas", "moq", "adigan", "ydigan",
              "ganlik", "ganlig", "uv", "v", "ishlik", "shlik", "gich", "kich", "qich", "k", "q", "im", "m",
              "ma", "ishlig", "shlig", "inch", "nch", "qoq"]


# Qo'shimcha allomorflari: qaysi biri faqat unlidan (V) yoki faqat undoshdan (C) keyin keladi
_AFTER_V = {"m", "ng", "miz", "ngiz", "si", "ri", "viy", "b", "y", "r", "sh", "v", "vchi", "ydi", "yman", "ysan",
            "ymiz", "ysiz", "ydilar", "ylik", "yin", "ydigan", "yajak", "bdi", "bman", "l", "n", "t", "nglar",
            "shlik", "shlig", "nch", "q", "k"}
_AFTER_C = {"im", "ing", "imiz", "ingiz", "i", "iy", "ib", "a", "ay", "adi", "aman", "asan", "amiz", "asiz",
            "adilar", "ar", "aylik", "ayin", "ish", "uv", "uvchi", "inglar", "il", "in", "ibdi", "ibman", "ibmiz",
            "ibsiz", "ibdilar", "adigan", "ajak", "iz", "ila", "ishlik", "ishlig", "inch", "ishi", "armi", "admi",
            "ilish", "ar"}
_VOWELS = set("aeiou")


def ends_vowel(s: str) -> bool:
    if not s:
        return False
    if s.endswith("o" + OQ):
        return True
    return s[-1] in _VOWELS


def _req(part: str):
    if part in _AFTER_V:
        return "V"
    if part in _AFTER_C:
        return "C"
    return None


def _chains(slots: list[list[str]]) -> dict[str, set]:
    """Barcha birikmalar; ichki chegaralar fonetik tekshiriladi.
    Natija: qo'shimcha -> {o'zak oxiriga talab: 'V' | 'C' | None}."""
    out: dict[str, set] = {}
    for combo in itertools.product(*slots):
        parts = [p for p in combo if p]
        ok = True
        for left, right in zip(parts, parts[1:]):
            r = _req(right)
            if r == "V" and not ends_vowel(left) or r == "C" and ends_vowel(left):
                ok = False
                break
        if not ok:
            continue
        key = "".join(parts)
        out.setdefault(key, set()).add(_req(parts[0]) if parts else None)
    return out


def _merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        dst.setdefault(k, set()).update(v)


def _noun_chains() -> dict[str, set]:
    out = _chains([_DERIV, _PLURAL, _POSS, _CASE, _PART])
    for d1 in ("siz", "li", "kor", "chi", "dor", "iy", "viy", "gi", "dagi"):
        _merge(out, _chains([[d1], ["lik", "lig"], _PLURAL, _POSS, _CASE]))
    return out


def _verb_chains() -> dict[str, set]:
    small_tail = [_PLURAL, _POSS, _CASE]
    out = _chains([_VOICE, _NEG, _V_END])
    _merge(out, _chains([_VOICE, _NEG, _V_NOMINAL] + small_tail))
    return out


class Analyzer:
    def __init__(self, extra_words: list[str] | None = None):
        self.nouns = {apos(w.lower()) for w in D.NOUNS if w}
        self.verbs = {apos(w.lower()) for w in D.VERBS if w}
        self.closed = {apos(w.lower()) for w in D.CLOSED if w}
        self.forms = {apos(w.lower()) for w in D.FORMS if w}
        self.extra: set[str] = set()
        for w in extra_words or []:
            self.add_word(w)
        self.noun_suf = _noun_chains()
        self.verb_suf = _verb_chains()
        # fe'l o'zagi ham otga aylanishi mumkin (o'qi -> o'qish), shuning uchun ish/sh orqali yuqorida qamraldi
        self._cache: dict[str, bool] = {}
        self.max_stem = max(len(x) for x in self.nouns | self.verbs | {'a'})
        self.max_suf = max(max(map(len, self.noun_suf)), max(map(len, self.verb_suf)))

    def add_word(self, word: str) -> None:
        w = apos(word.strip().lower())
        if w and w.replace("-", "").replace(OQ, "").replace(TUT, "").isalpha():
            self.extra.add(w)
            self._cache = {} if hasattr(self, "_cache") else {}

    def _stem_ok(self, stem: str, verb: bool) -> bool:
        if verb:
            return stem in self.verbs
        return stem in self.nouns or stem in self.extra

    def is_word(self, word: str) -> bool:
        w = word.lower()
        if not w:
            return False
        hit = self._cache.get(w)
        if hit is not None:
            return hit
        res = self._check(w)
        if len(self._cache) > 200_000:
            self._cache.clear()
        self._cache[w] = res
        return res

    def _check(self, w: str) -> bool:
        if w in self.closed or w in self.forms or w in self.extra:
            return True
        if "-" in w:
            parts = [p for p in w.split("-") if p]
            return bool(parts) and all(self._check(p) for p in parts)
        for pt in _STRIP_PART:
            if w.endswith(pt) and len(w) - len(pt) >= 3 and self._check_core(w[: -len(pt)].rstrip("-")):
                return True
        return self._check_core(w)

    def _check_core(self, w: str) -> bool:
        if w in self.closed or w in self.forms or w in self.extra:
            return True
        n = len(w)
        for i in range(max(2, n - self.max_suf), n + 1):
            stem, suf = w[:i], w[i:]
            if len(stem) > self.max_stem:
                break
            for table, verb in ((self.noun_suf, False), (self.verb_suf, True)):
                reqs = table.get(suf)
                if reqs is None:
                    continue
                if self._stem_ok(stem, verb) and self._junction(stem, reqs):
                    return True
                alt = self._alt(stem, suf, verb)
                if alt and self._junction(alt, reqs):
                    return True
        return False

    @staticmethod
    def _junction(stem: str, reqs: set) -> bool:
        if None in reqs:
            return True
        return ("V" if ends_vowel(stem) else "C") in reqs

    _VOWEL_DROP = {"og‘z": "og‘iz", "burn": "burun", "o‘g‘l": "o‘g‘il", "ko‘ngl": "ko‘ngil", "singl": "singil",
                   "bo‘yn": "bo‘yin", "qorn": "qorin", "shahr": "shahar", "ism": "ism", "qayr": "qayir",
                   "ayr": "ayir", "yig‘l": "yig‘il", "o‘rn": "o‘rin", "bur": "burun", "fikr": "fikr",
                   "hukm": "hukm", "ilm": "ilm", "aql": "aql", "nasl": "nasl", "shakl": "shakl", "qadr": "qadr",
                   "sabr": "sabr", "umr": "umr", "zehn": "zehn", "mehr": "mehr", "fasl": "fasl"}

    def _alt(self, stem: str, suf: str, verb: bool) -> str | None:
        """Undosh almashinuvi (yurak->yuragi, qishloq->qishlog‘i) va unli tushishi (og‘iz->og‘zi).
        Mos asl o'zakni qaytaradi."""
        if verb and suf.startswith("v"):
            # tingla+vchi -> tinglovchi, o‘qi+vchi -> o‘quvchi
            if stem.endswith("o") and self._stem_ok(stem[:-1] + "a", True):
                return stem
            if stem.endswith("u") and self._stem_ok(stem[:-1] + "i", True):
                return stem
        if not suf or suf[0] not in "aeiou":
            return None
        if stem.endswith("g" + OQ) and self._stem_ok(stem[:-2] + "q", verb):
            return stem[:-2] + "q"
        if stem.endswith("g") and self._stem_ok(stem[:-1] + "k", verb):
            return stem[:-1] + "k"
        full = self._VOWEL_DROP.get(stem)
        if full and self._stem_ok(full, verb):
            return stem
        return None

    def is_known_stem(self, w: str) -> bool:
        return w in self.nouns or w in self.verbs or w in self.closed or w in self.extra


_lock = threading.Lock()
_instance: Analyzer | None = None
_user_file: Path | None = None
_user_mtime: float = -1.0


def get_analyzer(user_lexicon: Path | None = None) -> Analyzer:
    """Yagona (keshlangan) analizator; foydalanuvchi lug'ati o'zgarsa qayta o'qiladi."""
    global _instance, _user_file, _user_mtime
    with _lock:
        if _instance is None:
            _instance = Analyzer()
        if user_lexicon is not None:
            try:
                mt = os.path.getmtime(user_lexicon)
            except OSError:
                mt = -1.0
            if user_lexicon != _user_file or mt != _user_mtime:
                _user_file, _user_mtime = user_lexicon, mt
                if mt >= 0:
                    for line in Path(user_lexicon).read_text(encoding="utf-8").splitlines():
                        if line.strip() and not line.startswith("#"):
                            _instance.add_word(line.split()[0])
        return _instance
