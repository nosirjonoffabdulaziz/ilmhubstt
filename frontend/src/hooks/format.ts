import type { T } from "../i18n";

export function clock(sec: number): string {
  const s = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(r).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function human(sec: number, t: T): string {
  const s = Math.max(0, Math.round(sec || 0));
  if (s < 60) return `${s} ${t("sec")}`;
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  if (h > 0) return `${h} ${t("hr")} ${m} ${t("min")}`;
  return `${m} ${t("min")}`;
}

export function mb(bytes: number): string {
  if (!bytes) return "0 MB";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function isVideo(name: string, type?: string): boolean {
  return (type || "").startsWith("video/") || /\.(mp4|mov|webm|mkv|avi|m4v|3gp)$/i.test(name);
}

export function nfmt(n: number): string {
  return n.toLocaleString("ru-RU").replace(/,/g, " ");
}
