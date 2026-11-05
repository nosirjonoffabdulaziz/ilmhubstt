"""ASR xom natijasidan uch versiyali matn yasash: xom (raw), lotin/tozalangan va tahrir uchun.

Har bir so'z ishonch ko'rsatkichi bilan saqlanadi; past ishonchli so'zlar "noaniq" deb belgilanadi
va matnga taxmin qilingan boshqa so'z qo'shilmaydi.
"""
from __future__ import annotations

from .proofreading_service import drop_mask, is_loop
from .punctuation_service import capitalize_first, ends_sentence, strip_punctuation, tidy
from .transliteration_service import normalize_latin, to_latin

PARA_GAP = 2.0
PARA_MAX_WORDS = 120
LOW_LOGPROB = -1.0
HIGH_COMPRESSION = 2.4


def _tokens_from_segment(seg: dict) -> list[dict]:
    words = [w for w in (seg.get("words") or []) if str(w.get("w", "")).strip()]
    if words:
        return [{"w": str(w["w"]).strip(), "s": float(w["s"]), "e": float(w["e"]),
                 "p": (None if w.get("p") is None else float(w["p"]))} for w in words]
    parts = str(seg.get("text", "")).split()
    if not parts:
        return []
    start, end = float(seg["start"]), float(seg["end"])
    step = (end - start) / len(parts) if end > start else 0
    return [{"w": p, "s": round(start + i * step, 3), "e": round(start + (i + 1) * step, 3), "p": None}
            for i, p in enumerate(parts)]


def _apply_corrector(corrector, pre: list[dict]) -> list[dict]:
    toks = corrector.correct_tokens([w["t"] for w in pre], [w["p"] for w in pre])
    out = []
    for t in toks:
        src = [i for i in t.src if 0 <= i < len(pre)] or [0]
        first, last = pre[min(src)], pre[max(src)]
        ps = [pre[i]["p"] for i in src if pre[i]["p"] is not None]
        orig = " ".join(pre[i]["t"] for i in sorted(set(src)))
        changed = t.changed and t.text != orig
        out.append({"t": t.text, "s": first["s"], "e": last["e"], "p": min(ps) if ps else None,
                    "c": orig if changed else None, "x": t.unknown})
    return out


def build_result(raw_segments: list[dict], options: dict, text_lang: str, threshold: float,
                 corrector=None) -> dict:
    latin = options.get("script", "latin") == "latin"
    if not (latin and text_lang == "uz" and options.get("spellfix", True)):
        corrector = None
    fixed_words = 0
    if corrector is not None and hasattr(corrector, "calibrate"):
        everything = []
        for sg in raw_segments:
            for tk in _tokens_from_segment(sg):
                everything.append(to_latin(tk["w"], text_lang) if latin else tk["w"])
        corrector.calibrate(everything)
    clean = options.get("mode", "clean") == "clean"
    punct = bool(options.get("punctuation", True))
    paras_on = bool(options.get("paragraphs", True))

    out_segments: list[dict] = []
    raw_lines: list[str] = []
    prev_raw: list[str] = []
    warnings: list[str] = []
    sentence_start = True
    para_words = 0
    last_end = None
    total_words = uncertain = low_segments = 0

    for seg in sorted(raw_segments, key=lambda s: float(s.get("start", 0))):
        tokens = _tokens_from_segment(seg)
        if not tokens:
            continue
        raw_text = tidy(" ".join(t["w"] for t in tokens))
        if is_loop(prev_raw, raw_text):
            if "loop_removed" not in warnings:
                warnings.append("loop_removed")
            continue
        prev_raw.append(raw_text)
        raw_lines.append(raw_text)

        low = (seg.get("avg_logprob") is not None and float(seg["avg_logprob"]) < LOW_LOGPROB) or \
              (seg.get("compression_ratio") is not None and float(seg["compression_ratio"]) > HIGH_COMPRESSION)
        if low:
            low_segments += 1

        mask = drop_mask([t["w"] for t in tokens], clean)
        pre = []
        for tok, dropped in zip(tokens, mask):
            if dropped:
                continue
            t = to_latin(tok["w"], text_lang) if latin else normalize_latin(tok["w"], text_lang)
            if not punct:
                t = strip_punctuation(t)
            if not t.strip():
                continue
            pre.append({"t": t.strip(), "s": tok["s"], "e": tok["e"], "p": tok["p"], "c": None, "x": False})
        if corrector is not None and pre:
            pre = _apply_corrector(corrector, pre)
            fixed_words += sum(1 for w in pre if w["c"] is not None)
        words_out = []
        for w in pre:
            t = w["t"]
            if punct and sentence_start:
                t = capitalize_first(t)
            sentence_start = ends_sentence(t) if punct else False
            p = w["p"]
            u = bool(low or w["x"] or (p is not None and p < threshold and w["c"] is None))
            uncertain += int(u)
            total_words += 1
            item = {"t": t, "s": round(w["s"], 2), "e": round(w["e"], 2),
                    "p": None if p is None else round(p, 3), "u": u}
            if w["c"] is not None:
                item["c"] = w["c"]
            words_out.append(item)
        if not words_out:
            continue

        start = float(seg["start"])
        para = not out_segments
        if paras_on and out_segments:
            gap = start - (last_end if last_end is not None else start)
            prev_done = ends_sentence(out_segments[-1]["words"][-1]["t"])
            if gap >= PARA_GAP or (para_words >= PARA_MAX_WORDS and prev_done):
                para = True
        if para and out_segments and punct:
            last = out_segments[-1]["words"][-1]
            if not ends_sentence(last["t"]):
                last["t"] = last["t"].rstrip(",;:") + "."
                out_segments[-1]["text"] = tidy(" ".join(w["t"] for w in out_segments[-1]["words"]))
            words_out[0]["t"] = capitalize_first(words_out[0]["t"])
        para_words = len(words_out) if para else para_words + len(words_out)
        last_end = float(seg["end"])
        out_segments.append({
            "id": len(out_segments),
            "start": round(start, 2),
            "end": round(float(seg["end"]), 2),
            "raw": raw_text,
            "text": tidy(" ".join(w["t"] for w in words_out)),
            "para": para,
            "low": bool(low),
            "words": words_out,
        })

    if out_segments and punct:
        last = out_segments[-1]["words"][-1]
        if not ends_sentence(last["t"]):
            last["t"] = last["t"].rstrip(",;:") + "."
            out_segments[-1]["text"] = tidy(" ".join(w["t"] for w in out_segments[-1]["words"]))

    paragraphs: list[list[str]] = []
    for s in out_segments:
        if s["para"] or not paragraphs:
            paragraphs.append([])
        paragraphs[-1].append(s["text"])
    latin_text = "\n\n".join(tidy(" ".join(p)) for p in paragraphs)

    return {
        "raw_text": "\n".join(raw_lines),
        "latin_text": latin_text,
        "edited_text": latin_text,
        "segments": out_segments,
        "stats": {
            "words": total_words,
            "uncertain": uncertain,
            "segments": len(out_segments),
            "paragraphs": len(paragraphs),
            "low_segments": low_segments,
            "corrected": fixed_words,
        },
        "warnings": warnings,
    }
