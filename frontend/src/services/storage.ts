// Brauzer xotirasi: ishlar tarixi (job_id + token) va foydalanuvchi sozlamalari.
import type { Lang } from "../i18n";

export interface HistoryItem {
  id: string; token: string; filename: string; created: number; duration: number;
  language: string; status: string; progress?: number;
  kind?: "cloud"; source?: "youtube" | "file" | "url";
}
export interface Prefs {
  lang: Lang; theme: "light" | "dark" | "system";
  language: string; script: string; mode: string; quality: string; punctuation: boolean; paragraphs: boolean; spellfix: boolean; aiProofread?: boolean; engine?: string; summaryLang?: string; srcTab?: "file" | "link"; autoSummary?: boolean;
}

const H_KEY = "ilmhubstt.history";
const P_KEY = "ilmhubstt.prefs";

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
  } catch { return fallback; }
}
function write(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ }
}

function detectLang(): Lang {
  const n = (navigator.language || "uz").toLowerCase();
  if (n.startsWith("ru")) return "ru";
  if (n.startsWith("en")) return "en";
  return "uz";
}

export const DEFAULT_PREFS: Prefs = {
  lang: "uz", theme: "system", language: "uz", script: "latin", mode: "clean", quality: "balanced",
  punctuation: true, paragraphs: true, spellfix: true,
};

export function loadPrefs(): Prefs {
  let stored: string | null = null;
  try { stored = localStorage.getItem(P_KEY); } catch { /* */ }
  const base = { ...DEFAULT_PREFS, lang: detectLang() };
  return stored ? read(P_KEY, base) : base;
}
export const savePrefs = (p: Prefs) => write(P_KEY, p);

export function loadHistory(): HistoryItem[] {
  try {
    const raw = localStorage.getItem(H_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list : [];
  } catch { return []; }
}
export const saveHistory = (list: HistoryItem[]) => write(H_KEY, list.slice(0, 100));

export function upsertHistory(item: Partial<HistoryItem> & { id: string }): HistoryItem[] {
  const list = loadHistory();
  const i = list.findIndex((x) => x.id === item.id);
  if (i >= 0) list[i] = { ...list[i], ...item };
  else list.unshift(item as HistoryItem);
  saveHistory(list);
  return list;
}
export function removeHistory(id: string): HistoryItem[] {
  const list = loadHistory().filter((x) => x.id !== id);
  saveHistory(list);
  return list;
}
export const findHistory = (id: string) => loadHistory().find((x) => x.id === id);
