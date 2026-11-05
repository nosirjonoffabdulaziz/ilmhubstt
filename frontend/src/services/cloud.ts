// Brauzer rejimi: YouTube havolasi, to'g'ridan-to'g'ri havola yoki faylni Gemini orqali matnga aylantirish.
// Hammasi foydalanuvchi brauzerida bajariladi (server kerak emas) — Vercel kabi statik hostingda ishlaydi.
import {
  addUsage, blobToBase64, deleteFile, emptyUsage, generate, GeminiError, getFile, getKey, GFile, uploadFile, Usage, waitActive,
} from "./gemini";
import { idbDel, idbGet, idbPut } from "./idb";
import { removeHistory, upsertHistory } from "./storage";
import { youtubeUrl } from "./youtube";
import type { Result, Segment, Word } from "./api";
import { makeSummary, storeSummary } from "./summary";

export type SourceType = "youtube" | "file" | "url";
export interface CloudSource { type: SourceType; name: string; url?: string; videoId?: string; mime?: string; size?: number }
export interface CloudOptions { language: string; mode: string; script: string; vocabulary: string; summaryLang?: string }
export interface CloudSeg { start: number; end: number; text: string; para: boolean }
export interface CloudJob {
  id: string; kind: "cloud"; created: number; source: CloudSource; options: CloudOptions;
  status: string; stage: string; progress: number; detail: Record<string, any>; error: string | null; errorDetail?: string;
  duration: number; processed: number; segments: CloudSeg[]; live: string[];
  file?: { name: string; uri: string; mimeType: string; at: number } | null;
  external?: boolean; inline?: boolean; clip?: boolean | null;
  usage: Usage; model: string; started: number; finished: number | null; edited?: string; warnings: string[];
}

export const RUNNING = ["queued", "downloading", "uploading", "processing", "transcribing", "summarizing"];
const WIN = 15 * 60; // bitta so'rovdagi parcha (soniya), Files API kesish ishlasa
const INLINE_MAX = 15 * 1024 * 1024; // shundan kichik fayllar to'g'ridan-to'g'ri so'rov ichida yuboriladi
const INLINE_FALLBACK_MAX = 70 * 1024 * 1024;
export const FILE_MAX = 2 * 1024 * 1024 * 1024;

// ---------------- holat va obunachilar ----------------
const cache = new Map<string, CloudJob>();
const ctrls = new Map<string, AbortController>();
const subs = new Map<string, Set<(j: CloudJob) => void>>();
const inlineCache = new Map<string, string>();

export function newId(): string {
  const a = new Uint8Array(16);
  crypto.getRandomValues(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}
export function subscribe(id: string, fn: (j: CloudJob) => void): () => void {
  if (!subs.has(id)) subs.set(id, new Set());
  subs.get(id)!.add(fn);
  return () => { subs.get(id)?.delete(fn); };
}
export const isRunning = (id: string) => ctrls.has(id);
export const anyRunning = () => ctrls.size > 0;

let saveTimers = new Map<string, number>();
async function persist(job: CloudJob, now = false) {
  cache.set(job.id, job);
  subs.get(job.id)?.forEach((fn) => fn({ ...job }));
  upsertHistory({ id: job.id, status: job.status, progress: job.progress, duration: job.duration, filename: job.source.name });
  window.clearTimeout(saveTimers.get(job.id));
  const write = () => idbPut("jobs", job.id, job).catch(() => undefined);
  if (now) await write();
  else saveTimers.set(job.id, window.setTimeout(write, 700));
}

export async function loadCloudJob(id: string): Promise<CloudJob | null> {
  const c = cache.get(id);
  if (c) return c;
  const j = await idbGet<CloudJob>("jobs", id);
  if (!j) return null;
  // sahifa yopilib qolgan bo'lsa — to'xtatilgan deb belgilash
  if (RUNNING.includes(j.status) && !ctrls.has(id)) { j.status = "paused"; j.stage = "paused"; }
  cache.set(id, j);
  return j;
}

export async function createCloudJob(source: CloudSource, options: CloudOptions, opts: { blob?: Blob; duration?: number | null }): Promise<string> {
  const id = newId();
  const job: CloudJob = {
    id, kind: "cloud", created: Date.now(), source, options, status: "queued", stage: "queued", progress: 0, detail: {},
    error: null, duration: opts.duration || 0, processed: 0, segments: [], live: [], usage: emptyUsage(), model: "",
    started: Date.now(), finished: null, warnings: [],
  };
  if (opts.blob) {
    try { await idbPut("blobs", id, opts.blob); } catch { job.warnings.push("blob_not_saved"); }
    blobs.set(id, opts.blob);
  }
  upsertHistory({ id, token: "", kind: "cloud", source: source.type, filename: source.name, created: job.created,
    duration: job.duration, language: options.language, status: "queued", progress: 0 } as any);
  await persist(job, true);
  startCloudJob(id);
  return id;
}

const blobs = new Map<string, Blob>();
async function getBlob(id: string): Promise<Blob | null> {
  return blobs.get(id) || (await idbGet<Blob>("blobs", id)) || null;
}
export async function mediaUrl(job: CloudJob): Promise<string | null> {
  const b = await getBlob(job.id);
  return b ? URL.createObjectURL(b) : null;
}

export function cancelCloudJob(id: string) {
  ctrls.get(id)?.abort();
}

export async function deleteCloudJob(id: string) {
  cancelCloudJob(id);
  const j = await loadCloudJob(id);
  if (j?.file?.name && getKey()) deleteFile(j.file.name);
  cache.delete(id);
  blobs.delete(id);
  inlineCache.delete(id);
  await idbDel("jobs", id);
  await idbDel("blobs", id);
  await idbDel("summaries", id);
  removeHistory(id);
}

export async function saveCloudEdit(id: string, text: string) {
  const j = await loadCloudJob(id);
  if (!j) throw new Error("not_found");
  j.edited = text;
  cache.set(id, j);
  await idbPut("jobs", id, j);
}

// ---------------- prompt ----------------
function fmt(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  return `${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function transcriptPrompt(o: CloudOptions, video: boolean, range: { from: number; to?: number; relative: boolean; tail: string[] }): string {
  const L: string[] = [];
  L.push(`You are a professional transcriptionist. Transcribe the speech in the attached ${video ? "video (use only what is SPOKEN in the audio track)" : "recording"} completely and word for word.`);
  const lang = o.language;
  if (lang === "uz" || lang === "auto") {
    L.push("The speech is mainly in UZBEK (it may include Russian or English words, regional dialects, or occasional Kazakh/Kyrgyz speakers).");
    L.push("Write Uzbek speech in the official modern Uzbek LATIN alphabet with correct orthography: o‘ and g‘ written with the ‘ sign (U+2018), the tutuq belgisi as ’ (U+2019) — e.g. ta’lim, ma’no, sur’at, e’tibor; sh, ch, ng as usual. Never write Uzbek in Cyrillic. Keep Russian/English words as spoken in their normal spelling.");
    L.push("Dialect words: write the word the speaker actually said, in standard Uzbek spelling when it is the same word. Do not replace words with synonyms.");
    if (lang === "auto") L.push("If a fragment is in another language, write it in that language and its standard script.");
  } else {
    const name = lang === "kk" ? "KAZAKH" : "KYRGYZ";
    L.push(`The speech is mainly in ${name}.`);
    if (o.script === "latin") L.push(lang === "kk" ? "Write it in the official Kazakh Latin alphabet (2021)." : "Write it in Latin script using a consistent Turkic-style transliteration (ş, ç, ñ, ö, ü, ı).");
    else L.push(`Write it in the standard ${name === "KAZAKH" ? "Kazakh" : "Kyrgyz"} Cyrillic orthography.`);
  }
  L.push(o.mode === "verbatim"
    ? "Verbatim mode: keep every spoken word, including fillers (ee, mm) and repetitions."
    : "Clean mode: omit fillers (ee, mm, hmm) and accidental stutters/repetitions, but never omit or change meaningful words.");
  L.push("Use correct punctuation (. , ? ! : —) and capitalization. Write numbers as digits (2026-yil, 340 nafar, 15%).");
  L.push("Do NOT translate, summarize, shorten, paraphrase or add anything. Do not skip any part. Unintelligible words: [eshitilmadi]. Long music or silence: one short line like [musiqa].");
  L.push("OUTPUT FORMAT — plain text only, one sentence or short thought (about 5–30 seconds of speech) per line:");
  L.push("[HH:MM:SS] text");
  L.push("The time is when that line starts. Put an empty line between paragraphs (when the topic or the speaker changes). No headings, no comments, no markdown, no code fences.");
  if (range.relative && range.to != null) {
    L.push(`You are given only an excerpt of a longer recording. Transcribe the whole excerpt; count times from the beginning of THIS excerpt (00:00:00).`);
  } else if (range.from > 0) {
    L.push(`The transcript up to ${fmt(range.from)} is already done. Continue from ${fmt(range.from)} (times are from the very beginning of the recording) until the end${range.to != null ? ` or until ${fmt(range.to)}` : ""}. Do not repeat earlier lines.`);
    if (range.tail.length) L.push("The last lines already written were:\n" + range.tail.join("\n"));
  }
  if (o.vocabulary.trim()) L.push("Spell these names and terms exactly like this: " + o.vocabulary.trim() + ".");
  return L.join("\n");
}

// ---------------- javobni tahlil qilish ----------------
const LINE = /^\s*(?:[-*•]\s*)?[[(]?\s*((?:\d{1,2}:)?\d{1,3}:\d{2})(?:[.,]\d+)?\s*[\])]?\s*[-–—:|]?\s*(.*)$/;

function parseClock(s: string): number {
  const p = s.split(":").map((x) => parseInt(x, 10));
  return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
}

export interface Line { start: number; text: string; para: boolean }

export function parseTranscript(raw: string): Line[] {
  const txt = raw.replace(/^```[a-z]*\s*/i, "").replace(/```\s*$/, "").replace(/\*\*/g, "");
  const out: Line[] = [];
  let para = false;
  for (const ln of txt.split(/\r?\n/)) {
    if (!ln.trim()) { if (out.length) para = true; continue; }
    const m = LINE.exec(ln);
    if (m) {
      const text = m[2].replace(/\s+/g, " ").trim();
      if (!text) { para = true; continue; }
      out.push({ start: parseClock(m[1]), text, para: para || out.length === 0 });
      para = false;
    } else if (out.length) {
      out[out.length - 1].text += " " + ln.replace(/\s+/g, " ").trim();
    } else if (ln.trim().length > 2 && !/^#|transcri/i.test(ln.trim())) {
      out.push({ start: 0, text: ln.replace(/\s+/g, " ").trim(), para: true });
    }
  }
  return out;
}

const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();

/** Yangi satrlarni umumiy ro'yxatga qo'shish: vaqtlarni moslash, takror va "aylana"larni olib tashlash. */
export function mergeLines(all: CloudSeg[], lines: Line[], from: number, to: number | undefined, relative: boolean): CloudSeg[] {
  if (!lines.length) return [];
  let ls = lines.map((l) => ({ ...l }));
  const span = to != null ? to - from : Infinity;
  const maxT = Math.max(...ls.map((l) => l.start));
  if (from > 0) {
    if (relative) {
      // model baribir mutlaq vaqt yozgan bo'lsa
      const absolute = ls[0].start >= from - 20 && maxT > span + 30;
      if (!absolute) ls = ls.map((l) => ({ ...l, start: l.start + from }));
    } else if (ls[0].start < from - 30 && maxT <= span + 30 && span < Infinity) {
      ls = ls.map((l) => ({ ...l, start: l.start + from }));
    }
  }
  const tail = all.slice(-4).map((s) => norm(s.text));
  let lastStart = all.length ? all[all.length - 1].start : -1;
  const out: CloudSeg[] = [];
  let repeat = 0;
  for (const l of ls) {
    if (l.start < from - 3) continue;
    if (to != null && l.start > to + 5) continue;
    const n = norm(l.text);
    if (!n) continue;
    if (tail.includes(n) && l.start <= from + 30) continue;
    const prev = out.length ? norm(out[out.length - 1].text) : tail[tail.length - 1];
    if (n === prev) { repeat += 1; if (repeat >= 1) continue; } else repeat = 0;
    let start = l.start;
    if (start < lastStart) {
      if (lastStart - start > 60) continue; // orqaga sakrash — ehtimol takrorlash aylanasi
      start = lastStart;
    }
    out.push({ start, end: start, text: l.text, para: l.para });
    lastStart = start;
  }
  return out;
}

function fixEnds(segs: CloudSeg[], duration: number) {
  for (let i = 0; i < segs.length; i++) {
    const s = segs[i];
    const words = s.text.split(/\s+/).length;
    const est = s.start + Math.max(1.5, words * 0.45 + 0.8);
    const next = i + 1 < segs.length ? segs[i + 1].start : Infinity;
    let end = Math.min(next, Math.max(est, Math.min(next, s.start + 1)));
    if (next !== Infinity && next - s.start < 40) end = next;
    if (duration > 0) end = Math.min(end, duration);
    s.end = Math.max(s.start + 0.3, end);
  }
}

// ---------------- media qismlari ----------------
async function mediaPart(job: CloudJob): Promise<any> {
  const s = job.source;
  if (s.type === "youtube" && s.videoId) return { fileData: { fileUri: youtubeUrl(s.videoId) } };
  if (job.inline) {
    let b64 = inlineCache.get(job.id);
    if (!b64) {
      const blob = await getBlob(job.id);
      if (!blob) throw new GeminiError("file_expired");
      b64 = await blobToBase64(blob);
      inlineCache.set(job.id, b64);
    }
    return { inlineData: { mimeType: s.mime || "audio/mpeg", data: b64 } };
  }
  if (job.external && s.url) return { fileData: { fileUri: s.url, mimeType: s.mime || guessMime(s.url) } };
  if (job.file) return { fileData: { fileUri: job.file.uri, mimeType: job.file.mimeType } };
  throw new GeminiError("file_expired");
}

const MIME: Record<string, string> = {
  mp3: "audio/mpeg", wav: "audio/wav", m4a: "audio/mp4", aac: "audio/aac", ogg: "audio/ogg", oga: "audio/ogg", opus: "audio/ogg",
  flac: "audio/flac", aif: "audio/aiff", aiff: "audio/aiff", mp4: "video/mp4", m4v: "video/mp4", mov: "video/quicktime",
  webm: "video/webm", mpeg: "video/mpeg", mpg: "video/mpeg", avi: "video/x-msvideo", wmv: "video/x-ms-wmv", "3gp": "video/3gpp",
  flv: "video/x-flv", mkv: "video/x-matroska",
};
export function guessMime(name: string, type?: string): string {
  const ext = (/\.([a-z0-9]{2,5})(?:$|[?#])/i.exec(name)?.[1] || "").toLowerCase();
  if (MIME[ext]) return MIME[ext];
  if (type && /^(audio|video)\//.test(type)) return type === "audio/x-m4a" ? "audio/mp4" : type;
  return "audio/mpeg";
}
export const isVideoMime = (m: string) => m.startsWith("video/");

// ---------------- havoladan yuklab olish (CORS ruxsat bersa) ----------------
async function fetchLink(job: CloudJob, signal: AbortSignal): Promise<Blob | null> {
  const url = job.source.url!;
  let res: Response;
  try { res = await fetch(url, { signal, mode: "cors", credentials: "omit", referrerPolicy: "no-referrer" }); } catch (e) {
    if ((e as any)?.name === "AbortError") throw new GeminiError("aborted");
    return null; // CORS yoki tarmoq — Gemini'ning o'ziga havolani beramiz
  }
  if (!res.ok) throw new GeminiError("link_unreachable", `HTTP ${res.status}`);
  const ct = (res.headers.get("content-type") || "").split(";")[0].trim();
  if (ct && !/^(audio|video)\/|octet-stream|binary/.test(ct)) throw new GeminiError("link_not_media", ct);
  const total = Number(res.headers.get("content-length") || 0);
  if (total > FILE_MAX) throw new GeminiError("file_too_large_cloud");
  const reader = res.body?.getReader();
  if (!reader) return await res.blob();
  const chunks: BlobPart[] = [];
  let got = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    chunks.push(value as unknown as BlobPart);
    got += value.length;
    if (got > FILE_MAX) throw new GeminiError("file_too_large_cloud");
    job.detail = { done_mb: got / 1048576, total_mb: total ? total / 1048576 : null };
    job.progress = total ? Math.min(10, (got / total) * 10) : Math.min(9, got / 1048576 / 20);
    persist(job);
  }
  const mime = ct && ct !== "application/octet-stream" ? ct : guessMime(url);
  job.source.mime = guessMime(url, mime);
  return new Blob(chunks, { type: job.source.mime });
}

function probeBlobDuration(blob: Blob): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(blob);
    const el = document.createElement(isVideoMime(blob.type) ? "video" : "audio");
    let done = false;
    const fin = (v: number | null) => { if (done) return; done = true; URL.revokeObjectURL(url); resolve(v); };
    el.preload = "metadata";
    el.onloadedmetadata = () => fin(Number.isFinite(el.duration) && el.duration > 0 ? el.duration : null);
    el.onerror = () => fin(null);
    window.setTimeout(() => fin(null), 8000);
    el.src = url;
  });
}

// ---------------- asosiy jarayon ----------------
export function startCloudJob(id: string) {
  if (ctrls.has(id)) return;
  const ctrl = new AbortController();
  ctrls.set(id, ctrl);
  run(id, ctrl.signal).catch(() => undefined).finally(() => ctrls.delete(id));
}

async function run(id: string, signal: AbortSignal) {
  const job = await loadCloudJob(id);
  if (!job) return;
  job.status = "queued";
  job.error = null;
  job.errorDetail = undefined;
  await persist(job);
  try {
    await prepareMedia(job, signal);
    await transcribe(job, signal);
    if (job.options.summaryLang && job.segments.length) {
      job.status = "summarizing"; job.stage = "summarizing"; job.progress = 98; await persist(job);
      try {
        const sm = await makeSummary(timedTranscript(job.segments), job.options.summaryLang, job.source.name, { signal });
        await storeSummary(job.id, sm);
      } catch (e) {
        if ((e as GeminiError).code === "aborted") throw e;
        job.warnings.push("summary_failed");
      }
    }
    job.status = "completed";
    job.stage = "completed";
    job.progress = 100;
    job.finished = Date.now();
    job.live = [];
    if (!job.segments.length) job.warnings.push("no_speech_found");
    await persist(job, true);
  } catch (e) {
    const err = e as GeminiError;
    if (err.code === "aborted") {
      job.status = "cancelled";
      job.stage = "cancelled";
    } else {
      job.status = "failed";
      job.stage = "failed";
      job.error = err.code || "cloud_error";
      job.errorDetail = err.detail || String(err.message || "");
    }
    await persist(job, true);
  }
}

async function prepareMedia(job: CloudJob, signal: AbortSignal) {
  const s = job.source;
  if (s.type === "youtube") return;
  // havola: avval brauzerda yuklab olishga urinamiz
  if (s.type === "url" && !job.external && !(await getBlob(job.id))) {
    job.status = "downloading"; job.stage = "downloading"; await persist(job);
    const blob = await fetchLink(job, signal);
    if (blob) {
      blobs.set(job.id, blob);
      try { await idbPut("blobs", job.id, blob); } catch { /* xotira yetmasa ham davom etadi */ }
      s.size = blob.size;
      if (!job.duration) job.duration = (await probeBlobDuration(blob)) || 0;
    } else {
      job.external = true; // brauzer yuklay olmadi — Gemini havolani o'zi oladi
      s.mime = s.mime || guessMime(s.url || "");
      return;
    }
  }
  if (job.external) return;
  const blob = await getBlob(job.id);
  if (job.file && Date.now() - job.file.at < 46 * 3600_000) {
    const f = await getFile(job.file.name).catch(() => null);
    if (f && (f as any).state !== "FAILED") return;
  }
  if (!blob) throw new GeminiError("file_expired");
  const mime = guessMime(s.name, blob.type || s.mime);
  s.mime = mime;
  if (blob.size <= INLINE_MAX) { job.inline = true; return; }
  job.status = "uploading"; job.stage = "uploading"; job.progress = 0; await persist(job);
  let f: GFile;
  try {
    f = await uploadFile(blob, s.name, mime, (p) => { job.progress = Math.round(p * 0.15 * 10) / 10; job.detail = { upload: Math.round(p) }; persist(job); }, signal);
  } catch (e) {
    const c = (e as GeminiError).code;
    if ((c === "upload_header_hidden" || c === "cloud_unreachable") && blob.size <= INLINE_FALLBACK_MAX) { job.inline = true; return; }
    throw e;
  }
  job.status = "processing"; job.stage = "processing"; await persist(job);
  f = await waitActive(f, signal);
  job.file = { name: f.name, uri: f.uri, mimeType: f.mimeType || mime, at: Date.now() };
  await persist(job, true);
}

async function transcribe(job: CloudJob, signal: AbortSignal) {
  const s = job.source;
  const video = s.type === "youtube" || isVideoMime(s.mime || "");
  const fileLike = !!job.file || !!job.inline;
  if (job.clip == null) job.clip = fileLike && job.duration > WIN * 1.3 ? true : false;
  let from = job.segments.length ? job.segments[job.segments.length - 1].end : 0;
  let guard = 0;
  let noProgress = 0;
  const maxIter = Math.ceil((job.duration || 3 * 3600) / WIN) * 3 + 12;
  job.status = "transcribing";
  job.stage = "transcribing";
  await persist(job);

  while (guard++ < maxIter) {
    if (signal.aborted) throw new GeminiError("aborted");
    if (job.duration > 0 && from >= job.duration - 1.5) break;
    const useWindow = !!job.clip && job.duration > 0;
    const to = useWindow ? Math.min(job.duration, from + WIN) : undefined;
    const relative = useWindow && from > 0;
    const part = await mediaPart(job);
    if (useWindow) part.videoMetadata = { startOffset: `${Math.floor(from)}s`, endOffset: `${Math.ceil(to!)}s` };
    else if (from > 0 && fileLike && job.clip !== false) part.videoMetadata = { startOffset: `${Math.floor(from)}s` };
    const tail = job.segments.slice(-3).map((x) => `[${fmt(x.start)}] ${x.text}`);
    const prompt = transcriptPrompt(job.options, video, { from, to, relative, tail });

    let res;
    try {
      res = await generate([part, { text: prompt }], {
        signal, mediaLow: video, context: s.type === "youtube" ? "youtube" : s.type === "url" && job.external ? "url" : "",
        onText: (txt) => {
          const lines = parseTranscript(txt).slice(-6);
          job.live = lines.map((l) => `${relative ? fmt(l.start + from) : fmt(l.start)}\u0001${l.text}`);
          const lastT = lines.length ? (relative ? lines[lines.length - 1].start + from : lines[lines.length - 1].start) : from;
          job.processed = Math.max(job.processed, Math.min(job.duration || lastT, lastT));
          job.progress = progressOf(job);
          persist(job);
        },
        onStatus: (stage, detail) => { job.stage = stage; job.detail = detail; persist(job); },
      });
    } catch (e) {
      const err = e as GeminiError;
      // audio uchun videoMetadata qabul qilinmasa — kesishsiz rejimga o'tamiz
      if (part.videoMetadata && err.code === "cloud_error" && /video_?metadata|offset/i.test(err.detail)) {
        job.clip = false;
        continue;
      }
      throw err;
    }
    job.stage = "transcribing";
    job.detail = {};
    job.model = res.model;
    job.usage = addUsage(job.usage, res.usage, res.model);

    // kesish (offset) haqiqatan ishladimi? — audio tokenlar soni bo'yicha
    if (useWindow && res.usage && job.duration > 0) {
      const audioTok = (res.usage.promptTokensDetails || []).filter((d: any) => /AUDIO/i.test(d.modality)).reduce((a: number, d: any) => a + (d.tokenCount || 0), 0)
        || res.usage.promptTokenCount || 0;
      const expected = (to! - from) * 32;
      if (audioTok > expected * 1.8 && job.duration * 32 > expected * 1.8) job.clip = false;
    }

    let lines = parseTranscript(res.text);
    const cut = res.finish === "MAX_TOKENS" || res.finish === "INTERRUPTED";
    let resumeAt: number | null = null;
    if (cut && lines.length > 1) {
      const last = lines.pop()!;
      resumeAt = relative ? last.start + from : last.start;
    }
    const added = mergeLines(job.segments, lines, from, to, relative);
    job.segments.push(...added);
    fixEnds(job.segments, job.duration);
    const lastStart = job.segments.length ? job.segments[job.segments.length - 1].start : 0;
    job.live = [];

    if (cut) {
      const next = resumeAt ?? (added.length ? lastStart + 1 : null);
      if (next == null || next <= from + 2) {
        if (++noProgress >= 2) { job.warnings.push("cloud_incomplete"); break; }
        if (to != null) { from = to; }
        continue;
      }
      noProgress = 0;
      from = next;
    } else if (to != null) {
      from = to;
      noProgress = 0;
    } else {
      // kesishsiz rejim: model to'xtadi. Davomiylik ma'lum bo'lsa va oxirigacha yetmagan bo'lsa — davom ettiramiz
      const covered = job.segments.length ? job.segments[job.segments.length - 1].end : from;
      if (job.duration > 0 && covered < job.duration - 90 && added.length > 0) {
        from = covered;
        noProgress = 0;
      } else {
        if (job.duration > 0 && covered < job.duration - 90 && job.segments.length) job.warnings.push("cloud_incomplete");
        break;
      }
    }
    job.processed = Math.max(job.processed, Math.min(job.duration || from, from));
    job.progress = progressOf(job);
    await persist(job, true);
  }
  if (job.segments.length) {
    const last = job.segments[job.segments.length - 1];
    if (!job.duration || job.duration < last.end) job.duration = Math.max(job.duration, last.end);
  }
  fixEnds(job.segments, job.duration);
}

function progressOf(job: CloudJob): number {
  const base = job.source.type === "youtube" || job.inline || job.external ? 3 : 16;
  if (job.duration > 0) return Math.min(98, base + (98 - base) * Math.min(1, job.processed / job.duration));
  // davomiylik noma'lum: sekin o'suvchi taxmin
  return Math.min(95, base + (95 - base) * (1 - Math.exp(-job.processed / 1800)));
}

// ---------------- natija (ResultView formatida) ----------------
const UNC = /\[(eshitilmadi|неразборчиво|inaudible|unclear|tushunarsiz)[^\]]*\]/i;

export function paragraphsText(segs: { text: string; para: boolean }[]): string {
  const out: string[] = [];
  let cur: string[] = [];
  segs.forEach((s, i) => {
    if (s.para && i > 0 && cur.length) { out.push(cur.join(" ")); cur = []; }
    cur.push(s.text);
  });
  if (cur.length) out.push(cur.join(" "));
  return out.join("\n\n");
}

export function buildResult(job: CloudJob): Result {
  const segments: Segment[] = job.segments.map((s, id) => {
    const toks = s.text.split(/\s+/).filter(Boolean);
    const total = toks.reduce((a, w) => a + w.length + 1, 0) || 1;
    const span = Math.max(0.3, s.end - s.start);
    let acc = 0;
    const words: Word[] = [];
    for (let i = 0; i < toks.length; i++) {
      let w = toks[i];
      // [eshitilmadi] kabi belgilar bir nechta bo'lakka bo'linib qolmasin
      if (w.startsWith("[") && !w.includes("]")) {
        while (i + 1 < toks.length && !w.includes("]")) w += " " + toks[++i];
      }
      const ws = s.start + (acc / total) * span;
      acc += w.length + 1;
      const we = s.start + (acc / total) * span;
      words.push({ t: w, s: Math.round(ws * 100) / 100, e: Math.round(we * 100) / 100, p: null, u: UNC.test(w) });
    }
    return { id, start: s.start, end: s.end, raw: s.text, text: s.text, para: s.para, low: false, words };
  });
  const text = paragraphsText(job.segments);
  const words = segments.reduce((a, s) => a + s.words.length, 0);
  const uncertain = segments.reduce((a, s) => a + s.words.filter((w) => w.u).length, 0);
  return {
    job_id: job.id, filename: job.source.name, language: job.options.language === "auto" ? "uz" : job.options.language,
    detected_language: null, language_probability: null, raw_text: text, latin_text: text, edited_text: job.edited ?? text, segments,
    stats: { words, uncertain, segments: segments.length, paragraphs: segments.filter((s) => s.para).length, low_segments: 0 },
    warnings: job.warnings.filter((w, i, a) => a.indexOf(w) === i && w !== "blob_not_saved"), duration: job.duration,
    options: { language: job.options.language, script: job.options.script, mode: job.options.mode, punctuation: true, paragraphs: true,
      quality: "", engine: "gemini", vocabulary: job.options.vocabulary },
    model: `Gemini · ${job.model || "?"} (cloud)`,
    processing_seconds: ((job.finished || Date.now()) - job.started) / 1000,
    waveform: [],
    cloud_usage: { model: job.model, input_tokens: job.usage.input_tokens, output_tokens: job.usage.output_tokens, cost_usd: job.usage.cost_usd },
  };
}

/** Matn + vaqt belgilari (xulosa uchun). */
export function timedTranscript(segs: { start: number; text: string }[]): string {
  return segs.map((s) => `[${fmt(s.start)}] ${s.text}`).join("\n");
}
export { fmt as fmtClock };
