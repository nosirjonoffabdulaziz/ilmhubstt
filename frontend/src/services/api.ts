// Backend API bilan aloqa. Barcha so'rovlar shu domen orqali (/api/v1).
const BASE = "/api/v1";
const KEY_STORAGE = "ilmhubstt.accessKey";

export class ApiError extends Error {
  code: string;
  status: number;
  extra: Record<string, any>;
  constructor(code: string, status = 0, extra: Record<string, any> = {}) {
    super(code);
    this.code = code;
    this.status = status;
    this.extra = extra;
  }
}

export function getAccessKey(): string {
  try { return localStorage.getItem(KEY_STORAGE) || ""; } catch { return ""; }
}
export function setAccessKey(k: string) {
  try { k ? localStorage.setItem(KEY_STORAGE, k) : localStorage.removeItem(KEY_STORAGE); } catch { /* */ }
}

function headers(token?: string, json = false): Record<string, string> {
  const h: Record<string, string> = {};
  const key = getAccessKey();
  if (key) h["x-access-key"] = key;
  if (token) h["x-job-token"] = token;
  if (json) h["content-type"] = "application/json";
  return h;
}

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, opts);
  } catch {
    throw new ApiError("network");
  }
  let data: any = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    try { data = await res.json(); } catch { data = null; }
  }
  if (!res.ok) {
    const { error, ...extra } = data || {};
    throw new ApiError(error || (res.status >= 500 ? "internal_error" : "network"), res.status, extra);
  }
  return data as T;
}

export interface EngineInfo { id: string; available: boolean; reason: string; cloud: boolean; chunked: boolean; models?: Record<string, string>; language_models?: Record<string, string>; model?: string; key_set?: boolean; key_hint?: string }
export interface Config {
  version: string; languages: string[]; qualities: string[]; default_quality: string;
  engines: EngineInfo[]; default_engine: string; max_upload_mb: number; max_duration_min: number;
  retention_hours: number; requires_access_key: boolean; export_formats: string[];
  ffmpeg: { ffmpeg: boolean; ffprobe: boolean }; transliteration_profiles: Record<string, string>;
  proofreader?: { available: boolean; model: string; reason: string; default_on: boolean };
}
export interface JobOptions {
  language: string; script: string; mode: string; punctuation: boolean; paragraphs: boolean; spellfix?: boolean; ai_proofread?: boolean;
  quality: string; engine: string; vocabulary: string;
}
export interface Job {
  job_id: string; status: string; stage: string; progress: number; error: string | null; filename: string;
  size_bytes: number; duration: number; options: JobOptions; created_at: number; started_at: number | null;
  finished_at: number | null; processed_seconds: number; eta_seconds: number | null; queue_position: number | null;
  language: string | null; warnings: string[]; preview: { t: number; x: string }[];
  detail: { wait?: number; attempt?: number; done?: number; total?: number; model?: string; done_mb?: number; total_mb?: number | null; speed_mbs?: number; eta?: number | null; device?: string };
}
export interface Word { t: string; s: number; e: number; p: number | null; u: boolean; c?: string; ai?: boolean }
export interface Segment { id: number; start: number; end: number; raw: string; text: string; para: boolean; low: boolean; words: Word[] }
export interface Result {
  job_id: string; filename: string; language: string; detected_language: string | null; language_probability: number | null;
  raw_text: string; latin_text: string; edited_text: string; segments: Segment[];
  stats: { words: number; uncertain: number; segments: number; paragraphs: number; low_segments: number; corrected?: number; ai_changed?: number };
  warnings: string[]; duration: number; options: JobOptions; model: string; processing_seconds: number; waveform: number[];
  proofread?: { model: string; chunks: number; accepted: number; rejected: number; changed_words: number };
  cloud_usage?: { model?: string; input_tokens: number; output_tokens: number; cost_usd: number };
}

export const api = {
  config: () => request<Config>("/config"),
  health: () => request<any>("/health"),
  job: (id: string, token: string) => request<Job>(`/jobs/${id}`, { headers: headers(token) }),
  result: (id: string, token: string) => request<Result>(`/jobs/${id}/result`, { headers: headers(token) }),
  saveEdit: (id: string, token: string, text: string) =>
    request<{ ok: boolean }>(`/jobs/${id}/result`, { method: "PATCH", headers: headers(token, true), body: JSON.stringify({ edited_text: text }) }),
  cancel: (id: string, token: string) => request<any>(`/jobs/${id}/cancel`, { method: "POST", headers: headers(token) }),
  remove: (id: string, token: string) => request<any>(`/jobs/${id}`, { method: "DELETE", headers: headers(token) }),
  geminiStatus: () => request<{ key_set: boolean; key_hint: string; model: string; available: boolean }>("/settings/gemini", { headers: headers() }),
  geminiSave: (api_key: string) => request<{ key_set: boolean; key_hint: string; model: string; available: boolean; models?: string[] }>(
    "/settings/gemini", { method: "POST", headers: headers(undefined, true), body: JSON.stringify({ api_key }) }),
  geminiDelete: () => request<any>("/settings/gemini", { method: "DELETE", headers: headers() }),
  audioUrl: (id: string, token: string) => {
    const q = new URLSearchParams({ token });
    const key = getAccessKey();
    if (key) q.set("key", key);
    return `${BASE}/jobs/${id}/audio?${q.toString()}`;
  },
  async download(id: string, token: string, format: string): Promise<void> {
    let res: Response;
    try {
      res = await fetch(`${BASE}/jobs/${id}/export?format=${encodeURIComponent(format)}`, { headers: headers(token) });
    } catch { throw new ApiError("network"); }
    if (!res.ok) {
      let code = "internal_error";
      try { code = (await res.json()).error || code; } catch { /* */ }
      throw new ApiError(code, res.status);
    }
    const blob = await res.blob();
    const cd = res.headers.get("content-disposition") || "";
    const m = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    const name = m ? decodeURIComponent(m[1]) : `ilmhubstt.${format === "txt_ts" ? "txt" : format}`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  },
  upload(file: File, options: Partial<JobOptions>, onProgress: (p: number) => void):
    { promise: Promise<{ job_id: string; token: string; duration: number }>; abort: () => void } {
    const xhr = new XMLHttpRequest();
    const promise = new Promise<{ job_id: string; token: string; duration: number }>((resolve, reject) => {
      const fd = new FormData();
      fd.append("file", file, file.name);
      for (const [k, v] of Object.entries(options)) fd.append(k, String(v));
      xhr.open("POST", BASE + "/jobs");
      const key = getAccessKey();
      if (key) xhr.setRequestHeader("x-access-key", key);
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100)); };
      xhr.onload = () => {
        let data: any = null;
        try { data = JSON.parse(xhr.responseText); } catch { /* */ }
        if (xhr.status === 201 && data) resolve(data);
        else {
          const { error, ...extra } = data || {};
          reject(new ApiError(error || (xhr.status === 413 ? "file_too_large" : xhr.status >= 500 ? "internal_error" : "network"), xhr.status, extra));
        }
      };
      xhr.onerror = () => reject(new ApiError("network"));
      xhr.onabort = () => reject(new ApiError("aborted"));
      xhr.send(fd);
    });
    return { promise, abort: () => xhr.abort() };
  },
};
