// Brauzerdan to'g'ridan-to'g'ri Google Gemini API bilan ishlash (BYOK — foydalanuvchining o'z kaliti).
// Kalit faqat shu brauzerda saqlanadi va faqat generativelanguage.googleapis.com ga yuboriladi.

const KEY_LOCAL = "ilmhubstt.geminiKey";
const MODEL_LOCAL = "ilmhubstt.geminiModel";
const BASE_LOCAL = "ilmhubstt.geminiBase"; // faqat test uchun (soxta server)
export const DEFAULT_BASE = "https://generativelanguage.googleapis.com";

export class GeminiError extends Error {
  code: string;
  detail: string;
  status: number;
  constructor(code: string, detail = "", status = 0) {
    super(code);
    this.code = code;
    this.detail = detail;
    this.status = status;
  }
}

// ---------------- kalit va sozlamalar ----------------
export function getKey(): string {
  try { return localStorage.getItem(KEY_LOCAL) || sessionStorage.getItem(KEY_LOCAL) || ""; } catch { return ""; }
}
export function setKey(key: string, remember = true) {
  try {
    localStorage.removeItem(KEY_LOCAL);
    sessionStorage.removeItem(KEY_LOCAL);
    if (key) (remember ? localStorage : sessionStorage).setItem(KEY_LOCAL, key);
  } catch { /* xususiy rejim */ }
  modelsCache = null;
}
export function keyHint(key = getKey()): string {
  return key ? "…" + key.slice(-4) : "";
}
export function getModelPref(): string {
  try { return localStorage.getItem(MODEL_LOCAL) || ""; } catch { return ""; }
}
export function setModelPref(m: string) {
  try { m ? localStorage.setItem(MODEL_LOCAL, m) : localStorage.removeItem(MODEL_LOCAL); } catch { /* */ }
}
function base(): string {
  try { return (localStorage.getItem(BASE_LOCAL) || DEFAULT_BASE).replace(/\/+$/, ""); } catch { return DEFAULT_BASE; }
}
export function cleanKey(raw: string): string {
  return raw.trim().replace(/^["'`]+|["'`]+$/g, "").replace(/\s+/g, "");
}
export const KEY_RE = /^[A-Za-z0-9_\-.~+/=]{20,400}$/;

const sleep = (ms: number, signal?: AbortSignal) => new Promise<void>((res, rej) => {
  if (signal?.aborted) return rej(new GeminiError("aborted"));
  const id = window.setTimeout(() => { signal?.removeEventListener("abort", on); res(); }, ms);
  const on = () => { window.clearTimeout(id); rej(new GeminiError("aborted")); };
  signal?.addEventListener("abort", on, { once: true });
});

// ---------------- xatolarni tushunarli kodga aylantirish ----------------
function mapError(status: number, body: string, context = ""): GeminiError {
  let msg = body;
  let blob = body;
  try {
    const j = JSON.parse(body);
    const err = Array.isArray(j) ? j[0]?.error : j.error;
    if (err) { msg = String(err.message || ""); blob = JSON.stringify(err); }
  } catch { /* matn */ }
  const low = msg.toLowerCase();
  const detail = msg.slice(0, 400);
  if (status === 429) return new GeminiError("cloud_rate_limited", detail, status);
  if (/SERVICE_DISABLED|has not been used|is disabled/.test(blob)) return new GeminiError("cloud_api_disabled", detail, status);
  if (/location|region|country/.test(low) && status !== 404) return new GeminiError("cloud_region", detail, status);
  if (/API_KEY_SERVICE_BLOCKED|API_KEY_HTTP_REFERRER_BLOCKED|referer|referrer/.test(blob) || /blocked/.test(low)) return new GeminiError("cloud_key_restricted", detail, status);
  if (status === 401 || status === 403 || /API_KEY_INVALID|api key not valid|api_key/i.test(blob)) return new GeminiError("cloud_auth_failed", detail, status);
  if (status === 404) return new GeminiError("cloud_model_not_found", detail, status);
  if (context === "youtube" && (status === 400 || status === 403) && /youtube|video|file_uri|url/i.test(msg)) return new GeminiError("yt_unavailable", detail, status);
  if (context === "url" && status === 400 && /url|uri|fetch|access/i.test(msg)) return new GeminiError("link_unreachable", detail, status);
  if (/token count|exceeds the maximum|too many tokens|context length/i.test(msg)) return new GeminiError("too_long_for_model", detail, status);
  if (/unsupported|mime type|not supported/i.test(msg)) return new GeminiError("unsupported_format", detail, status);
  if (status >= 500) return new GeminiError("cloud_error", detail, status);
  return new GeminiError("cloud_error", detail, status);
}

function retryDelay(body: string, attempt: number): number {
  try {
    const j = JSON.parse(body);
    for (const d of (j.error?.details || [])) {
      if (d.retryDelay) return Math.min(120, parseFloat(String(d.retryDelay)) + 1) * 1000;
    }
  } catch { /* */ }
  return Math.min(90, 5 * 2 ** attempt) * 1000;
}

async function call(path: string, init: RequestInit, key: string, context = ""): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(base() + path, { ...init, headers: { ...(init.headers || {}), "x-goog-api-key": key } });
  } catch (e) {
    if ((e as any)?.name === "AbortError") throw new GeminiError("aborted");
    throw new GeminiError("cloud_unreachable", String((e as Error)?.message || e));
  }
  if (!res.ok) throw mapError(res.status, await res.text().catch(() => ""), context);
  return res;
}

// ---------------- modellar ----------------
let modelsCache: { key: string; at: number; list: string[] } | null = null;

export async function listModels(key = getKey()): Promise<string[]> {
  if (!key) throw new GeminiError("gemini_key_missing");
  if (modelsCache && modelsCache.key === key && Date.now() - modelsCache.at < 3600_000) return modelsCache.list;
  const res = await call("/v1beta/models?pageSize=200", { method: "GET" }, key);
  const data = await res.json().catch(() => ({}));
  const list: string[] = (data.models || [])
    .filter((m: any) => !m.supportedGenerationMethods || m.supportedGenerationMethods.includes("generateContent"))
    .map((m: any) => String(m.name || "").replace(/^models\//, ""))
    .filter((n: string) => n.startsWith("gemini"));
  modelsCache = { key, at: Date.now(), list };
  return list;
}

/** Kalitni tekshirish: modellar ro'yxatini olish. */
export async function verifyKey(key: string): Promise<string[]> {
  modelsCache = null;
  return listModels(key);
}

function version(m: string): number {
  const v = /gemini-(\d+(?:\.\d+)?)/.exec(m);
  return v ? parseFloat(v[1]) : 0;
}
const BAD = /tts|image|live|embedding|audio|native|thinking-exp|learnlm|robotics|computer|search|aqa|banana|veo|lyria/i;

/** Nutq uchun tavsiya etilgan modellar tartibi: eng yangi "flash" → lite → pro. */
export function rankModels(models: string[]): string[] {
  const ok = models.filter((m) => !BAD.test(m));
  const score = (m: string) => {
    let s = version(m) * 10;
    if (/flash/.test(m) && !/lite/.test(m)) s += 5;
    else if (/flash-lite/.test(m)) s += 2;
    else if (/pro/.test(m)) s += 3;
    if (/preview|exp/.test(m)) s -= 0.5;
    if (/-\d{3,}$|-\d{2}-\d{2}/.test(m)) s -= 0.2; // sana bilan yozilgan aniq versiyalar
    return s;
  };
  return [...ok].sort((a, b) => score(b) - score(a));
}

const PROVEN = ["gemini-3-flash-preview", "gemini-3-flash", "gemini-2.5-flash"];
const FALLBACK = ["gemini-3-flash-preview", "gemini-3-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite"];

export async function modelCandidates(key = getKey()): Promise<string[]> {
  const pref = getModelPref();
  let models: string[] = [];
  try { models = await listModels(key); } catch (e) {
    if ((e as GeminiError).code !== "cloud_unreachable") throw e;
  }
  if (!models.length) return pref ? [pref, ...FALLBACK.filter((m) => m !== pref)] : FALLBACK;
  const ranked = rankModels(models);
  // Avval sinalgan, barqaror ishlaydigan modellar (lokal versiyada shular ishlatilgan), keyin eng yangilari.
  // Eng yangi model ko'pincha "high demand" (503) bo'ladi, shuning uchun u birinchi emas.
  const proven = PROVEN.filter((m) => models.includes(m));
  const order = [...proven, ...ranked.filter((m) => !proven.includes(m))];
  const out = (pref && models.includes(pref) ? [pref, ...order.filter((m) => m !== pref)] : order).slice(0, 4);
  // barqaror (preview bo'lmagan) zaxira model doim ro'yxatda bo'lsin
  for (const stable of ["gemini-2.5-flash", "gemini-3-flash"]) if (models.includes(stable) && !out.includes(stable)) { out.push(stable); break; }
  return out;
}

// ---------------- narx (taxminiy, USD / 1M token) ----------------
// [matn/rasm/video kirish, audio kirish, chiqish]
const PRICES: [RegExp, [number, number, number]][] = [
  [/gemini-3(\.\d+)?-flash-lite/, [0.25, 0.5, 1.5]],
  [/gemini-3(\.\d+)?-flash/, [0.5, 1.0, 3.0]],
  [/gemini-3(\.\d+)?-pro/, [2.0, 2.0, 12.0]],
  [/gemini-2\.5-flash-lite/, [0.1, 0.3, 0.4]],
  [/gemini-2\.5-flash/, [0.3, 1.0, 2.5]],
  [/gemini-2\.5-pro/, [1.25, 1.25, 10.0]],
];
export interface Usage { input_tokens: number; audio_tokens: number; output_tokens: number; cost_usd: number; model: string; requests: number }
export const emptyUsage = (): Usage => ({ input_tokens: 0, audio_tokens: 0, output_tokens: 0, cost_usd: 0, model: "", requests: 0 });

export function addUsage(u: Usage, meta: any, model: string): Usage {
  if (!meta) return u;
  const input = Number(meta.promptTokenCount || 0);
  let audio = 0;
  for (const d of meta.promptTokensDetails || []) if (String(d.modality).toUpperCase() === "AUDIO") audio += Number(d.tokenCount || 0);
  const out = Number(meta.candidatesTokenCount || 0) + Number(meta.thoughtsTokenCount || 0);
  const p = (PRICES.find(([re]) => re.test(model)) || [null, [0.5, 1.0, 3.0]])[1] as [number, number, number];
  const cost = ((input - audio) * p[0] + audio * p[1] + out * p[2]) / 1e6;
  return {
    input_tokens: u.input_tokens + input, audio_tokens: u.audio_tokens + audio, output_tokens: u.output_tokens + out,
    cost_usd: u.cost_usd + cost, model, requests: u.requests + 1,
  };
}

// ---------------- generateContent (oqimli) ----------------
export interface GenResult { text: string; finish: string; usage: any; model: string }
export interface GenOptions {
  key?: string;
  signal?: AbortSignal;
  onText?: (full: string) => void;
  onStatus?: (stage: string, detail: Record<string, any>) => void;
  context?: string; // "youtube" | "url" | ""
  json?: boolean;
  schema?: any;
  maxWaitMs?: number;
  models?: string[];
  mediaLow?: boolean;
}

function genConfig(model: string, o: GenOptions, flags: { thinking: boolean; media: boolean; maxOut: number }) {
  const g: any = { maxOutputTokens: flags.maxOut, temperature: model.startsWith("gemini-3") ? 1.0 : 0.2 };
  if (o.json) {
    g.responseMimeType = "application/json";
    if (o.schema) g.responseSchema = o.schema;
  }
  if (flags.media && o.mediaLow) g.mediaResolution = "MEDIA_RESOLUTION_LOW";
  if (flags.thinking) {
    if (model.startsWith("gemini-2.5")) g.thinkingConfig = { thinkingBudget: /flash/.test(model) ? 0 : 128 };
    else if (/^gemini-[3-9]/.test(model)) g.thinkingConfig = { thinkingLevel: "low" };
  }
  return g;
}

async function readSSE(res: Response, onEvent: (data: any) => void, signal?: AbortSignal): Promise<void> {
  const reader = res.body?.getReader();
  if (!reader) {
    const txt = await res.text();
    for (const ev of parseSSE(txt).events) onEvent(ev);
    return;
  }
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    if (signal?.aborted) { try { await reader.cancel(); } catch { /* */ } throw new GeminiError("aborted"); }
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parsed = parseSSE(buf);
    buf = parsed.rest;
    for (const ev of parsed.events) onEvent(ev);
  }
  buf += dec.decode();
  for (const ev of parseSSE(buf + "\n\n").events) onEvent(ev);
}

export function parseSSE(buf: string): { events: any[]; rest: string } {
  const events: any[] = [];
  const norm = buf.replace(/\r\n/g, "\n");
  const blocks = norm.split("\n\n");
  const rest = blocks.pop() || "";
  for (const b of blocks) {
    const data = b.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n");
    if (!data || data === "[DONE]") continue;
    try { events.push(JSON.parse(data)); } catch { /* buzilgan bo'lak */ }
  }
  return { events, rest };
}

/** Oqimli generateContent. 5xx/429 da qayta urinadi, keyin ixtiyoriy sozlamalarsiz, so'ng keyingi modelga o'tadi;
 * hamma modellar band bo'lsa — kutib yangi aylana. Umumiy kutish maxWaitMs dan oshmaydi. */
export async function generate(parts: any[], o: GenOptions = {}): Promise<GenResult> {
  const key = o.key || getKey();
  if (!key) throw new GeminiError("gemini_key_missing");
  const models = o.models?.length ? o.models : await modelCandidates(key);
  const maxWait = o.maxWaitMs ?? 900_000;
  let waited = 0;
  let lastErr: GeminiError | null = null;
  const dead = new Set<string>(); // topilmagan modellar
  const flagsOf = new Map<string, { thinking: boolean; media: boolean; maxOut: number }>();

  const pause = async (stage: string, ms: number, attempt: number, model: string, err: GeminiError | null) => {
    if (waited + ms > maxWait) throw err || new GeminiError("cloud_error");
    waited += ms;
    o.onStatus?.(stage, { wait: Math.round(ms / 1000), attempt, model, message: err?.detail?.slice(0, 200) || "" });
    await sleep(ms, o.signal);
  };

  for (let round = 0; round < 6; round++) {
    let tried = 0;
    for (const model of models) {
      if (dead.has(model)) continue;
      tried += 1;
      if (!flagsOf.has(model)) flagsOf.set(model, { thinking: true, media: true, maxOut: 65536 });
      const flags = flagsOf.get(model)!;
      let attempt = 0;
      let net = 0;
      for (;;) {
        if (o.signal?.aborted) throw new GeminiError("aborted");
        const body = { contents: [{ role: "user", parts }], generationConfig: genConfig(model, o, flags) };
        let res: Response | null = null;
        try {
          res = await fetch(`${base()}/v1beta/models/${encodeURIComponent(model)}:streamGenerateContent?alt=sse`, {
            method: "POST", signal: o.signal,
            headers: { "content-type": "application/json", "x-goog-api-key": key },
            body: JSON.stringify(body),
          });
        } catch (e) {
          if ((e as any)?.name === "AbortError") throw new GeminiError("aborted");
          lastErr = new GeminiError("cloud_unreachable", String((e as Error)?.message || e));
          if (++net > 3) throw lastErr;
          await pause("cloud_retry", 3000 * net, net, model, lastErr);
          continue;
        }
        let status = res.status;
        let errText = "";
        if (res.ok) {
          let text = "";
          let finish = "";
          let usage: any = null;
          let blocked = "";
          let streamErr: any = null;
          try {
            await readSSE(res, (ev) => {
              if (ev.error) { streamErr = ev.error; return; }
              if (ev.promptFeedback?.blockReason) blocked = ev.promptFeedback.blockReason;
              const c = ev.candidates?.[0];
              if (c) {
                for (const p of c.content?.parts || []) if (typeof p.text === "string" && !p.thought) text += p.text;
                if (c.finishReason) finish = c.finishReason;
              }
              if (ev.usageMetadata) usage = ev.usageMetadata;
              o.onText?.(text);
            }, o.signal);
          } catch (e) {
            if ((e as GeminiError).code === "aborted") throw e;
            finish = finish || "INTERRUPTED"; // oqim uzildi: olingan qism qaytadi, chaqiruvchi davom ettiradi
          }
          if (!streamErr || text) {
            if (streamErr) finish = finish || "INTERRUPTED";
            if (blocked && !text) throw new GeminiError("cloud_blocked", blocked);
            if (!text && !finish) { status = 500; errText = '{"error":{"message":"empty response"}}'; }
            else return { text, finish: finish || "STOP", usage, model };
          } else {
            status = Number(streamErr.code) || 500;
            errText = JSON.stringify({ error: streamErr });
          }
        } else {
          errText = await res.text().catch(() => "");
        }
        if (status === 400 && flags.thinking && /thinking/i.test(errText)) { flags.thinking = false; continue; }
        if (status === 400 && flags.media && /media_?resolution/i.test(errText)) { flags.media = false; continue; }
        if (status === 400 && flags.maxOut > 8192 && /max_?output_?tokens/i.test(errText)) { flags.maxOut = flags.maxOut > 32768 ? 32768 : 8192; continue; }
        if (status === 404 || (status === 400 && /not supported for|is not found|unknown model|not available/i.test(errText) && !/youtube|video/i.test(errText))) {
          lastErr = mapError(404, errText);
          dead.add(model);
          break;
        }
        if (status === 429 || status >= 500) {
          lastErr = mapError(status, errText, o.context);
          attempt += 1;
          if (status >= 500 && attempt === 2 && (flags.media || flags.thinking)) {
            // ba'zi model/YouTube birikmalarida ixtiyoriy sozlamalar 500 beradi — ularsiz urinib ko'ramiz
            flags.media = false;
            flags.thinking = false;
            await pause("cloud_retry", 2000, attempt, model, lastErr);
            continue;
          }
          // "high demand / overloaded" — shu model hozir band: darhol keyingi modelga o'tamiz
          if (status === 503 || /high demand|overloaded|UNAVAILABLE/i.test(errText)) break;
          if (attempt >= 3 || (status === 429 && attempt >= 2)) break; // keyingi modelga o'tamiz
          const d = status === 429 ? Math.min(retryDelay(errText, attempt), 30_000) : 4000 * attempt;
          await pause(status === 429 ? "rate_limited_wait" : "cloud_retry", d, attempt, model, lastErr);
          continue;
        }
        throw mapError(status, errText, o.context);
      }
    }
    if (!tried) break;
    // hamma modellar band — biroz kutib yangi aylana
    const d = Math.min(90_000, 15_000 * 2 ** round);
    await pause(lastErr?.status === 429 ? "rate_limited_wait" : "cloud_retry", d, round + 1, "", lastErr);
  }
  throw lastErr || new GeminiError("cloud_model_not_found");
}

// ---------------- Files API (katta fayllarni yuklash, 2 GB gacha) ----------------
export interface GFile { name: string; uri: string; mimeType: string; state?: string; sizeBytes?: string }

function xhrSend(method: string, url: string, headers: Record<string, string>, body: Blob | string | null,
  onProgress?: (loaded: number, total: number) => void, signal?: AbortSignal): Promise<XMLHttpRequest> {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open(method, url);
    for (const [k, v] of Object.entries(headers)) x.setRequestHeader(k, v);
    if (onProgress) x.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded, e.total); };
    x.onload = () => resolve(x);
    x.onerror = () => reject(new GeminiError("cloud_unreachable", "upload network error"));
    x.onabort = () => reject(new GeminiError("aborted"));
    signal?.addEventListener("abort", () => x.abort(), { once: true });
    x.send(body);
  });
}

export async function uploadFile(blob: Blob, displayName: string, mime: string,
  onProgress?: (p: number) => void, signal?: AbortSignal, key = getKey()): Promise<GFile> {
  if (!key) throw new GeminiError("gemini_key_missing");
  const startUrl = `${base()}/upload/v1beta/files`;
  const start = await xhrSend("POST", startUrl, {
    "x-goog-api-key": key,
    "X-Goog-Upload-Protocol": "resumable",
    "X-Goog-Upload-Command": "start",
    "X-Goog-Upload-Header-Content-Length": String(blob.size),
    "X-Goog-Upload-Header-Content-Type": mime,
    "Content-Type": "application/json",
  }, JSON.stringify({ file: { display_name: displayName.slice(0, 120) } }), undefined, signal);
  if (start.status >= 400) throw mapError(start.status, start.responseText);
  const upUrl = start.getResponseHeader("x-goog-upload-url") || start.getResponseHeader("X-Goog-Upload-URL");
  if (!upUrl) throw new GeminiError("upload_header_hidden");
  // katta fayllar 8 MB bo'laklarda (uzilishga chidamli)
  const CH = 8 * 1024 * 1024;
  let offset = 0;
  let last: XMLHttpRequest | null = null;
  while (offset < blob.size || blob.size === 0) {
    const end = Math.min(blob.size, offset + CH);
    const final = end >= blob.size;
    let tries = 0;
    for (;;) {
      try {
        last = await xhrSend("POST", upUrl, {
          "X-Goog-Upload-Command": final ? "upload, finalize" : "upload",
          "X-Goog-Upload-Offset": String(offset),
        }, blob.slice(offset, end), (l) => onProgress?.(Math.min(100, ((offset + l) / Math.max(1, blob.size)) * 100)), signal);
        if (last.status >= 500 && tries < 4) { tries += 1; await sleep(2000 * tries, signal); continue; }
        break;
      } catch (e) {
        if ((e as GeminiError).code === "aborted" || tries >= 4) throw e;
        tries += 1;
        await sleep(2000 * tries, signal);
      }
    }
    if (last.status >= 400) throw mapError(last.status, last.responseText);
    offset = end;
    if (final) break;
  }
  let data: any = {};
  try { data = JSON.parse(last?.responseText || "{}"); } catch { /* */ }
  const f = data.file || data;
  if (!f?.uri) throw new GeminiError("cloud_error", "upload: no file uri");
  return { name: f.name, uri: f.uri, mimeType: f.mimeType || mime, state: f.state };
}

export async function getFile(name: string, key = getKey()): Promise<GFile | null> {
  try {
    const res = await call(`/v1beta/${name}`, { method: "GET" }, key);
    return await res.json();
  } catch (e) {
    const c = (e as GeminiError).code;
    if (c === "cloud_model_not_found" || c === "cloud_auth_failed") return null;
    throw e;
  }
}

export async function waitActive(f: GFile, signal?: AbortSignal, key = getKey()): Promise<GFile> {
  let cur = f;
  const t0 = Date.now();
  while (cur.state === "PROCESSING") {
    if (Date.now() - t0 > 15 * 60_000) throw new GeminiError("cloud_error", "file processing timeout");
    await sleep(2500, signal);
    const g = await getFile(cur.name, key);
    if (!g) throw new GeminiError("cloud_error", "file disappeared");
    cur = g;
  }
  if (cur.state === "FAILED") throw new GeminiError("unsupported_format", "Google could not process the file");
  return cur;
}

export async function deleteFile(name: string, key = getKey()) {
  try { await call(`/v1beta/${name}`, { method: "DELETE" }, key); } catch { /* 48 soatda o'zi o'chadi */ }
}

export async function blobToBase64(blob: Blob): Promise<string> {
  const buf = new Uint8Array(await blob.arrayBuffer());
  let s = "";
  const CH = 0x8000;
  for (let i = 0; i < buf.length; i += CH) s += String.fromCharCode.apply(null, Array.from(buf.subarray(i, i + CH)));
  return btoa(s);
}
