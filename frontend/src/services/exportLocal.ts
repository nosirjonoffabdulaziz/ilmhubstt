// Natijani brauzerning o'zida faylga aylantirish (server kerak emas).
import type { Result } from "./api";

function ts(sec: number, sep: "," | "."): string {
  const ms = Math.max(0, Math.round(sec * 1000));
  const h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000), s = Math.floor((ms % 60000) / 1000), r = ms % 1000;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}${sep}${String(r).padStart(3, "0")}`;
}
function short(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

export function safeName(name: string): string {
  const base = name.replace(/\.[a-z0-9]{2,5}$/i, "").replace(/[\\/:*?"<>|\u0000-\u001f]+/g, " ").replace(/\s+/g, " ").trim();
  return (base || "ilmhubstt").slice(0, 80);
}

export function downloadText(filename: string, content: string, mime = "text/plain") {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export function renderExport(r: Result, text: string, fmt: string): { body: string; ext: string; mime: string } {
  const segs = r.segments;
  switch (fmt) {
    case "txt_ts":
      return { body: segs.map((s) => `[${short(s.start)}] ${s.text}`).join("\n") + "\n", ext: "txt", mime: "text/plain" };
    case "srt":
      return { body: segs.map((s, i) => `${i + 1}\n${ts(s.start, ",")} --> ${ts(s.end, ",")}\n${s.text}\n`).join("\n"), ext: "srt", mime: "application/x-subrip" };
    case "vtt":
      return { body: "WEBVTT\n\n" + segs.map((s) => `${ts(s.start, ".")} --> ${ts(s.end, ".")}\n${s.text}\n`).join("\n"), ext: "vtt", mime: "text/vtt" };
    case "json":
      return {
        body: JSON.stringify({ filename: r.filename, language: r.language, duration: r.duration, model: r.model, text,
          segments: segs.map((s) => ({ start: s.start, end: s.end, text: s.text })) }, null, 2),
        ext: "json", mime: "application/json",
      };
    default:
      return { body: text.endsWith("\n") ? text : text + "\n", ext: "txt", mime: "text/plain" };
  }
}

export function exportLocal(r: Result, text: string, fmt: string) {
  const { body, ext, mime } = renderExport(r, text, fmt);
  downloadText(`${safeName(r.filename)}${fmt === "txt_ts" ? "_vaqt" : ""}.${ext}`, body, mime);
}
