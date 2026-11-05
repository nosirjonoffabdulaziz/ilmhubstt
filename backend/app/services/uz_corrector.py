"""AI'siz o'zbekcha imlo tuzatuvchi.

Umumiy Whisper modeli o'zbekchani ko'pincha turkcha/qozoqcha harflar bilan, buzib yozadi:
"khafsizligini", "ukuçinin", "qaydalarige", "farzandim nin". Bu modul uni qoidalar asosida tuzatadi:

1. Harflarni normallashtirish (har doim, xavfsiz): ç→ch, ş→sh, ğ→g‘, ı→i, ö→o‘, ü→u, kh→x, tsh→ch ...
2. So'z lug'at + qo'shimchalar grammatikasidan (uz_morph) tekshiriladi.
3. Noto'g'ri so'z uchun Whisper'ning odatiy xatolari jadvali (a↔o, k↔q, x↔h, -nin→-ning ...) va bitta
   umumiy tahrir bilan eng arzon to'g'ri variant qidiriladi (vaznli tahrir masofasi).
4. Ajralib qolgan qo'shimchalar qo'shiladi ("transporti dan" → "transportidan"),
   yopishib qolgan so'zlar ajratiladi ("etişxamda" → "etish hamda").

Xavfsizlik: ism (gap o'rtasida bosh harf), raqam, foydalanuvchi atamalari o'zgartirilmaydi; ASR ishonchi
yuqori so'zlar tegilmaydi; tuzatib bo'lmagan so'z "noaniq" deb belgilanadi (taxmin yozilmaydi).
"""
from __future__ import annotations

import heapq
import re
from dataclasses import dataclass, field

from .uz_morph import OQ, TUT, Analyzer

# 1) har doim qo'llanadigan harf almashtirishlar (o'zbek lotin alifbosida bu harflar yo'q)
CHAR_MAP = [
    ("tsh", "ch"), ("Tsh", "Ch"), ("TSH", "CH"),
    ("kh", "x"), ("Kh", "X"), ("KH", "X"),
    ("zh", "j"), ("Zh", "J"),
    ("ç", "ch"), ("Ç", "Ch"), ("ş", "sh"), ("Ş", "Sh"), ("ğ", "g" + OQ), ("Ğ", "G" + OQ),
    ("ı", "i"), ("İ", "I"), ("ö", "o" + OQ), ("Ö", "O" + OQ), ("ü", "u"), ("Ü", "U"),
    ("ä", "a"), ("Ä", "A"), ("ñ", "ng"), ("Ñ", "Ng"), ("ū", "u"), ("Ū", "U"), ("â", "a"), ("î", "i"),
    ("é", "e"), ("è", "e"), ("ó", "o"), ("ô", "o"), ("ú", "u"), ("ý", "y"),
]

# 2) Whisper'ning o'zbekchadagi odatiy xatolari: (topilgan, to'g'risi, narx). "$" — so'z oxiri.
RULES: list[tuple[str, str, float]] = [
    ("nin$", "ning", 0.2), ("ning$", "nin", 0.9),
    ("uchi", "uvchi", 0.4), ("ichi", "uvchi", 0.6), ("uk", "o" + OQ + "q", 0.3), ("uq", "o" + OQ + "q", 0.3),
    ("bul", "bo" + OQ + "l", 0.3), ("yol", "yo" + OQ + "l", 0.3), ("tog", "to" + OQ + "g" + OQ, 0.4),
    ("egi", "agi", 0.3), ("ige$", "iga", 0.3), ("ege$", "aga", 0.3), ("ine$", "ina", 0.4),
    ("ay", "oi", 0.5), ("ai", "ay", 0.4), ("ky", "k", 0.3), ("yu", "u", 0.5), ("ya", "yo", 0.5), ("ye", "e", 0.5),
    ("ts", "s", 0.4), ("ll", "nl", 0.6), ("nn", "n", 0.4), ("af", "avf", 0.4),
    ("c", "ch", 0.4), ("c", "j", 0.5), ("j", "y", 0.6), ("y", "j", 0.7),
    ("x", "h", 0.5), ("h", "x", 0.5), ("k", "q", 0.5), ("q", "k", 0.5), ("q", "x", 0.6), ("q", "h", 0.6),
    ("g", "g" + OQ, 0.4), ("o", "o" + OQ, 0.4), ("u", "o" + OQ, 0.6), ("g" + OQ, "g", 0.5), ("o" + OQ, "o", 0.5),
    ("a", "o", 0.6), ("o", "a", 0.6), ("e", "a", 0.6), ("a", "e", 0.7), ("e", "i", 0.6), ("i", "e", 0.7),
    ("u", "i", 0.7), ("i", "u", 0.7), ("u", "o", 0.7), ("o", "u", 0.7), ("i", "y", 0.6), ("y", "i", 0.6),
    ("t", "d", 0.7), ("d", "t", 0.7), ("b", "v", 0.8), ("v", "b", 0.8),
    ("i$", "iy", 0.4), ("iy$", "i", 0.6),
]
GENERIC_COST = 1.0
APOS_INS_COST = 0.3          # ta'til, ma'no, sun'iy — tutuq tushib qolishi juda ko'p
INSERT_CHARS = "aeiouyvgnh" + OQ
MAX_EXPANSIONS = 900

# Alohida yozilib qolgan qo'shimchalar (oldingi so'zga qo'shiladi)
DETACHED = {"nin", "ning", "ni", "ga", "ka", "qa", "da", "dan", "ta", "tan", "dagi", "lar", "larni", "larga",
            "larda", "lardan", "larning", "imiz", "ingiz", "si", "gi", "dek", "day", "cha", "mi", "chi", "gacha",
            "ning", "lari", "ini", "iga", "ida", "idan", "dir"}
STANDALONE = {"va", "bu", "u", "da-da"}  # hech qachon qo'shilmaydi
HYPHEN_PAIRS = {("ota", "ona"), ("xulq", "atvor"), ("xatti", "harakat"), ("urf", "odat"), ("ish", "harakat"),
                ("qo‘llab", "quvvatla"), ("soat", "soat")}

# (1-so'z, 2-so'z boshi) -> (to'g'ri 1-so'z, to'g'ri 2-so'z boshi | None = qo'shib yozish)
BIGRAM_FIX = {
    ("ehtiyot", "qor"): ("ehtiyotkor", None), ("ehtiyot", "kor"): ("ehtiyotkor", None),
    ("majburiyat", "noma"): ("majburiyatnoma", None), ("ma'lumot", "noma"): ("ma’lumotnoma", None),
    ("oz", "zimma"): ("o‘z", "zimma"), ("oz", "o‘zi"): ("o‘z", "o‘zi"),
    ("hatti", "harakat"): ("xatti", "harakat"), ("xati", "harakat"): ("xatti", "harakat"),
    ("bo‘sh", "vaqt"): ("bo‘sh", "vaqt"), ("bosh", "vaqt"): ("bo‘sh", "vaqt"),
    ("yongin", "xavf"): ("yong‘in", "xavf"), ("su", "havza"): ("suv", "havza"), ("su", "xavza"): ("suv", "havza"),
}

_PUNCT_L = re.compile(r"^[\"'«“„(\[]+")
_PUNCT_R = re.compile(r"[\"'»”)\].,!?;:…]+$")
_HAS_DIGIT = re.compile(r"\d")
_NUMBERING = re.compile(r"^\d+[.)]*-?$|^[-–—•]$")


def normalize_chars(text: str) -> str:
    for a, b in CHAR_MAP:
        if a in text:
            text = text.replace(a, b)
    return text


def max_cost(n: int) -> float:
    if n <= 2:
        return 0.0
    if n == 3:
        return 0.45
    if n <= 5:
        return 0.9
    if n <= 7:
        return 1.3
    if n <= 9:
        return 1.75
    return 2.25


@dataclass
class Tok:
    text: str                     # yakuniy ko'rinish (tinish belgilari bilan)
    src: list[int]                # asl tokenlar indekslari (vaqt belgilari uchun)
    changed: bool = False
    original: str = ""
    unknown: bool = False         # tuzatib bo'lmadi -> noaniq
    meta: dict = field(default_factory=dict)


def _split_punct(tok: str) -> tuple[str, str, str]:
    m1 = _PUNCT_L.match(tok)
    left = m1.group(0) if m1 else ""
    rest = tok[len(left):]
    m2 = _PUNCT_R.search(rest)
    right = m2.group(0) if m2 else ""
    core = rest[: len(rest) - len(right)] if right else rest
    return left, core, right


def _match_case(src: str, dst: str) -> str:
    if src.isupper() and len(src) > 1:
        return dst.upper().replace(OQ.upper(), OQ)
    if src[:1].isupper():
        return dst[:1].upper() + dst[1:]
    return dst


GARBLED_RATIO = 0.22   # shundan ko'p so'z lug'atda topilmasa, matn "buzilgan" deb hisoblanadi


class Corrector:
    """mode: "auto" (hujjat bo'yicha avtomatik), "aggressive" (buzilgan matn), "conservative" (sifatli matn).

    conservative — faqat xavfsiz amallar: harflarni normallashtirish, ajralgan qo'shimchani qo'shish,
    ma'lum juftliklar va past ishonchli (p<0.5) so'zlarni jadval qoidalari bilan tuzatish.
    Lug'atda yo'q, lekin ishonchli so'zlarga tegilmaydi (ular noyob, ammo to'g'ri so'z bo'lishi mumkin).
    """

    def __init__(self, analyzer: Analyzer, protected: list[str] | None = None, mode: str = "auto"):
        self.a = analyzer
        self.protected = {p.lower() for p in (protected or [])}
        self._memo: dict[str, tuple[str, float] | None] = {}
        self.mode = mode
        self.aggressive = mode == "aggressive"

    def garble_ratio(self, tokens: list[str]) -> float:
        words = []
        for t in tokens:
            _, c, _ = _split_punct(normalize_chars(t))
            if c and c.replace(OQ, "").replace(TUT, "").replace("-", "").isalpha() and len(c) >= 3:
                words.append(c.lower())
        if not words:
            return 0.0
        foreign = sum(1 for t in tokens if normalize_chars(t) != t)
        bad = sum(1 for w in words if not self.valid(w))
        return (bad + foreign) / max(1, len(words))

    def calibrate(self, tokens: list[str]) -> float:
        """Butun hujjat bo'yicha rejimni tanlash (mode='auto' bo'lsa)."""
        r = self.garble_ratio(tokens)
        if self.mode == "auto":
            self.aggressive = r >= GARBLED_RATIO
        return r

    # ---------- bitta so'z ----------
    def valid(self, w: str) -> bool:
        return self.a.is_word(w)

    def best(self, w: str, budget: float | None = None) -> tuple[str, float] | None:
        """Eng arzon to'g'ri variant (so'z, narx) yoki None. w — kichik harfda, normallashtirilgan."""
        if budget is None:
            budget = max_cost(len(w.replace(OQ, "").replace(TUT, "")))
        key = f"{w}|{budget}"
        if key in self._memo:
            return self._memo[key]
        res = self._search(w, budget)
        self._memo[key] = res
        return res

    def _search(self, w: str, budget: float, generic: bool = True) -> tuple[str, float] | None:
        if self.valid(w):
            return w, 0.0
        if budget <= 0:
            return None
        heap: list[tuple[float, int, str]] = [(0.0, 0, w)]
        seen: dict[tuple[str, int], float] = {(w, 0): 0.0}
        found: list[tuple[float, int, str]] = []
        expansions = 0
        while heap and expansions < MAX_EXPANSIONS:
            cost, gen, s = heapq.heappop(heap)
            if found and cost > found[0][0] + 0.25:
                break
            if s != w and self.valid(s):
                found.append((cost, gen, s))
                found.sort()
                continue
            expansions += 1
            for ns, c, g in self._moves(s, gen if generic else 1):
                nc = cost + c
                if nc > budget + 1e-9:
                    continue
                k = (ns, gen + g)
                if seen.get(k, 1e9) <= nc:
                    continue
                seen[k] = nc
                heapq.heappush(heap, (nc, gen + g, ns))
        if not found:
            return None
        # teng narxda: yuklamasiz (to'g'ridan-to'g'ri) shakl va asl uzunlikka yaqinrog'i afzal
        found.sort(key=lambda x: (round(x[0], 3), x[1], 0 if self.a._check_core(x[2]) else 1,
                                  abs(len(x[2]) - len(w))))
        return found[0][2], found[0][0]

    def _moves(self, s: str, gen_used: int):
        n = len(s)
        for src, dst, c in RULES:
            if src.endswith("$"):
                core = src[:-1]
                if s.endswith(core):
                    yield s[: n - len(core)] + dst, c, 0
                continue
            start = s.find(src)
            while start != -1:
                # o‘/g‘ ichidagi o/g ni qayta almashtirmaslik
                if not (dst.startswith(src) and s[start: start + len(dst)] == dst):
                    yield s[:start] + dst + s[start + len(src):], c, 0
                start = s.find(src, start + 1)
        # tutuq belgisini qo'shish (ta'til, ma'no, sun'iy)
        if TUT not in s:
            for i in range(1, n):
                a_, b_ = s[i - 1], s[i]
                if a_ in OQ + TUT or b_ in OQ + TUT:
                    continue
                if (a_ in "aeiou") != (b_ in "aeiou"):
                    yield s[:i] + TUT + s[i:], APOS_INS_COST, 0
        if gen_used:
            return
        # bitta umumiy tahrir (cheklangan): o'chirish, joy almashtirish, ko'p tushib qoladigan harfni qo'shish
        for i in range(n):
            yield s[:i] + s[i + 1:], GENERIC_COST * (0.5 if i and s[i] == s[i - 1] else 1.0 if i else 1.5), 1
            if i + 1 < n:
                yield s[:i] + s[i + 1] + s[i] + s[i + 2:], GENERIC_COST, 1
        for i in range(n + 1):
            for ch in INSERT_CHARS:
                yield s[:i] + ch + s[i:], GENERIC_COST * (0.6 if ch in "yv" else 1.0), 1
        for i in range(n):
            if s[i] in "lrnmsz":
                for ch in "lrnmsz":
                    if ch != s[i]:
                        yield s[:i] + ch + s[i + 1:], GENERIC_COST, 1

    # ---------- matn (tokenlar ro'yxati) ----------
    def correct_tokens(self, tokens: list[str], probs: list[float | None] | None = None,
                       trust_prob: float = 0.85) -> list[Tok]:
        probs = probs or [None] * len(tokens)
        toks = [Tok(t if _split_punct(t)[1].lower() in self.protected else normalize_chars(t), [i], original=t)
                for i, t in enumerate(tokens)]
        for t in toks:
            if t.text != t.original:
                t.changed = True

        def core_of(t: Tok) -> tuple[str, str, str]:
            return _split_punct(t.text)

        def sentence_start(idx: int, arr: list[Tok]) -> bool:
            if idx == 0:
                return True
            prev = arr[idx - 1].text.rstrip("»”\")]")
            return prev.endswith((".", "!", "?", "…", ":", ".-", ")", ";")) or bool(_NUMBERING.match(prev))

        def is_name(idx: int, arr: list[Tok]) -> bool:
            _, c, _ = core_of(arr[idx])
            return bool(c[:1].isupper()) and not sentence_start(idx, arr)

        def skip(idx: int, arr: list[Tok]) -> bool:
            _, c, _ = core_of(arr[idx])
            if not c or _HAS_DIGIT.search(c) or c.lower() in self.protected:
                return True
            if not any(ch.isalpha() for ch in c):
                return True
            return is_name(idx, arr)

        def trusted(t: Tok) -> bool:
            # buzilgan hujjatda umumiy model noto'g'ri so'zni ham "ishonch bilan" chiqaradi -> ishonchga tayanmaymiz
            if self.aggressive:
                return False
            ps = [probs[i] for i in t.src if probs[i] is not None]
            return bool(ps) and min(ps) >= trust_prob and t.text == t.original

        # A) ajralib qolgan qo'shimchalarni qo'shish ("farzandim nin" -> "farzandimning")
        out: list[Tok] = []
        for idx, t in enumerate(toks):
            _, c, rr = core_of(t)
            cl = c.lower()
            if out and cl in DETACHED and cl not in STANDALONE:
                pl, pc, pr = core_of(out[-1])
                if not pr and pc and pc.replace(OQ, "").replace(TUT, "").isalpha():
                    merged = None
                    if pc[:1].isupper() and not sentence_start(len(out) - 1, out):
                        # ism: Toshkent da -> Toshkentda (lug'atsiz)
                        suf = "ning" if cl == "nin" else cl
                        merged = pc + suf
                    else:
                        r = self.best((pc + c).lower())
                        if r:
                            merged = _match_case(pc, r[0])
                    if merged:
                        out[-1] = Tok(pl + merged + rr, out[-1].src + t.src, True,
                                      (out[-1].original + " " + t.original).strip())
                        continue
            if self.aggressive and out and cl and not self.valid(cl) and cl.isalpha():
                pl, pc, pr = core_of(out[-1])
                if not pr and pc and self.valid((pc + c).lower()):
                    out[-1] = Tok(pl + pc + c.lower() + rr, out[-1].src + t.src, True,
                                  (out[-1].original + " " + t.original).strip())
                    continue
            out.append(t)
        toks = out

        # B) har bir so'zni tuzatish
        out = []
        i = 0
        while i < len(toks):
            t = toks[i]
            l, c, r = core_of(t)
            if skip(i, toks) or trusted(t):
                out.append(t)
                i += 1
                continue
            parts = c.split("-") if "-" in c.strip("-") else [c]
            if len(parts) > 1:
                fixed, ok = [], True
                for p in parts:
                    rb = self.best(p.lower()) if p else (p, 0.0)
                    if not rb:
                        ok = False
                        fixed.append(p)
                    else:
                        fixed.append(_match_case(p, rb[0]) if p else p)
                new = "-".join(fixed)
                out.append(Tok(l + new + r, t.src, t.changed or new != c, t.original, unknown=not ok))
                i += 1
                continue
            low = c.lower()
            if self.valid(low):
                out.append(t)
                i += 1
                continue
            if not self.aggressive:
                ps = [probs[j] for j in t.src if probs[j] is not None]
                weak = bool(ps) and min(ps) < 0.5
                res = self._search(low, min(0.9, max_cost(len(low))), generic=False) if weak or t.changed else None
                if res and res[0] != low:
                    out.append(Tok(l + _match_case(c, res[0]) + r, t.src, True, t.original))
                else:
                    out.append(Tok(t.text, t.src, t.changed, t.original, unknown=weak))
                i += 1
                continue
            res = self.best(low)
            # yopishib qolgan ikki so'z: "etishhamda" -> "etish hamda"
            split = self._try_split(low) if (res is None or res[1] > 1.2) and len(low) >= 7 else None
            if split and (res is None or split[2] < res[1]):
                a_, b_ = split[0], split[1]
                out.append(Tok(l + _match_case(c, a_), t.src, True, t.original))
                out.append(Tok(b_ + r, t.src, True, ""))
                i += 1
                continue
            # keyingi so'z bilan chegarani siljitish / qo'shish ("küzgit atil" -> "kuzgi ta'til", "ti ilish" -> "tiyilish")
            if (res is None or res[1] >= 0.9) and i + 1 < len(toks) and not skip(i + 1, toks) and not r:
                nxt = _split_punct(toks[i + 1].text)[1].lower()
                if nxt and not self.valid(nxt):
                    pair = self._try_pair(c, toks[i + 1])
                    alone = (res[1] if res else 9) + ((self.best(nxt) or (None, 9))[1])
                    if pair and pair[-1].meta.get("cost", 0) < alone:
                        for p_ in pair:
                            p_.src = t.src + toks[i + 1].src
                            p_.original = (t.original + " " + toks[i + 1].original).strip()
                        out.extend(pair)
                        i += 2
                        continue
            # oldingi to'g'ri so'zga bo'lakni ulash ("nazar atqilish" -> "nazorat qilish")
            if res is None and out:
                fix = self._try_attach_prev(out[-1], c, r, t)
                if fix:
                    out[-1], cur = fix
                    out.append(cur)
                    i += 1
                    continue
            if res:
                new = _match_case(c, res[0])
                out.append(Tok(l + new + r, t.src, True, t.original, meta={"cost": round(res[1], 2)}))
            else:
                out.append(Tok(t.text, t.src, t.changed, t.original, unknown=True))
            i += 1

        # B2) tez-tez ajralib/buzilib eshitiladigan juftliklar
        for k in range(len(out) - 1):
            pl, pc, pr = core_of(out[k])
            nl, nc, nr = core_of(out[k + 1])
            if pr:
                continue
            key = (pc.lower(), nc.lower())
            for (a_, b_), (ra_, rb_) in BIGRAM_FIX.items():
                if key[0] == a_ and key[1].startswith(b_):
                    rest = nc[len(b_):]
                    if rb_ is None:   # birlashtirish
                        out[k] = Tok(pl + _match_case(pc, ra_ + rest) + nr, out[k].src + out[k + 1].src, True,
                                     (out[k].original + " " + out[k + 1].original).strip())
                        out[k + 1] = Tok("", [], True, "")
                    else:
                        out[k] = Tok(pl + _match_case(pc, ra_), out[k].src, True, out[k].original)
                        out[k + 1] = Tok(nl + _match_case(nc, rb_ + rest) + nr, out[k + 1].src, True,
                                         out[k + 1].original)
                    break
        out = [t for t in out if t.text]

        # C) defis bilan yoziladigan juftliklar: ota ona -> ota-ona, xulq atvori -> xulq-atvori
        final: list[Tok] = []
        for t in out:
            if final:
                pl, pc, pr = core_of(final[-1])
                _, cc, cr = core_of(t)
                for a_, b_ in HYPHEN_PAIRS:
                    second = cc
                    if a_ == "ota" and cc.lower().startswith("ana") and self.valid("ona" + cc.lower()[3:]):
                        second = _match_case(cc, "ona" + cc.lower()[3:])
                    if not pr and pc.lower() == a_ and second.lower().startswith(b_):
                        final[-1] = Tok(pl + pc + "-" + second + cr, final[-1].src + t.src, True,
                                        (final[-1].original + " " + t.original).strip())
                        break
                else:
                    final.append(t)
                continue
            final.append(t)
        return final

    def _try_split(self, w: str):
        best = None
        for k in range(2, len(w) - 1):
            a, b = w[:k], w[k:]
            ra = self.best(a, min(0.6, max_cost(len(a))))
            if not ra or len(ra[0]) < 3:
                continue
            rb = self.best(b, min(0.6, max_cost(len(b))))
            if not rb or len(rb[0]) < 2:
                continue
            cost = ra[1] + rb[1] + 0.6
            if best is None or cost < best[2]:
                best = (ra[0], rb[0], cost)
        return best

    def _try_pair(self, c1: str, t2: Tok):
        l2, c2, r2 = _split_punct(t2.text)
        if not c2 or self.valid(c2.lower()):
            return None
        joined = (c1 + c2).lower()
        r = self.best(joined)
        if r:
            return [Tok(_match_case(c1, r[0]) + r2, [], True, "", meta={"cost": r[1] + 0.2})]
        # chegarani 1-2 harf siljitish
        best = None
        for shift in (-2, -1, 1, 2):
            if shift < 0:
                a, b = c1[:shift], c1[shift:] + c2
            else:
                a, b = c1 + c2[:shift], c2[shift:]
            if len(a) < 3 or len(b) < 3:
                continue
            ra, rb = self.best(a.lower()), self.best(b.lower())
            if ra and rb:
                cost = ra[1] + rb[1] + 0.3
                if best is None or cost < best[2]:
                    best = (_match_case(a, ra[0]), rb[0], cost)
        if best:
            return [Tok(best[0], [], True, ""), Tok(best[1] + r2, [], True, "", meta={"cost": best[2]})]
        return None

    def _try_attach_prev(self, prev: Tok, c: str, r: str, cur: Tok):
        pl, pc, pr = _split_punct(prev.text)
        if pr or not pc:
            return None
        for k in (1, 2, 3):
            x, y = c[:k], c[k:]
            if len(y) < 3:
                break
            ry = self.best(y.lower())
            if not ry:
                continue
            rx = self.best((pc + x).lower(), 0.8)
            if rx and len(x) <= 2 and rx[1] > 0 and len(rx[0]) > len(pc) and rx[1] + ry[1] <= 1.6:
                return (Tok(pl + _match_case(pc, rx[0]), prev.src, True, prev.original),
                        Tok(ry[0] + r, cur.src, True, cur.original))
        return None
