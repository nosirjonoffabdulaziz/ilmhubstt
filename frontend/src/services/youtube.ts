// YouTube havolalarini aniqlash va IFrame Player API (davomiylik, video ijro, vaqtga o'tish).

export function youtubeId(raw: string): string | null {
  const s = raw.trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(s)) return null; // faqat ID — havola emas
  let u: URL;
  try { u = new URL(/^https?:\/\//i.test(s) ? s : "https://" + s); } catch { return null; }
  const host = u.hostname.replace(/^www\.|^m\.|^music\./, "").toLowerCase();
  let id: string | null = null;
  if (host === "youtu.be") id = u.pathname.split("/")[1] || null;
  else if (host === "youtube.com" || host === "youtube-nocookie.com") {
    if (u.pathname === "/watch") id = u.searchParams.get("v");
    else {
      const m = /^\/(shorts|live|embed|v)\/([^/?#]+)/.exec(u.pathname);
      if (m) id = m[2];
    }
  }
  return id && /^[A-Za-z0-9_-]{11}$/.test(id) ? id : null;
}

export const youtubeUrl = (id: string) => `https://www.youtube.com/watch?v=${id}`;
export const youtubeThumb = (id: string) => `https://i.ytimg.com/vi/${id}/mqdefault.jpg`;

/** Video nomi (oEmbed). Ishlamasa null. */
export async function youtubeTitle(id: string): Promise<string | null> {
  try {
    const ctrl = new AbortController();
    const tm = window.setTimeout(() => ctrl.abort(), 6000);
    const r = await fetch(`https://www.youtube.com/oembed?format=json&url=${encodeURIComponent(youtubeUrl(id))}`, { signal: ctrl.signal });
    window.clearTimeout(tm);
    if (!r.ok) return null;
    const j = await r.json();
    return typeof j.title === "string" ? j.title.slice(0, 200) : null;
  } catch { return null; }
}

// ---------------- IFrame API ----------------
declare global {
  interface Window { YT?: any; onYouTubeIframeAPIReady?: () => void }
}
let apiP: Promise<any> | null = null;

export function loadYT(): Promise<any> {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (apiP) return apiP;
  apiP = new Promise((resolve, reject) => {
    const prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => { prev?.(); resolve(window.YT); };
    const s = document.createElement("script");
    s.src = "https://www.youtube.com/iframe_api";
    s.async = true;
    s.onerror = () => { apiP = null; reject(new Error("yt api")); };
    document.head.appendChild(s);
    window.setTimeout(() => { if (!window.YT?.Player) { apiP = null; reject(new Error("yt timeout")); } }, 15000);
  });
  return apiP;
}

/** Yashirin pleer orqali video davomiyligini olish (soniya). Topilmasa null. */
export async function youtubeDuration(id: string, timeoutMs = 10000): Promise<number | null> {
  try {
    const YT = await loadYT();
    return await new Promise<number | null>((resolve) => {
      const host = document.createElement("div");
      host.style.cssText = "position:fixed;left:-9999px;top:0;width:200px;height:120px;opacity:0;pointer-events:none";
      const inner = document.createElement("div");
      host.appendChild(inner);
      document.body.appendChild(host);
      let done = false;
      let player: any = null;
      const finish = (v: number | null) => {
        if (done) return;
        done = true;
        window.clearInterval(iv);
        try { player?.destroy(); } catch { /* */ }
        host.remove();
        resolve(v);
      };
      const check = () => {
        try {
          const d = player?.getDuration?.();
          if (d && d > 0) finish(d);
        } catch { /* */ }
      };
      const iv = window.setInterval(check, 400);
      window.setTimeout(() => finish(null), timeoutMs);
      player = new YT.Player(inner, {
        videoId: id, host: "https://www.youtube-nocookie.com",
        playerVars: { controls: 0, mute: 1, playsinline: 1 },
        events: { onReady: check, onError: () => finish(null) },
      });
    });
  } catch { return null; }
}
