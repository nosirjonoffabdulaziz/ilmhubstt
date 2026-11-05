import React, { useEffect, useRef, useState } from "react";
import { useApp, StatusBadge } from "../components/Layout";
import { Icon } from "../components/Icons";
import { api, ApiError } from "../services/api";
import { HistoryItem, loadHistory, upsertHistory } from "../services/storage";
import { errorText } from "../i18n";
import { clock, isVideo, mb } from "../hooks/format";
import KeyBox from "../components/KeyBox";
import { createCloudJob, FILE_MAX, guessMime } from "../services/cloud";
import { getKey } from "../services/gemini";
import { youtubeDuration, youtubeId, youtubeThumb, youtubeTitle } from "../services/youtube";

const CLOUD_BAD = /\.(amr|wma|ape|ac3|dts|ra|rm)$/i;
interface LinkInfo { raw: string; kind: "youtube" | "url" | "bad"; id?: string; title?: string | null; dur?: number | null; loading?: boolean }

export function historyPath(h: HistoryItem): string {
  return h.kind === "cloud" ? `/c/${h.id}` : `/job/${h.id}`;
}
export function historyIcon(h: HistoryItem): string {
  return h.source === "youtube" ? "youtube" : h.source === "url" ? "link" : isVideo(h.filename) ? "video" : "music";
}

function linkName(u: string): string {
  try {
    const x = new URL(u);
    const last = decodeURIComponent(x.pathname.split("/").filter(Boolean).pop() || "");
    return (last || x.hostname).slice(0, 120);
  } catch { return u.slice(0, 120); }
}

const ACCEPT = "audio/*,video/*,.mp3,.wav,.m4a,.ogg,.opus,.flac,.aac,.mp4,.mov,.webm,.mkv,.amr,.wma,.3gp";
const ACTIVE = ["queued", "converting", "transcribing", "normalizing"];

function probeDuration(file: File): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const el = document.createElement(isVideo(file.name, file.type) ? "video" : "audio");
    let done = false;
    const finish = (v: number | null) => {
      if (done) return;
      done = true;
      URL.revokeObjectURL(url);
      resolve(v);
    };
    el.preload = "metadata";
    el.onloadedmetadata = () => finish(Number.isFinite(el.duration) && el.duration > 0 ? el.duration : null);
    el.onerror = () => finish(null);
    window.setTimeout(() => finish(null), 8000);
    el.src = url;
  });
}

export default function HomePage() {
  const { t, prefs, setPrefs, config, go, askKey } = useApp();
  const [file, setFile] = useState<File | null>(null);
  const [dur, setDur] = useState<number | null>(null);
  const [checking, setChecking] = useState(false);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [vocab, setVocab] = useState("");
  const engine = prefs.engine || "";
  const setEngine = (e: string) => setPrefs({ engine: e });
  const [upload, setUpload] = useState<{ p: number; abort: () => void } | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>(loadHistory);
  const inputRef = useRef<HTMLInputElement>(null);
  const tab = __STATIC__ ? (prefs.srcTab || "link") : (prefs.srcTab || "file");
  const cloudMode = __STATIC__ || tab === "link";
  const [link, setLink] = useState("");
  const [info, setInfo] = useState<LinkInfo | null>(null);
  const [hasKey, setHasKey] = useState(!!getKey());
  const [starting, setStarting] = useState(false);
  const autoSum = prefs.autoSummary !== false;
  const sumLang = prefs.summaryLang || prefs.lang;

  // havolani tahlil qilish: YouTube bo'lsa nomi va davomiyligini olish
  useEffect(() => {
    const raw = link.trim();
    if (!raw) { setInfo(null); return; }
    const id = youtubeId(raw);
    if (id) {
      const base: LinkInfo = { raw, kind: "youtube", id, loading: true };
      setInfo(base);
      let alive = true;
      const tm = window.setTimeout(async () => {
        // davomiylik alohida keladi (YouTube pleeri sekin yuklansa ham tugma bloklanmasin)
        youtubeDuration(id).then((dur) => { if (alive && dur) setInfo((o) => (o && o.id === id ? { ...o, dur } : o)); });
        const title = await youtubeTitle(id);
        if (alive) setInfo((o) => (o && o.id === id ? { ...o, title, loading: false } : o));
      }, 350);
      return () => { alive = false; window.clearTimeout(tm); };
    }
    if (/^https?:\/\/[^\s/]+\.[^\s]+$/i.test(raw)) setInfo({ raw, kind: "url" });
    else setInfo({ raw, kind: "bad" });
  }, [link]);

  const maxMb = config?.max_upload_mb ?? 1024;
  const maxMin = config?.max_duration_min ?? 180;
  const engines = (config?.engines || []).filter((e) => e.available);
  const curEngine = (engine && engines.some((e) => e.id === engine)) ? engine : (config?.default_engine || "faster-whisper");
  const engineInfo = engines.find((e) => e.id === curEngine);
  const pr = config?.proofreader;
  const aiAvail = !!pr?.available;
  const aiWanted = prefs.aiProofread ?? (pr?.default_on ?? true);

  // So'nggi ishlar holatini yangilab turish
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      const list = loadHistory().slice(0, 5);
      for (const h of list.filter((x) => ACTIVE.includes(x.status) && x.kind !== "cloud")) {
        try {
          const j = await api.job(h.id, h.token);
          upsertHistory({ id: h.id, status: j.status, progress: j.progress });
        } catch (e) {
          if ((e as ApiError).code === "not_found") upsertHistory({ id: h.id, status: "expired" });
        }
      }
      if (!stop) setHistory(loadHistory());
    };
    tick();
    const iv = window.setInterval(tick, 3000);
    return () => { stop = true; window.clearInterval(iv); };
  }, []);

  async function pick(f: File | null | undefined) {
    if (!f) return;
    setError(null);
    setFile(f);
    setDur(null);
    if (__STATIC__) {
      if (f.size > FILE_MAX) { setError(errorText(t, "file_too_large", { mb: 2048 })); return; }
      if (CLOUD_BAD.test(f.name)) { setError(t("e_unsupported_cloud")); return; }
    } else if (f.size > maxMb * 1024 * 1024) {
      setError(errorText(t, "file_too_large", { mb: maxMb }));
      return;
    }
    setChecking(true);
    const d = await probeDuration(f);
    setChecking(false);
    setDur(d);
    if (!__STATIC__ && d && d > maxMin * 60 + 1) setError(errorText(t, "too_long", { min: maxMin }));
  }

  async function startCloud() {
    if (starting) return;
    if (!getKey()) { setHasKey(false); setError(t("e_gemini_key_missing")); return; }
    const opts = { language: prefs.language, mode: prefs.mode, script: prefs.language === "uz" || prefs.language === "auto" ? "latin" : prefs.script,
      vocabulary: vocab.trim(), summaryLang: autoSum ? sumLang : "" };
    setStarting(true);
    setError(null);
    try {
      let id: string;
      if (tab === "link" || !file) {
        if (!info || info.kind === "bad") { setError(t("e_link_bad")); return; }
        if (info.kind === "youtube") {
          id = await createCloudJob({ type: "youtube", videoId: info.id, url: info.raw, name: info.title || `YouTube · ${info.id}` }, opts, { duration: info.dur });
        } else {
          id = await createCloudJob({ type: "url", url: info.raw, name: linkName(info.raw), mime: guessMime(info.raw) }, opts, {});
        }
      } else {
        id = await createCloudJob({ type: "file", name: file.name, mime: guessMime(file.name, file.type), size: file.size }, opts, { blob: file, duration: dur });
      }
      go(`/c/${id}`);
    } catch (e) {
      setError(errorText(t, (e as any)?.code || "internal_error"));
    } finally {
      setStarting(false);
    }
  }

  function start() {
    if (cloudMode) { startCloud(); return; }
    if (!file || upload) return;
    setError(null);
    const opts = {
      language: prefs.language, script: prefs.script, mode: prefs.mode, punctuation: prefs.punctuation,
      paragraphs: prefs.paragraphs, quality: prefs.quality, engine: curEngine, vocabulary: vocab.trim(),
      spellfix: prefs.spellfix !== false,
      ai_proofread: aiAvail && aiWanted && !engineInfo?.cloud,
    };
    const u = api.upload(file, opts, (p) => setUpload((old) => (old ? { ...old, p } : old)));
    setUpload({ p: 0, abort: u.abort });
    u.promise.then((r) => {
      upsertHistory({ id: r.job_id, token: r.token, filename: file.name, created: Date.now(), duration: r.duration,
        language: prefs.language, status: "queued", progress: 0 });
      setUpload(null);
      go(`/job/${r.job_id}`);
    }).catch((e: ApiError) => {
      setUpload(null);
      if (e.code === "aborted") return;
      if (e.code === "access_key_required") askKey();
      setError(errorText(t, e.code, e.extra));
    });
  }

  const canStart = cloudMode
    ? !starting && (tab === "link" ? !!info && info.kind !== "bad" && !info.loading : !!file && !checking && !error)
    : !!file && !checking && !error && !upload && !!config && engines.length > 0;
  const langs: [string, string][] = [["uz", "UZ"], ["ky", "KY"], ["kk", "KK"], ["auto", "AUTO"]];

  const cta = (
    <>
      {upload ? (
        <div className="row gap8">
          <div className="btn btn-primary btn-lg grow" style={{ position: "relative", overflow: "hidden" }}>
            <span style={{ position: "absolute", inset: 0, width: `${upload.p}%`, background: "rgba(255,255,255,.18)" }} />
            <span className="spin" style={{ borderColor: "rgba(255,255,255,.35)", borderTopColor: "#fff" }} />
            {t("uploading", { p: upload.p })}
          </div>
          <button className="btn btn-ghost btn-lg" onClick={upload.abort}>{t("cancelUpload")}</button>
        </div>
      ) : (
        <button className="btn btn-primary btn-lg btn-block" disabled={!canStart} onClick={start}>
          {starting ? <span className="spin" style={{ borderColor: "rgba(255,255,255,.35)", borderTopColor: "#fff" }} /> : <Icon name="sparkle" />}
          {cloudMode && autoSum ? t("ctaSum") : t("cta")}
        </button>
      )}
    </>
  );

  return (
    <div className="wrap">
      <div className="home-grid">
        <section>
          <span className="eyebrow"><span className="st"><Icon name="sparkle" sm /></span>{t("eyebrow")}</span>
          <h1 style={{ margin: "18px 0 14px" }}>{t("h1a")}<em>{t("h1b")}</em>{t("h1c")}</h1>
          <p className="muted" style={{ fontSize: 17, lineHeight: 1.55, maxWidth: 620, marginBottom: 26 }}>{t("sub")}</p>

          <div className="seg src-tabs" role="tablist">
            <button role="tab" aria-selected={tab === "file"} className={tab === "file" ? "on" : ""} onClick={() => { setPrefs({ srcTab: "file" }); setError(null); }}>
              <Icon name="upload" sm />{t("srcFile")}</button>
            <button role="tab" aria-selected={tab === "link"} className={tab === "link" ? "on" : ""} onClick={() => { setPrefs({ srcTab: "link" }); setError(null); }}>
              <Icon name="youtube" sm />{t("srcLink")}</button>
          </div>

          {tab === "link" ? (
            <div className="dz link-dz">
              <div className="ic"><Icon name="link" /></div>
              <h3>{t("linkT")}</h3>
              <p className="muted" style={{ fontSize: 14.5, margin: "6px 0 16px" }}>{t("linkS")}</p>
              <form className="row gap8" style={{ width: "100%", maxWidth: 620 }} onSubmit={(e) => { e.preventDefault(); if (canStart) start(); }}>
                <input className="input grow" type="url" inputMode="url" autoComplete="off" spellCheck={false} value={link}
                  placeholder="https://www.youtube.com/watch?v=…" onChange={(e) => setLink(e.target.value)} aria-label={t("linkT")} />
                <button type="button" className="btn btn-ghost" onClick={async () => {
                  try { const v = await navigator.clipboard.readText(); if (v) setLink(v.trim()); } catch { /* ruxsat yo'q */ }
                }}>{t("paste")}</button>
              </form>
              {info?.kind === "youtube" && (
                <div className="filerow yt-row" style={{ marginTop: 14, width: "100%", maxWidth: 620, textAlign: "left" }}>
                  <img className="yt-thumb" src={youtubeThumb(info.id!)} alt="" onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
                  <div className="grow" style={{ minWidth: 0 }}>
                    <div className="fname">{info.loading ? t("checking") : info.title || `YouTube · ${info.id}`}</div>
                    <div className="fmeta"><span className="row gap4"><Icon name="youtube" sm />YouTube</span>
                      {info.dur ? <><span>·</span><span>{clock(info.dur)}</span></> : null}
                      {!info.loading && <><span>·</span><span className="ok-t"><Icon name="check" sm />{t("linkReady")}</span></>}
                    </div>
                  </div>
                </div>
              )}
              {info?.kind === "url" && <div className="note info" style={{ marginTop: 14, textAlign: "left", maxWidth: 620 }}><Icon name="link" sm /><span>{t("linkDirect")}</span></div>}
              {info?.kind === "bad" && <div className="note err" style={{ marginTop: 14, textAlign: "left", maxWidth: 620 }}><Icon name="alert" sm /><span>{t("e_link_bad")}</span></div>}
              <div className="row gap6 wrapf" style={{ justifyContent: "center", marginTop: 16 }}>
                <span className="chip"><Icon name="youtube" sm />YouTube</span><span className="chip">Shorts</span><span className="chip">youtu.be</span>
                <span className="chip"><Icon name="link" sm />MP3 · MP4 {t("linkChip")}</span>
              </div>
            </div>
          ) : (
          <label className={`dz${drag ? " drag" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}>
            <input ref={inputRef} className="sr" type="file" accept={ACCEPT}
              onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
            <div className="ic"><Icon name="upload" /></div>
            <h3>{t("drop")}</h3>
            <p className="muted" style={{ fontSize: 14.5, margin: "6px 0 16px" }}>{t("dropOr")}</p>
            <span className="btn btn-ghost" style={{ marginBottom: 18 }}><Icon name="upload" sm />{t("choose")}</span>
            <div className="row gap6 wrapf" style={{ justifyContent: "center" }}>
              {["MP3", "WAV", "M4A", "OGG", "OPUS", "FLAC", "AAC"].map((x) => <span key={x} className="chip">{x}</span>)}
              <span className="chip" style={{ color: "var(--brand-text)" }}><Icon name="video" sm />MP4 · MOV · WEBM</span>
            </div>
            <p className="faint" style={{ fontSize: 13, marginTop: 14 }}>{__STATIC__ ? t("limitsCloud") : t("limits", { mb: maxMb, min: maxMin })}</p>
          </label>
          )}

          {file && tab === "file" && (
            <div className="filerow" style={{ marginTop: 14 }}>
              <div className="ficon"><Icon name={isVideo(file.name, file.type) ? "video" : "music"} /></div>
              <div className="grow">
                <div className="fname" title={file.name}>{file.name}</div>
                <div className="fmeta">
                  <span>{mb(file.size)}</span>
                  {dur ? <><span>·</span><span>{clock(dur)}</span></> : null}
                  <span>·</span>
                  {checking ? <span className="row gap6"><span className="spin sm" />{t("checking")}</span>
                    : error ? <span className="err-t"><Icon name="alert" sm />{t("st_failed")}</span>
                      : <span className="ok-t"><Icon name="check" sm />{t("ready")}</span>}
                </div>
              </div>
              <button className="icon-btn" aria-label="✕" onClick={() => { setFile(null); setError(null); setDur(null); }} disabled={!!upload}>
                <Icon name="x" sm />
              </button>
            </div>
          )}
          {error && tab === "file" && <div className="note err" style={{ marginTop: 12 }}><Icon name="alert" sm /><span>{error}</span></div>}

          <div className="feats desk-only">
            {([["sparkle", "var(--accent-soft)", "var(--accent-text)", "f1"], ["wave", "var(--brand-soft)", "var(--brand-text)", "f2"],
              ["file", "var(--success-soft)", "var(--success)", "f3"], ["shield", "var(--surface-3)", "var(--muted)", "f4"]] as const).map(([ic, bg, fg, k]) => (
              <div className="feat" key={k}>
                <div className="fi" style={{ background: bg, color: fg }}><Icon name={ic} /></div>
                <b>{t(k)}</b><p>{t(k + "s")}</p>
              </div>
            ))}
          </div>
        </section>

        {cloudMode ? (
        <section className="card" style={{ padding: 24 }} aria-label={t("settings")}>
          <div className="row sp" style={{ marginBottom: 20 }}>
            <h2>{t("settings")}</h2>
            <span className="badge b-q"><Icon name="cloud" sm />Gemini</span>
          </div>
          {!hasKey && (
            <div className="card keycard" style={{ padding: 16, marginBottom: 18 }}>
              <b className="row gap6" style={{ marginBottom: 6 }}><Icon name="key" sm />{t("bkNeed")}</b>
              <KeyBox compact onSaved={() => { setHasKey(true); setError(null); }} />
            </div>
          )}
          <div className="label"><Icon name="langs" sm />{t("lang")}</div>
          <div className="lt">
            {langs.map(([code, short]) => (
              <button key={code} className={prefs.language === code ? "on" : ""} onClick={() => setPrefs({ language: code })} aria-pressed={prefs.language === code}>
                <span className="code">{code === "auto" ? <Icon name="sparkle" sm /> : short}</span>
                <div><b>{t("l_" + code)}</b><small>{code === "auto" ? t("auto_s") : code}</small></div>
                {prefs.language === code && <span className="ck"><Icon name="check" /></span>}
              </button>
            ))}
          </div>
          {(prefs.language === "ky" || prefs.language === "kk") && (
            <>
              <div className="label" style={{ marginTop: 20 }}><Icon name="type" sm />{t("script")}</div>
              <div className="seg">
                {["original", "latin"].map((sc) => (
                  <button key={sc} className={prefs.script === sc ? "on" : ""} onClick={() => setPrefs({ script: sc })}>{t(sc === "original" ? "s_cyr" : "s_latin")}</button>
                ))}
              </div>
            </>
          )}
          <div className="label" style={{ marginTop: 20 }}><Icon name="file" sm />{t("mode")}</div>
          <div className="mode">
            {["clean", "verbatim"].map((m) => (
              <button key={m} className={prefs.mode === m ? "on" : ""} onClick={() => setPrefs({ mode: m })}>
                <b><span className="radio" />{t("m_" + m)}</b><p>{t("m_" + m + "_s")}</p>
              </button>
            ))}
          </div>
          <div style={{ marginTop: 6 }}>
            <button className="tg" onClick={() => setPrefs({ autoSummary: !autoSum })} role="switch" aria-checked={autoSum}>
              <div><b className="row gap6"><Icon name="sparkle" sm />{t("autoSum")}</b><small>{t("autoSumS")}</small></div>
              <span className={`toggle${autoSum ? " on" : ""}`} />
            </button>
            {autoSum && (
              <div className="row sp gap8" style={{ padding: "4px 0 12px" }}>
                <span className="muted" style={{ fontSize: 13.5, fontWeight: 600 }}>{t("anLang")}</span>
                <div className="seg" style={{ width: 180 }}>
                  {(["uz", "ru", "en"] as const).map((l) => (
                    <button key={l} className={sumLang === l ? "on" : ""} onClick={() => setPrefs({ summaryLang: l })}>{l.toUpperCase()}</button>
                  ))}
                </div>
              </div>
            )}
          </div>
          <div className="label" style={{ marginTop: 8 }}><Icon name="pen" sm />{t("vocab")}</div>
          <input className="input" value={vocab} maxLength={600} placeholder={t("vocabPh")} onChange={(e) => setVocab(e.target.value)} />
          <div className="faint" style={{ fontSize: 12.5, marginTop: 6 }}>{t("vocabS")}</div>
          {error && tab === "link" && <div className="note err" style={{ marginTop: 14 }}><Icon name="alert" sm /><span>{error}</span></div>}
          <div className="card-cta" style={{ marginTop: 22 }}>{cta}</div>
          <div className="row gap6 muted" style={{ marginTop: 14, fontSize: 13, alignItems: "flex-start" }}>
            <Icon name="lock" sm /><span>{t("cloudPrivB")}</span>
          </div>
        </section>
        ) : (
        <section className="card" style={{ padding: 24 }} aria-label={t("settings")}>
          <div className="row sp" style={{ marginBottom: 20 }}>
            <h2>{t("settings")}</h2>
            <span className="badge b-q"><Icon name={engineInfo?.cloud ? "cloud" : "cpu"} sm />{engineInfo?.cloud ? "Cloud" : "Local"}</span>
          </div>
          <div className="label"><Icon name="langs" sm />{t("lang")}</div>
          <div className="lt">
            {langs.map(([code, short]) => (
              <button key={code} className={prefs.language === code ? "on" : ""} onClick={() => setPrefs({ language: code })} aria-pressed={prefs.language === code}>
                <span className="code">{code === "auto" ? <Icon name="sparkle" sm /> : short}</span>
                <div><b>{t("l_" + code)}</b><small>{code === "auto" ? t("auto_s") : code}</small></div>
                {prefs.language === code && <span className="ck"><Icon name="check" /></span>}
              </button>
            ))}
          </div>
          {curEngine === "faster-whisper" && engineInfo?.language_models?.[prefs.language] && (
            <div className="note" style={{ marginTop: 10, background: "var(--success-soft)", color: "var(--success)" }}><Icon name="check" sm /><span>{t("langModel", { m: engineInfo.language_models[prefs.language] })}</span></div>
          )}
          {curEngine === "faster-whisper" && prefs.language === "uz" && engineInfo && !engineInfo.language_models?.uz && !engines.some((e) => e.id === "gemini") && (
            <div className="note warn" style={{ marginTop: 10 }}><Icon name="info" sm /><span>{t("genericUz")}</span></div>
          )}
          {prefs.language === "ky" && curEngine === "faster-whisper" && !engineInfo?.language_models?.ky && (
            <div className="note warn" style={{ marginTop: 10 }}><Icon name="info" sm /><span>{t("kyNote")}</span></div>
          )}

          <div className="label" style={{ marginTop: 20 }}><Icon name="type" sm />{t("script")}</div>
          <div className="seg">
            {["latin", "original"].map((s) => (
              <button key={s} className={prefs.script === s ? "on" : ""} onClick={() => setPrefs({ script: s })}>{t("s_" + s)}</button>
            ))}
          </div>

          <div className="label" style={{ marginTop: 20 }}><Icon name="file" sm />{t("mode")}</div>
          <div className="mode">
            {["clean", "verbatim"].map((m) => (
              <button key={m} className={prefs.mode === m ? "on" : ""} onClick={() => setPrefs({ mode: m })}>
                <b><span className="radio" />{t("m_" + m)}</b><p>{t("m_" + m + "_s")}</p>
              </button>
            ))}
          </div>

          <div style={{ marginTop: 6 }}>
            <button className="tg" onClick={() => setPrefs({ punctuation: !prefs.punctuation })} role="switch" aria-checked={prefs.punctuation}>
              <div><b>{t("punct")}</b><small>{t("punctS")}</small></div><span className={`toggle${prefs.punctuation ? " on" : ""}`} />
            </button>
            <button className="tg" onClick={() => setPrefs({ paragraphs: !prefs.paragraphs })} role="switch" aria-checked={prefs.paragraphs}>
              <div><b>{t("para")}</b><small>{t("paraS")}</small></div><span className={`toggle${prefs.paragraphs ? " on" : ""}`} />
            </button>
            {pr && !engineInfo?.cloud && (aiAvail ? (
              <button className="tg" onClick={() => setPrefs({ aiProofread: !aiWanted })} role="switch" aria-checked={aiWanted}>
                <div><b className="row gap6"><Icon name="sparkle" sm />{t("aiOn")}</b><small>{t("aiOnS", { m: pr.model })}</small></div>
                <span className={`toggle${aiWanted ? " on" : ""}`} />
              </button>
            ) : (
              <div className="tg" style={{ opacity: 0.75 }}>
                <div><b className="row gap6"><Icon name="sparkle" sm />{t("aiOff")}</b>
                  <small>{pr.reason === "model_not_pulled" ? t("aiNoModel", { m: pr.model }) : t("aiOffS")}</small></div>
                <span className="toggle" />
              </div>
            ))}
            {(prefs.language === "uz" || prefs.language === "auto") && prefs.script === "latin" && (
              <button className="tg" onClick={() => setPrefs({ spellfix: prefs.spellfix === false })} role="switch" aria-checked={prefs.spellfix !== false}>
                <div><b>{t("spellfix")}</b><small>{t("spellfixS")}</small></div><span className={`toggle${prefs.spellfix !== false ? " on" : ""}`} />
              </button>
            )}
          </div>

          {(!engineInfo || engineInfo.chunked) && curEngine !== "dummy" && !engineInfo?.cloud && !engineInfo?.language_models?.[prefs.language] && (
            <>
              <div className="label" style={{ marginTop: 10 }}><Icon name="cpu" sm />{t("quality")}</div>
              <select className="select" value={prefs.quality} onChange={(e) => setPrefs({ quality: e.target.value })}>
                {["fast", "balanced", "best"].map((q) => (
                  <option key={q} value={q}>{t("q_" + q)} — {engineInfo?.models?.[q] || t("q_" + q + "_s")}</option>
                ))}
              </select>
            </>
          )}

          {engines.length > 1 && (
            <>
              <div className="label" style={{ marginTop: 18 }}><Icon name="server" sm />{t("engine")}</div>
              <select className="select" value={curEngine} onChange={(e) => setEngine(e.target.value)}>
                {engines.map((e) => (
                  <option key={e.id} value={e.id}>{e.id === "gemini" ? t("e_gemini") : e.id === "elevenlabs" ? t("e_cloud") : e.id === "dummy" ? t("e_demo") : t("e_local")}</option>
                ))}
              </select>
              {engineInfo?.cloud && <div className="note warn" style={{ marginTop: 10 }}><Icon name="cloud" sm /><span>{curEngine === "gemini" ? t("gemNote") : t("cloudNote")}</span></div>}
              {curEngine === "dummy" && <div className="note warn" style={{ marginTop: 10 }}><Icon name="info" sm /><span>{t("demoNote")}</span></div>}
            </>
          )}

          <div className="label" style={{ marginTop: 18 }}><Icon name="pen" sm />{t("vocab")}</div>
          <input className="input" value={vocab} maxLength={600} placeholder={t("vocabPh")} onChange={(e) => setVocab(e.target.value)} />
          <div className="faint" style={{ fontSize: 12.5, marginTop: 6 }}>{t("vocabS")}</div>

          <div className="card-cta" style={{ marginTop: 22 }}>{cta}</div>
          <div className="row gap6 muted" style={{ marginTop: 14, fontSize: 13 }}>
            <Icon name="lock" sm />{engineInfo?.cloud ? t("cloudPriv", { n: curEngine === "gemini" ? "Google Gemini" : "ElevenLabs" }) : t("localPriv")} · {t("priv", { h: config?.retention_hours ?? 24 })}
          </div>
        </section>
        )}
      </div>

      {history.length > 0 && (
        <div className="card" style={{ marginTop: 28, padding: "20px 6px 6px" }}>
          <div className="row sp" style={{ padding: "0 14px 12px" }}>
            <h2>{t("recent")}</h2>
            <a href="#/history" onClick={(e) => { e.preventDefault(); go("/history"); }} className="row gap4" style={{ fontWeight: 600, fontSize: 14, textDecoration: "none" }}>
              {t("all")}<Icon name="chevr" sm />
            </a>
          </div>
          <table className="tbl">
            <thead><tr><th>{t("th_file")}</th><th className="hide-m">{t("th_lang")}</th><th className="hide-m">{t("th_dur")}</th><th>{t("th_status")}</th></tr></thead>
            <tbody>
              {history.slice(0, 5).map((h) => (
                <tr key={h.id} className="click" onClick={() => go(historyPath(h))}>
                  <td><div className="row gap10" style={{ minWidth: 0 }}>
                    <div className="ficon" style={{ width: 36, height: 36, borderRadius: 10 }}><Icon name={historyIcon(h)} sm /></div>
                    <b className="fname" style={{ fontWeight: 600, maxWidth: 260 }}>{h.filename}</b></div></td>
                  <td className="hide-m">{t("l_" + h.language)}</td>
                  <td className="hide-m muted">{clock(h.duration)}</td>
                  <td><StatusBadge status={h.status} progress={(ACTIVE.includes(h.status) || h.kind === "cloud") && h.status !== "queued" && h.status !== "completed" ? h.progress : undefined} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {((file && tab === "file") || (tab === "link" && info && info.kind !== "bad")) && <div className="mobile-cta">{cta}</div>}
    </div>
  );
}
