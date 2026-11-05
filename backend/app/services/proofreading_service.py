"""Ehtiyotkor tahrir: faqat xavfsiz, ma'noni o'zgartirmaydigan tuzatishlar.

- "Toza matn" rejimida yakka to'ldiruvchi tovushlar (ee, mm, hmm, э-э ...) olib tashlanadi.
- Bir so'zning 3 va undan ortiq marta ketma-ket takrori bitta qilinadi (2 marta takror
  saqlanadi, chunki o'zbek tilida juft so'zlar ma'noli bo'lishi mumkin).
- Ism, raqam, manzil va atamalar hech qachon almashtirilmaydi.
- Takrorlanib qolgan (model "aylanib qolgan") segmentlar aniqlanadi.
"""
from __future__ import annotations

import re

from .language_service import FILLERS

_CORE = re.compile(r"[^\w\-‘’']+", re.UNICODE)


def core(token: str) -> str:
    return _CORE.sub("", token).lower()


def is_filler(token: str) -> bool:
    c = core(token)
    return bool(c) and c in FILLERS


def drop_mask(tokens: list[str], clean: bool) -> list[bool]:
    """Qaysi tokenlar toza matnda tashlab yuborilishini qaytaradi."""
    n = len(tokens)
    mask = [False] * n
    if not clean:
        return mask
    for i, t in enumerate(tokens):
        if is_filler(t):
            mask[i] = True
    # 3+ marta ketma-ket takror
    i = 0
    while i < n:
        c = core(tokens[i])
        j = i + 1
        while j < n and c and core(tokens[j]) == c and not mask[j]:
            j += 1
        if c and j - i >= 3:
            for k in range(i + 1, j):
                mask[k] = True
        i = max(j, i + 1)
    return mask


def is_loop(prev_texts: list[str], text: str, limit: int = 2) -> bool:
    """Bir xil segment ketma-ket `limit` martadan ko'p chiqsa — bu modelning takror xatosi."""
    key = core(text.replace(" ", ""))
    if not key:
        return False
    tail = prev_texts[-limit:]
    return len(tail) == limit and all(core(t.replace(" ", "")) == key for t in tail)
