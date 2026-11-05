"""Eksport: TXT (UTF-8), vaqt belgili TXT, SRT, VTT, JSON."""
from __future__ import annotations

import json
import re
from urllib.parse import quote

FORMATS = {
    "txt": ("text/plain; charset=utf-8", "txt"),
    "txt_ts": ("text/plain; charset=utf-8", "txt"),
    "srt": ("application/x-subrip; charset=utf-8", "srt"),
    "vtt": ("text/vtt; charset=utf-8", "vtt"),
    "json": ("application/json; charset=utf-8", "json"),
}
MAX_CUE_CHARS = 84
MAX_CUE_SECONDS = 7.0


def _hms(t: float, sep: str = ",", hours_always: bool = True) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _clock(t: float) -> str:
    t = int(max(0.0, t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _wrap(text: str, width: int = 42) -> str:
    if len(text) <= width:
        return text
    words = text.split()
    best = len(words) // 2
    best_diff = 10**9
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        diff = abs(len(a) - len(b))
        if diff < best_diff:
            best, best_diff = i, diff
    return " ".join(words[:best]) + "\n" + " ".join(words[best:])


def cues(segments: list[dict]) -> list[tuple[float, float, str]]:
    out: list[tuple[float, float, str]] = []
    for seg in segments:
        words = seg.get("words") or []
        if not words:
            out.append((seg["start"], seg["end"], seg["text"]))
            continue
        cur: list[dict] = []
        for w in words:
            if cur:
                text = " ".join(x["t"] for x in cur + [w])
                if len(text) > MAX_CUE_CHARS or w["e"] - cur[0]["s"] > MAX_CUE_SECONDS:
                    out.append((cur[0]["s"], cur[-1]["e"], " ".join(x["t"] for x in cur)))
                    cur = []
            cur.append(w)
        if cur:
            out.append((cur[0]["s"], cur[-1]["e"], " ".join(x["t"] for x in cur)))
    fixed = []
    for i, (s, e, t) in enumerate(out):
        if e <= s:
            e = s + 0.5
        if i + 1 < len(out) and e > out[i + 1][0]:
            e = max(s + 0.01, out[i + 1][0])
        fixed.append((s, e, t))
    return fixed


def render(result: dict, fmt: str) -> str:
    if fmt == "txt":
        text = result.get("edited_text") or result.get("latin_text") or ""
        return text.replace("\r\n", "\n").rstrip() + "\n"
    if fmt == "txt_ts":
        lines = []
        for seg in result.get("segments", []):
            if seg.get("para") and lines:
                lines.append("")
            lines.append(f"[{_clock(seg['start'])}] {seg['text']}")
        return "\n".join(lines) + "\n"
    if fmt == "srt":
        blocks = [f"{i}\n{_hms(s)} --> {_hms(e)}\n{_wrap(t)}\n" for i, (s, e, t) in enumerate(cues(result.get("segments", [])), 1)]
        return "\n".join(blocks)
    if fmt == "vtt":
        blocks = [f"{_hms(s, '.')} --> {_hms(e, '.')}\n{_wrap(t)}\n" for s, e, t in cues(result.get("segments", []))]
        return "WEBVTT\n\n" + "\n".join(blocks)
    if fmt == "json":
        data = {k: v for k, v in result.items() if k != "waveform"}
        return json.dumps(data, ensure_ascii=False, indent=2)
    raise ValueError(fmt)


def download_name(filename: str, fmt: str) -> str:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    stem = re.sub(r"[\\/:*?\"<>|]+", "_", stem).strip() or "transkripsiya"
    return f"{stem}_ilmhubstt.{FORMATS[fmt][1]}"


def content_disposition(name: str) -> str:
    ascii_name = name.encode("ascii", "ignore").decode() or "transkripsiya.txt"
    ascii_name = ascii_name.replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
