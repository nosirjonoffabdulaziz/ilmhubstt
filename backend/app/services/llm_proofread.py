"""Lokal AI muharrir: Ollama orqali kompyuterdagi til modeli (internetsiz, tekin).

Matn abzas-abzas modelga beriladi. Model faqat imlo, tinish belgisi, bosh harf va aniq noto'g'ri
tanilgan so'zlarni tuzatadi. Har bir javob qat'iy tekshiriladi: so'zlar soni yoki matn juda o'zgarsa,
izoh qo'shilsa yoki boshqa tilga o'girilsa — javob rad etiladi va asl matn qoladi.

Tuzatilgan so'zlar difflib orqali asl so'zlarga (vaqt belgilariga) qaytarib bog'lanadi.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import time
import urllib.error
import urllib.request

from .punctuation_service import tidy
from .transliteration_service import has_cyrillic, normalize_latin

log = logging.getLogger("ilmhubstt.proofread")

SYSTEM_UZ = (
    "Sen tajribali o‘zbek tili muharririsan. Senga nutqni avtomatik tanish (ASR) natijasi beriladi. "
    "Vazifang: matnni o‘zbek lotin alifbosining rasmiy imlosiga keltirish.\n"
    "Qoidalar:\n"
    "1. Imlo xatolarini, noto‘g‘ri eshitilgan so‘zlarni gap mazmuniga qarab tuzat "
    "(masalan: 'khafsizligini' -> 'xavfsizligini', 'ukuçinin' -> 'o‘quvchining').\n"
    "2. Tinish belgilarini (. , ? ! :) va bosh harflarni to‘g‘ri qo‘y.\n"
    "3. o‘ va g‘ uchun ‘ belgisini, tutuq uchun ’ belgisini ishlat (ta’til, ma’no).\n"
    "4. Ma’noni O‘ZGARTIRMA. Yangi gap QO‘SHMA, hech narsani O‘CHIRMA, qisqartirma, tarjima qilma.\n"
    "5. Ism, familiya, raqam, sana, manzil va atamalarni saqla.\n"
    "6. Faqat tuzatilgan matnni qaytar — izoh, sarlavha, qo‘shtirnoq yozma."
)
PROMPTS = {
    "uz": SYSTEM_UZ,
    "kk": SYSTEM_UZ.replace("o‘zbek tili muharririsan", "qozoq tili muharririsan (javobni qozoq tilida, "
                            "asl yozuvda qaytar)").replace("o‘zbek lotin alifbosining rasmiy imlosiga", "qozoq tilining "
                            "rasmiy imlosiga"),
    "ky": SYSTEM_UZ.replace("o‘zbek tili muharririsan", "qirg‘iz tili muharririsan (javobni qirg‘iz tilida, "
                            "asl yozuvda qaytar)").replace("o‘zbek lotin alifbosining rasmiy imlosiga", "qirg‘iz "
                            "tilining rasmiy imlosiga"),
}
_PREFIX = re.compile(r"^\s*(tuzatilgan matn|matn|javob|natija|corrected text|исправленный текст)\s*[:：-]\s*",
                     re.IGNORECASE)
_WORD = re.compile(r"\S+")
_CORE = re.compile(r"[^\w‘’'-]+", re.UNICODE)

MAX_CHUNK_WORDS = 160


class ProofreadError(Exception):
    pass


def _norm(w: str) -> str:
    return _CORE.sub("", w).lower().replace("'", "’")


class OllamaProofreader:
    def __init__(self, url: str, model: str, timeout: float = 600.0, temperature: float = 0.1):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self._status_cache: tuple[float, dict] | None = None

    # ---------- holat ----------
    def status(self, max_age: float = 15.0) -> dict:
        now = time.time()
        if self._status_cache and now - self._status_cache[0] < max_age:
            return self._status_cache[1]
        st = {"available": False, "model": self.model, "reason": ""}
        try:
            with urllib.request.urlopen(self.url + "/api/tags", timeout=2.0) as r:
                tags = json.loads(r.read().decode("utf-8"))
            names = {m.get("name", "") for m in tags.get("models", [])} | \
                    {m.get("model", "") for m in tags.get("models", [])}
            want = self.model if ":" in self.model else self.model + ":latest"
            if self.model in names or want in names:
                st["available"] = True
            else:
                st["reason"] = "model_not_pulled"
        except (urllib.error.URLError, OSError, ValueError):
            st["reason"] = "ollama_not_running"
        self._status_cache = (now, st)
        return st

    # ---------- bitta bo'lak ----------
    def _chat(self, system: str, text: str) -> str:
        body = json.dumps({
            "model": self.model,
            "stream": False,
            "keep_alive": "10m",
            "options": {"temperature": self.temperature, "num_ctx": 4096, "top_p": 0.9},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}],
        }).encode("utf-8")
        req = urllib.request.Request(self.url + "/api/chat", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ProofreadError(f"http_{exc.code}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProofreadError("ollama_unreachable") from exc
        return str((data.get("message") or {}).get("content", "")).strip()

    @staticmethod
    def clean_output(out: str) -> str:
        out = out.strip().strip("`").strip()
        out = _PREFIX.sub("", out)
        if len(out) > 2 and out[0] in "\"«“" and out[-1] in "\"»”":
            out = out[1:-1]
        return " ".join(out.split())

    @staticmethod
    def accept(src: str, out: str, lang: str) -> tuple[bool, str]:
        """Model javobi xavfsizmi? (ha/yo'q, sabab)"""
        if not out:
            return False, "empty"
        sw, ow = src.split(), out.split()
        if not sw:
            return False, "empty"
        ratio = len(ow) / len(sw)
        if ratio < 0.8 or ratio > 1.2:
            return False, "length"
        if lang == "uz" and has_cyrillic(out) and not has_cyrillic(src):
            return False, "script"
        sim = difflib.SequenceMatcher(None, src.lower(), out.lower(), autojunk=False).ratio()
        if sim < 0.6:
            return False, "too_different"
        nums_src = re.findall(r"\d+", src)
        nums_out = re.findall(r"\d+", out)
        if sorted(nums_src) != sorted(nums_out):
            return False, "numbers"
        return True, ""

    def proofread_text(self, text: str, lang: str, vocabulary: str = "") -> tuple[str, str]:
        system = PROMPTS.get(lang, SYSTEM_UZ)
        if vocabulary:
            system += f"\nBu atamalar to‘g‘ri yozilishi shart: {vocabulary}"
        out = self.clean_output(self._chat(system, text))
        if lang == "uz":
            out = normalize_latin(out, "uz")
        ok, why = self.accept(text, out, lang)
        return (out, "") if ok else (text, why)


# ---------- segmentlarga qayta bog'lash ----------
def _chunks(segments: list[dict]) -> list[list[int]]:
    """Abzaslar bo'yicha guruhlash, juda uzunlarini bo'lish (segment indekslari)."""
    groups: list[list[int]] = []
    cur: list[int] = []
    words = 0
    for i, s in enumerate(segments):
        n = len(s.get("words") or [])
        if cur and (s.get("para") or words + n > MAX_CHUNK_WORDS):
            groups.append(cur)
            cur, words = [], 0
        cur.append(i)
        words += n
    if cur:
        groups.append(cur)
    return groups


def remap(segments: list[dict], idxs: list[int], new_text: str) -> int:
    """Tahrirlangan matnni so'zlar bo'yicha asl segmentlarga joylash. O'zgargan so'zlar soni qaytadi."""
    flat: list[tuple[int, int]] = []
    for si in idxs:
        for wi, _ in enumerate(segments[si]["words"]):
            flat.append((si, wi))
    old = [segments[si]["words"][wi]["t"] for si, wi in flat]
    new = new_text.split()
    sm = difflib.SequenceMatcher(None, [_norm(w) for w in old], [_norm(w) for w in new], autojunk=False)
    changed = 0
    replace: dict[int, str | None] = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                if old[i1 + k] != new[j1 + k]:     # faqat tinish/bosh harf farqi
                    replace[i1 + k] = new[j1 + k]
            continue
        if tag in ("replace", "delete"):
            seg_new = new[j1:j2]
            span = i2 - i1
            for k in range(span):
                if k < len(seg_new):
                    piece = seg_new[k] if k < span - 1 else " ".join(seg_new[k:])
                    replace[i1 + k] = piece
                else:
                    replace[i1 + k] = None          # o'chirildi (masalan, takror)
        elif tag == "insert":
            target = i1 - 1 if i1 > 0 else 0
            if old:
                base = replace.get(target, old[target]) or old[target]
                ins = " ".join(new[j1:j2])
                replace[target] = (base + " " + ins) if i1 > 0 else (ins + " " + base)
    for k, val in replace.items():
        si, wi = flat[k]
        w = segments[si]["words"][wi]
        prev = w["t"]
        if val is None:
            w["drop"] = True
        elif val != prev:
            w.setdefault("c", prev)
            w["t"] = val
            w["ai"] = True
            if _norm(val) != _norm(prev):
                changed += 1
                w["u"] = False
    for si in idxs:
        seg = segments[si]
        seg["words"] = [w for w in seg["words"] if not w.get("drop")]
        seg["text"] = tidy(" ".join(w["t"] for w in seg["words"]))
    return changed


def proofread_segments(pr: OllamaProofreader, segments: list[dict], lang: str, vocabulary: str = "",
                       on_progress=None, cancelled=None) -> dict:
    groups = [g for g in _chunks(segments) if any(segments[i]["words"] for i in g)]
    stats = {"chunks": len(groups), "accepted": 0, "rejected": 0, "changed_words": 0, "reasons": {}}
    for n, g in enumerate(groups):
        if cancelled and cancelled():
            break
        src = " ".join(segments[i]["text"] for i in g if segments[i]["text"])
        if not src.strip():
            continue
        try:
            out, why = pr.proofread_text(src, lang, vocabulary)
        except ProofreadError as exc:
            stats["rejected"] += 1
            stats["reasons"][str(exc)] = stats["reasons"].get(str(exc), 0) + 1
            if str(exc) == "ollama_unreachable":
                stats["error"] = "ollama_unreachable"
                break
            continue
        if why:
            stats["rejected"] += 1
            stats["reasons"][why] = stats["reasons"].get(why, 0) + 1
        elif out != src:
            stats["accepted"] += 1
            stats["changed_words"] += remap(segments, g, out)
        else:
            stats["accepted"] += 1
        if on_progress:
            on_progress(n + 1, len(groups))
    return stats


def rebuild_text(segments: list[dict]) -> str:
    paragraphs: list[list[str]] = []
    for s in segments:
        if s.get("para") or not paragraphs:
            paragraphs.append([])
        if s.get("text"):
            paragraphs[-1].append(s["text"])
    return "\n\n".join(tidy(" ".join(p)) for p in paragraphs if p)
