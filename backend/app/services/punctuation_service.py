"""Matnni normallashtirish: bo'shliqlar, bosh harf, tinish belgilari.

Tinish belgilarining o'zi ASR modeli (Whisper) natijasidan olinadi; bu modul ularni tozalaydi,
gap boshini bosh harf bilan yozadi va kerak bo'lsa o'chiradi. Alohida "punktuatsiya modeli" yo'q.
"""
from __future__ import annotations

import re

SENT_END = (".", "!", "?", "…")
_PUNCT_STRIP = re.compile(r"[.,!?;:…«»\"“”„()\[\]]")
_SPACE_BEFORE = re.compile(r"\s+([,.!?;:…%)\]»])")
_SPACE_AFTER_OPEN = re.compile(r"([(\[«])\s+")
_MULTI_SPACE = re.compile(r"[ \t ]{2,}")
_DUP_PUNCT = re.compile(r"([,;:])\1+")


def tidy(text: str) -> str:
    text = text.replace(" ", " ")
    text = _SPACE_BEFORE.sub(r"\1", text)
    text = _SPACE_AFTER_OPEN.sub(r"\1", text)
    text = _DUP_PUNCT.sub(r"\1", text)
    text = re.sub(r"\.{4,}", "...", text)
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()


def strip_punctuation(token: str) -> str:
    return _PUNCT_STRIP.sub("", token)


def capitalize_first(token: str) -> str:
    for i, ch in enumerate(token):
        if ch.isalpha():
            if ch == "i" and token[i + 1: i + 2] == "̇":
                return token
            return token[:i] + ch.upper() + token[i + 1:]
        if ch.isdigit():
            return token
    return token


def ends_sentence(token: str) -> bool:
    t = token.rstrip("»\"”)] ")
    return t.endswith(SENT_END)
