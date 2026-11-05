"""Uzun audioni bo'laklarga bo'lish rejasi.

Har bir bo'lak iloji boricha pauza (sukut) o'rtasida kesiladi, shunda so'z o'rtadan bo'linmaydi.
Agar yaqin atrofda pauza topilmasa, qattiq kesiladi va ikki tomonga kichik overlap qo'shiladi;
takroriy so'zlar keyin vaqt bo'yicha "keep" oynasi orqali olib tashlanadi (dedup).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

HARD_CUT_OVERLAP = 1.5  # soniya


@dataclass
class Chunk:
    index: int
    keep_start: float  # natijaga kiradigan so'zlar shu oraliqdan boshlanadi
    keep_end: float
    audio_start: float  # modelga beriladigan audio (overlap bilan)
    audio_end: float

    def to_dict(self) -> dict:
        return asdict(self)


def plan_chunks(duration: float, silences: list[tuple[float, float]], target: float = 600.0,
                search: float = 45.0) -> list[Chunk]:
    if duration <= 0:
        return []
    if duration <= target * 1.25:
        return [Chunk(0, 0.0, duration, 0.0, duration)]

    cuts: list[tuple[float, bool]] = []  # (vaqt, pauzadami)
    pos = 0.0
    while duration - pos > target * 1.25:
        ideal = pos + target
        best = None
        for s, e in silences:
            mid = (s + e) / 2
            if mid <= pos + target * 0.5:
                continue
            if abs(mid - ideal) <= search and (best is None or abs(mid - ideal) < abs(best - ideal)):
                best = mid
        if best is not None:
            cuts.append((best, True))
            pos = best
        else:
            cuts.append((ideal, False))
            pos = ideal

    bounds = [0.0] + [c for c, _ in cuts] + [duration]
    soft = [True] + [s for _, s in cuts] + [True]
    chunks = []
    for i in range(len(bounds) - 1):
        ks, ke = bounds[i], bounds[i + 1]
        a_start = ks if soft[i] else max(0.0, ks - HARD_CUT_OVERLAP)
        a_end = ke if soft[i + 1] else min(duration, ke + HARD_CUT_OVERLAP)
        chunks.append(Chunk(i, round(ks, 3), round(ke, 3), round(a_start, 3), round(a_end, 3)))
    return chunks


def keep_words(words: list[dict], chunk: Chunk, is_last: bool) -> list[dict]:
    """Overlap tufayli ikki bo'lakda ham chiqqan so'zlardan faqat bittasini qoldirish."""
    out = []
    for w in words:
        mid = (w["s"] + w["e"]) / 2
        if mid < chunk.keep_start - 1e-6:
            continue
        if mid >= chunk.keep_end and not is_last:
            continue
        out.append(w)
    return out
