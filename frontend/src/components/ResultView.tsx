import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "./Layout";
import { Icon } from "./Icons";
import { api, ApiError, Job, Result, Segment, Word } from "../services/api";
import { removeHistory } from "../services/storage";
import { errorText, warningText } from "../i18n";
import { clock, human, nfmt } from "../hooks/format";
import { loadYT } from "../services/youtube";
import SummaryPanel from "./SummaryPanel";

type Tab = "edited" | "segments" | "raw" | "summary";

export type Media = { kind: "audio"; src: string } | { kind: "youtube"; id: string } | { kind: "none" };
export interface ResultBackend {
  save: (text: string) => Promise<void>;
  exportFile: (fmt: string, text: string) => Promise<void>;
  remove: () => Promise<void>;
  media: Media;
  cloud: boolean;
  privacyTitle: string;
  privacySub: string;
  summaryKey: string;
  onContinue?: () => void;
}

/** Server rejimidagi ish uchun standart backend. */
export function serverBackend(job: Job, token: string, t: (k: string, v?: any) => string, retentionH: number, cloudName: string | null): ResultBackend {
  return {
    save: (text) => api.saveEdit(job.job_id, token, text).then(() => undefined),
    exportFile: (fmt) => api.download(job.job_id, token, fmt),
    remove: async () => {
      try { await api.remove(job.job_id, token); } catch (e) { if ((e as ApiError).code !== "not_found") throw e; }
    },
    media: { kind: "audio", src: api.audioUrl(job.job_id, token) },
    cloud: !!cloudName,
    privacyTitle: cloudName ? t("cloudPriv", { n: cloudName }) : t("localPriv"),
    privacySub: t("delIn", { h: retentionH }),
    summaryKey: "srv_" + job.job_id,
  };
}

interface Player { toggle(): void; seek(t: number, play?: boolean): void; rate(r: number): void }
interface Pop { word: Word; x: number; y: number }

function findSegment(segs: Segment[], time: number): number {
  let lo = 0, hi = segs.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (segs[mid].start <= time) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  if (ans >= 0 && time > segs[ans].end + 1.5) return -1;
  return ans;
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    return ok;
  }
}

const SegRow = memo(function SegRow({ seg, active, raw, onSeek, onWord }: {
  seg: Segment; active: boolean; raw: boolean; onSeek: (t: number) => void; onWord: (w: Word, el: HTMLElement) => void;
}) {
  return (
    <div className={`sg${active ? " act" : ""}${seg.para && seg.id > 0 ? " newp" : ""}`} id={`seg-${seg.id}`}>
      <button className="ts" onClick={() => onSeek(seg.start)}>{clock(seg.start)}</button>
      {raw ? <p>{seg.raw}</p> : (
        <p>
          {seg.words.map((w, i) => (
            <React.Fragment key={i}>
              <span className={`w${w.u ? " unc" : w.ai ? " aifx" : w.c ? " fixd" : ""}`} title={w.c ? w.c : undefined} onClick={(e) => onWord(w, e.currentTarget)}>{w.t}</span>{" "}
            </React.Fragment>
          ))}
        </p>
      )}
    </div>
  );
});

const SegList = memo(function SegList({ segs, active, raw, onSeek, onWord }: {
  segs: Segment[]; active: number; raw: boolean; onSeek: (t: number) => void; onWord: (w: Word, el: HTMLElement) => void;
}) {
  return (
    <div className="segs">
      {segs.map((s, i) => <SegRow key={s.id} seg={s} active={i === active} raw={raw} onSeek={onSeek} onWord={onWord} />)}
    </div>
  );
});

export default function ResultView({ job, result, backend }: { job: Job; result: Result; backend: ResultBackend }) {
  const { t, toast, go } = useApp();
  const audio = useRef<HTMLAudioElement>(null);
  const ytBox = useRef<HTMLDivElement>(null);
  const yt = useRef<any>(null);
  const [ytDur, setYtDur] = useState(0);
  const media = backend.media;
  const [tab, setTab] = useState<Tab>("edited");
  const [text, setText] = useState(result.edited_text);
  const [save, setSave] = useState<"saved" | "saving" | "error">("saved");
  const [playing, setPlaying] = useState(false);
  const [cur, setCur] = useState(0);
  const [rate, setRate] = useState(1);
  const [pop, setPop] = useState<Pop | null>(null);
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const [narrow, setNarrow] = useState(() => window.innerWidth < 760);
  const saveTimer = useRef<number | undefined>(undefined);
  const lastSaved = useRef(result.edited_text);
  const dur = result.duration || job.duration || ytDur || 0;
  const segs = result.segments;
  const active = useMemo(() => (playing || cur > 0 ? findSegment(segs, cur) : -1), [segs, cur, playing]);

  useEffect(() => {
    const fn = () => setNarrow(window.innerWidth < 760);
    window.addEventListener("resize", fn);
    return () => window.removeEventListener("resize", fn);
  }, []);

  // Tahrirni avtomatik saqlash (1 soniya kutib)
  useEffect(() => {
    if (text === lastSaved.current) return;
    setSave("saving");
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(async () => {
      try {
        await backend.save(text);
        lastSaved.current = text;
        setSave("saved");
      } catch {
        setSave("error");
      }
    }, 1000);
    return () => window.clearTimeout(saveTimer.current);
  }, [text]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (text !== lastSaved.current) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [text]);

  useEffect(() => {
    if (!playing || active < 0 || tab !== "segments") return;
    document.getElementById(`seg-${segs[active].id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active, playing, tab]);

  useEffect(() => {
    if (!pop && !menu) return;
    const close = () => { setPop(null); setMenu(false); };
    const id = window.setTimeout(() => window.addEventListener("click", close), 0);
    return () => { window.clearTimeout(id); window.removeEventListener("click", close); };
  }, [pop, menu]);

  // YouTube pleeri (IFrame API)
  useEffect(() => {
    if (media.kind !== "youtube" || !ytBox.current) return;
    let alive = true;
    let iv = 0;
    const host = document.createElement("div");
    ytBox.current.appendChild(host);
    loadYT().then((YT) => {
      if (!alive) return;
      yt.current = new YT.Player(host, {
        videoId: media.id, host: "https://www.youtube-nocookie.com", width: "100%", height: "100%",
        playerVars: { playsinline: 1, rel: 0, modestbranding: 1 },
        events: {
          onReady: () => { try { setYtDur(yt.current.getDuration() || 0); } catch { /* */ } },
          onStateChange: (e: any) => {
            const p = e.data === 1;
            setPlaying(p);
            try { const d = yt.current.getDuration(); if (d) setYtDur(d); } catch { /* */ }
          },
        },
      });
      iv = window.setInterval(() => {
        try { const c = yt.current?.getCurrentTime?.(); if (typeof c === "number") setCur(c); } catch { /* */ }
      }, 300);
    }).catch(() => toast(t("ytApiFail")));
    return () => { alive = false; window.clearInterval(iv); try { yt.current?.destroy(); } catch { /* */ } yt.current = null; host.remove(); };
  }, [media.kind === "youtube" ? media.id : ""]);

  const player: Player = useMemo(() => ({
    toggle() {
      if (media.kind === "youtube") {
        const p = yt.current;
        if (!p) return;
        try { p.getPlayerState?.() === 1 ? p.pauseVideo() : p.playVideo(); } catch { /* */ }
        return;
      }
      const a = audio.current;
      if (!a) return;
      if (a.paused) a.play().catch(() => undefined); else a.pause();
    },
    seek(time: number, play = false) {
      const tt = Math.max(0, time - 0.2);
      if (media.kind === "youtube") {
        const p = yt.current;
        if (!p) return;
        try { p.seekTo(tt, true); if (play) p.playVideo(); } catch { /* */ }
        setCur(tt);
        return;
      }
      const a = audio.current;
      if (!a) return;
      a.currentTime = tt;
      setCur(a.currentTime);
      if (play) a.play().catch(() => undefined);
    },
    rate(r: number) {
      if (media.kind === "youtube") { try { yt.current?.setPlaybackRate(r); } catch { /* */ } return; }
      if (audio.current) audio.current.playbackRate = r;
    },
  }), [media.kind]);

  const seek = useCallback((time: number, play = false) => player.seek(time, play), [player]);
  const seekPlay = useCallback((x: number) => seek(x, true), [seek]);
  const onWord = useCallback((w: Word, el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    setPop({ word: w, x: Math.min(window.innerWidth - 316, Math.max(8, r.left)), y: r.bottom + 8 });
  }, []);

  const toggle = () => player.toggle();
  function cycleRate() {
    const rates = [1, 1.25, 1.5, 2, 0.75];
    const n = rates[(rates.indexOf(rate) + 1) % rates.length];
    setRate(n);
    player.rate(n);
  }

  const bars = useMemo(() => {
    const src = result.waveform || [];
    const n = narrow ? 56 : 140;
    if (!src.length) return Array.from({ length: n }, () => 0.15);
    const out: number[] = [];
    for (let i = 0; i < n; i++) {
      const a = Math.floor((i * src.length) / n), b = Math.max(a + 1, Math.floor(((i + 1) * src.length) / n));
      let m = 0;
      for (let k = a; k < b && k < src.length; k++) m = Math.max(m, src[k]);
      out.push(Math.max(0.1, m));
    }
    return out;
  }, [result.waveform, narrow]);
  const played = dur ? cur / dur : 0;

  async function doCopy() {
    const ok = await copyText(tab === "raw" ? result.raw_text : text);
    toast(ok ? t("copied") : "✕");
  }
  async function doExport(fmt: string) {
    setMenu(false);
    try { await backend.exportFile(fmt, text); } catch (e) { toast(errorText(t, (e as ApiError).code || "internal_error")); }
  }
  async function doDelete() {
    if (!window.confirm(t("delQ"))) return;
    setBusy(true);
    try { await backend.remove(); } catch (e) { setBusy(false); toast(errorText(t, (e as ApiError).code || "internal_error")); return; }
    removeHistory(job.job_id);
    go("/");
  }

  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const uncertainList = useMemo(() => {
    const list: Word[] = [];
    for (const s of segs) for (const w of s.words) { if (w.u) list.push(w); if (list.length >= 60) return list; }
    return list;
  }, [segs]);
  const cloud = backend.cloud;
  const timed = useMemo(() => segs.map((s) => `[${clock(s.start)}] ${s.text}`).join("\n"), [segs]);
  const incomplete = !!backend.onContinue && (result.warnings.includes("cloud_incomplete") ||
    (ytDur > 0 && segs.length > 0 && segs[segs.length - 1].end < ytDur - 90));
  const langLabel = result.options.language === "auto"
    ? `${result.detected_language ? t("l_" + result.detected_language) : "?"} · ${t("detected")}${result.language_probability ? ` ${Math.round(result.language_probability * 100)}%` : ""}`
    : `${t("l_" + result.options.language)} · ${t("manual")}`;

  const exportMenu = (
    <div className="menu" onClick={(e) => e.stopPropagation()}>
      {["txt", "txt_ts", "srt", "vtt", "json"].map((f) => (
        <button key={f} onClick={() => doExport(f)}>{t("ex_" + f)}<small>.{f === "txt_ts" ? "txt" : f}</small></button>
      ))}
    </div>
  );

  return (
    <div className="wrap">
      {media.kind === "audio" && (
        <audio ref={audio} src={media.src} preload="metadata"
          onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)}
          onTimeUpdate={(e) => setCur(e.currentTarget.currentTime)} />
      )}

      <div className="row sp gap12 wrapf" style={{ marginBottom: 18 }}>
        <div className="row gap12" style={{ minWidth: 0, flex: 1 }}>
          <button className="icon-btn" onClick={() => go("/")} aria-label={t("back")}><Icon name="chevl" /></button>
          <div style={{ minWidth: 0 }}>
            <div className="fname" style={{ fontSize: narrow ? 17 : 22, fontWeight: 750 }}>{job.filename}</div>
            <div className="row gap6 wrapf" style={{ marginTop: 5 }}>
              <span className="badge b-ok"><span className="dot" />{t("st_completed")}</span>
              <span className="chip">{t("l_" + result.language) !== "l_" + result.language ? t("l_" + result.language) : result.language}</span>
              <span className="chip">{t("s_" + result.options.script)}</span>
              <span className="chip desk-only">{t("m_" + result.options.mode)}</span>
            </div>
          </div>
        </div>
        <div className="row gap8 res-actions">
          <button className="btn btn-ghost desk-only" onClick={doCopy}><Icon name="copy" sm /><span className="lbl">{t("copy")}</span></button>
          <div style={{ position: "relative" }}>
            <button className="btn btn-ghost" onClick={(e) => { e.stopPropagation(); setMenu(!menu); }} aria-expanded={menu}>
              <span className="lbl">{t("more")}</span>{narrow ? <Icon name="more" /> : <Icon name="chev" sm />}
            </button>
            {menu && exportMenu}
          </div>
          <button className="btn btn-primary desk-only" onClick={() => doExport("txt")}><Icon name="download" sm />{t("dl")}</button>
        </div>
      </div>

      <div className="res-grid">
        <div style={{ minWidth: 0 }}>
          {media.kind === "youtube" && (
            <div className="card yt-card"><div className="yt-box" ref={ytBox} /></div>
          )}
          {incomplete && (
            <div className="note warn" style={{ marginBottom: 14 }}>
              <Icon name="info" sm /><span className="grow">{t("w_cloud_incomplete")}</span>
              <button className="btn btn-primary" style={{ minHeight: 34 }} onClick={backend.onContinue}><Icon name="refresh" sm />{t("continueJob")}</button>
            </div>
          )}
          {media.kind !== "none" && <div className="card" style={{ padding: narrow ? "14px" : "16px 20px" }}>
            <div className="row gap12">
              {!narrow && <button className="icon-btn" style={{ border: 0 }} onClick={() => seek(cur - 10)} aria-label="-10s"><Icon name="back10" /></button>}
              <button className="play" onClick={toggle} aria-label={playing ? "pause" : "play"}><Icon name={playing ? "pause" : "play"} /></button>
              {!narrow && <button className="icon-btn" style={{ border: 0 }} onClick={() => seek(cur + 10)} aria-label="+10s"><Icon name="fwd10" /></button>}
              <div className="wave" onClick={(e) => {
                const r = e.currentTarget.getBoundingClientRect();
                seek(((e.clientX - r.left) / r.width) * dur);
              }}>
                {bars.map((v, i) => <i key={i} className={i / bars.length < played ? "p" : ""} style={{ height: `${Math.round(v * 100)}%` }} />)}
              </div>
              {!narrow && <span style={{ fontVariantNumeric: "tabular-nums", fontSize: 14, fontWeight: 600, whiteSpace: "nowrap" }}>{clock(cur)} <span className="faint">/ {clock(dur)}</span></span>}
              {!narrow && <button className="chip" onClick={cycleRate}>{rate}×</button>}
            </div>
            {narrow && (
              <div className="row sp" style={{ fontSize: 12.5, fontWeight: 600, marginTop: 8, fontVariantNumeric: "tabular-nums" }}>
                <span>{clock(cur)}</span><button className="chip" onClick={cycleRate}>{rate}×</button><span className="faint">{clock(dur)}</span>
              </div>
            )}
          </div>}

          <div className="card" style={{ marginTop: media.kind !== "none" ? 16 : 0, padding: narrow ? "4px 12px 14px" : "6px 22px 18px" }}>
            <div className="tabs" role="tablist">
              {(["edited", "segments", "raw", "summary"] as Tab[]).map((k) => (
                <button key={k} role="tab" aria-selected={tab === k} className={(tab === k ? "on" : "") + (k === "summary" ? " tab-ai" : "")} onClick={() => setTab(k)}>
                  {k === "edited" && <Icon name="pen" sm />}{k === "summary" && <Icon name="sparkle" sm />}
                  {t(k === "edited" ? "t_edited" : k === "segments" ? "t_latin" : k === "raw" ? "t_raw" : "anTab")}
                </button>
              ))}
            </div>
            {tab !== "summary" && <div className="row gap16 wrapf" style={{ fontSize: 12.5, margin: "12px 0 8px" }}>
              {tab === "segments" && <span className="row gap6 muted"><span className="unc" style={{ fontSize: 12 }}>abc</span>{t("legend")}</span>}
              {tab === "segments" && (result.stats.corrected || 0) > 0 && <span className="row gap6 muted"><span className="fixd" style={{ fontSize: 12 }}>abc</span>{t("fixedLegend")}</span>}
              {tab === "segments" && (result.stats.ai_changed || 0) > 0 && <span className="row gap6 muted"><span className="aifx" style={{ fontSize: 12 }}>abc</span>{t("aiLegend")}</span>}
              {tab === "edited" && <span className="muted">{nfmt(words)} {t("words")} · {nfmt(text.length)} {t("chars")}</span>}
              {tab === "edited" && (
                <span className="row gap6" style={{ marginLeft: "auto", fontWeight: 600, color: save === "error" ? "var(--danger)" : save === "saving" ? "var(--muted)" : "var(--success)" }}>
                  {save === "saving" ? <span className="spin sm" /> : <Icon name={save === "error" ? "alert" : "check"} sm />}
                  {t(save === "saving" ? "saving" : save === "error" ? "saveErr" : "saved")}
                </span>
              )}
            </div>}
            {tab === "summary" && <SummaryPanel summaryKey={backend.summaryKey} transcript={timed} title={job.filename} onSeek={(x) => seek(x, true)} />}
            {tab === "edited" && (
              <textarea className="editor" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} aria-label={t("t_edited")} />
            )}
            {tab === "segments" && (segs.length ? <SegList segs={segs} active={active} raw={false} onSeek={seekPlay} onWord={onWord} /> :
              <p className="faint" style={{ padding: 16 }}>{warningText(t, "no_speech_found")}</p>)}
            {tab === "raw" && <SegList segs={segs} active={active} raw onSeek={seekPlay} onWord={onWord} />}
          </div>
        </div>

        <aside className="side">
          {result.warnings.filter((w) => w !== "cloud_incomplete").map((w) => <div key={w} className="note warn"><Icon name="info" sm /><span>{warningText(t, w)}</span></div>)}
          {tab !== "summary" && (
            <button className="card an-cta" onClick={() => { setTab("summary"); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
              <span className="ficon"><Icon name="sparkle" /></span>
              <span className="grow"><b>{t("anT")}</b><small>{t("anCta")}</small></span>
              <Icon name="chevr" sm />
            </button>
          )}
          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ marginBottom: 8 }}>{t("summary")}</h2>
            {([["k_lang", langLabel], ["k_dur", clock(dur)], ["k_words", nfmt(result.stats.words)],
              ["k_unc", nfmt(result.stats.uncertain)],
              ...((result.stats.corrected || 0) > 0 ? [["k_fixed", nfmt(result.stats.corrected || 0)]] : []),
              ...(result.cloud_usage ? [["k_cost", t("costInfo", { c: result.cloud_usage.cost_usd.toFixed(3), i: nfmt(result.cloud_usage.input_tokens), o: nfmt(result.cloud_usage.output_tokens) })]] : []),
              ...(result.proofread ? [["k_ai", t("aiStat", { m: result.proofread.model, n: nfmt(result.proofread.changed_words) })]] : []),
              ["k_model", result.model], ["k_time", human(result.processing_seconds, t)]] as [string, string][]).map(([k, v]) => (
              <div className="kv" key={k}><span>{t(k)}</span><b>{v}</b></div>
            ))}
          </div>
          <div className="card" style={{ padding: 20 }}>
            <div className="row sp" style={{ marginBottom: 6 }}><h2>{t("check")}</h2><span className="badge b-acc">{result.stats.uncertain}</span></div>
            {uncertainList.length === 0 ? <p className="faint" style={{ fontSize: 14, paddingTop: 6 }}>{t("checkNone")}</p> :
              uncertainList.slice(0, 12).map((w, i) => (
                <button key={i} className="jump" onClick={() => { setTab("segments"); seek(w.s, true); }}>
                  <span className="ts2">{clock(w.s)}</span><span className="grow" style={{ fontWeight: 500 }}>{w.t}</span><Icon name="chevr" sm />
                </button>
              ))}
          </div>
          <div className="card" style={{ padding: 20 }}>
            <div className="row gap10" style={{ marginBottom: 14 }}>
              <div className="ficon" style={{ background: cloud ? "var(--accent-soft)" : "var(--success-soft)", color: cloud ? "var(--accent-text)" : "var(--success)", width: 40, height: 40 }}>
                <Icon name={cloud ? "cloud" : "shield"} />
              </div>
              <div style={{ fontSize: 13.5 }}>
                <b style={{ display: "block", fontSize: 14.5 }}>{backend.privacyTitle}</b>
                <span className="muted">{backend.privacySub}</span>
              </div>
            </div>
            <button className="btn btn-danger btn-block" onClick={doDelete} disabled={busy}><Icon name="trash" sm />{t("del")}</button>
          </div>
        </aside>
      </div>

      <div className="mobile-cta">
        <div className="row gap10">
          <button className="btn btn-ghost grow" style={{ minHeight: 52 }} onClick={doCopy}><Icon name="copy" sm />{t("copy")}</button>
          <button className="btn btn-primary" style={{ flex: 1.5, minHeight: 52 }} onClick={() => doExport("txt")}><Icon name="download" sm />{t("dl")}</button>
        </div>
      </div>

      {pop && (
        <div className="pop" style={{ left: pop.x, top: pop.y }} onClick={(e) => e.stopPropagation()}>
          <div className="row sp" style={{ marginBottom: 10 }}>
            <span className="row gap6" style={{ fontWeight: 700, fontSize: 14, color: pop.word.u ? "var(--accent-text)" : "var(--text)" }}>
              {pop.word.u && <Icon name="alert" sm />}{pop.word.u ? t("popT") : pop.word.t}
            </span>
            {pop.word.p != null && <span className={`badge ${pop.word.u ? "b-acc" : "b-ok"}`}>{Math.round(pop.word.p * 100)}% {t("conf")}</span>}
          </div>
          <div style={{ fontSize: 17, fontWeight: 650, marginBottom: 6 }}>«{pop.word.t}»</div>
          {pop.word.c && <div className="muted" style={{ fontSize: 13, marginBottom: 6 }}>{t("origWas")} <s>{pop.word.c}</s></div>}
          <div className="faint" style={{ fontSize: 12.5, marginBottom: 12 }}>{clock(pop.word.s)} · {t("editHint")}</div>
          <button className="btn btn-primary btn-block" style={{ minHeight: 38, fontSize: 14 }} onClick={() => { seek(pop.word.s, true); setPop(null); }}>
            <Icon name="play" sm />{t("playHere")}
          </button>
        </div>
      )}
    </div>
  );
}
