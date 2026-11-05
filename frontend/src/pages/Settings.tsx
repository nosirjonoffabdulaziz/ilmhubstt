import React, { useEffect, useState } from "react";
import { useApp } from "../components/Layout";
import { Icon } from "../components/Icons";
import { api, ApiError, getAccessKey, setAccessKey } from "../services/api";
import { errorText } from "../i18n";
import { saveHistory } from "../services/storage";
import type { Lang } from "../i18n";
import KeyBox from "../components/KeyBox";
import { cleanKey, getKey, getModelPref, listModels, rankModels, setKey as setGeminiKey, setModelPref } from "../services/gemini";
import { idbClear } from "../services/idb";

export default function SettingsPage() {
  const { t, prefs, setPrefs, config, toast, reloadConfig } = useApp();
  const [health, setHealth] = useState<any>(null);
  const [key, setKey] = useState(getAccessKey());
  const [gem, setGem] = useState<{ key_set: boolean; key_hint: string; model: string; available: boolean } | null>(null);
  const [gemKey, setGemKey] = useState("");
  const [gemBusy, setGemBusy] = useState(false);
  const [gemErr, setGemErr] = useState<string | null>(null);

  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState(getModelPref());
  const refreshModels = () => { if (getKey()) listModels().then((m) => setModels(rankModels(m))).catch(() => setModels([])); };
  useEffect(refreshModels, []);
  useEffect(() => { if (!__STATIC__) api.geminiStatus().then(setGem).catch(() => setGem(null)); }, []);

  async function saveGemini() {
    setGemBusy(true);
    setGemErr(null);
    try {
      const r = await api.geminiSave(gemKey.trim());
      setGem(r);
      setGeminiKey(cleanKey(gemKey), true); // YouTube va xulosa uchun brauzerda ham
      refreshModels();
      setGemKey("");
      setPrefs({ engine: "gemini" });
      reloadConfig();
      toast(t("gemSaved"));
    } catch (e) {
      const err = e as ApiError;
      const detail = err.extra?.detail ? ` (Google: ${String(err.extra.detail).slice(0, 200)})` : "";
      setGemErr(errorText(t, err.code) + detail);
    } finally {
      setGemBusy(false);
    }
  }
  async function deleteGemini() {
    try { setGem(await api.geminiDelete()); } catch { /* */ }
    if (prefs.engine === "gemini") setPrefs({ engine: "" });
    reloadConfig();
  }

  useEffect(() => { if (!__STATIC__) api.health().then(setHealth).catch(() => setHealth({ ok: false })); }, []);

  const group = (title: string, children: React.ReactNode) => (
    <>
      <div className="faint" style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".07em", textTransform: "uppercase", margin: "24px 4px 10px" }}>{title}</div>
      <div className="card" style={{ padding: "4px 18px", borderRadius: 18 }}>{children}</div>
    </>
  );
  const line = (icon: string, label: string, right: React.ReactNode, sub?: string) => (
    <div className="tg" style={{ flexWrap: "wrap" }}>
      <div className="row gap12" style={{ minWidth: 0 }}>
        <span className="ficon" style={{ width: 36, height: 36, borderRadius: 10 }}><Icon name={icon} sm /></span>
        <div><b>{label}</b>{sub && <small>{sub}</small>}</div>
      </div>
      <div style={{ marginLeft: "auto" }}>{right}</div>
    </div>
  );
  const selectRow = (val: string, opts: [string, string][], on: (v: string) => void) => (
    <select className="select" style={{ minHeight: 40, width: "auto" }} value={val} onChange={(e) => on(e.target.value)}>
      {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
  const engines = health?.engines || config?.engines || [];

  return (
    <div className="wrap" style={{ maxWidth: 820 }}>
      <h1 style={{ fontSize: 30 }}>{t("setT")}</h1>

      {group(t("g_iface"), <>
        {line("globe", t("iface"), (
          <div className="lang">
            {(["uz", "ru", "en"] as Lang[]).map((l) => (
              <button key={l} className={prefs.lang === l ? "on" : ""} onClick={() => setPrefs({ lang: l })}>{l.toUpperCase()}</button>
            ))}
          </div>
        ))}
        <div className="tg" style={{ display: "block" }}>
          <b style={{ marginBottom: 10 }}>{t("theme")}</b>
          <div className="seg">
            {(["light", "dark", "system"] as const).map((th) => (
              <button key={th} className={prefs.theme === th ? "on" : ""} onClick={() => setPrefs({ theme: th })}>
                {th !== "system" && <Icon name={th === "light" ? "sun" : "moon"} sm />}{t("th_" + th)}
              </button>
            ))}
          </div>
        </div>
      </>)}

      {group(t("g_trans"), <>
        {line("langs", t("lang"), selectRow(prefs.language, ["uz", "ky", "kk", "auto"].map((l) => [l, t("l_" + l)]), (v) => setPrefs({ language: v })))}
        {line("type", t("script"), selectRow(prefs.script, [["latin", t("s_latin")], ["original", t("s_original")]], (v) => setPrefs({ script: v })))}
        {line("file", t("mode"), selectRow(prefs.mode, [["clean", t("m_clean")], ["verbatim", t("m_verbatim")]], (v) => setPrefs({ mode: v })))}
        {!__STATIC__ && line("cpu", t("quality"), selectRow(prefs.quality, ["fast", "balanced", "best"].map((q) => [q, t("q_" + q)]), (v) => setPrefs({ quality: v })))}
        {!__STATIC__ && line("type", t("tprof"), <span />, Object.values(config?.transliteration_profiles || {}).join(" · "))}
        {line("sparkle", t("anLang"), selectRow(prefs.summaryLang || prefs.lang, [["uz", "O‘zbek"], ["ru", "Русский"], ["en", "English"]], (v) => setPrefs({ summaryLang: v })))}
      </>)}

      {group(t("bkGroup"), <>
        <div className="tg" style={{ display: "block" }}>
          <KeyBox onSaved={(m) => setModels(rankModels(m))} />
        </div>
        {line("cpu", t("bkModel"), selectRow(model, [["", t("bkAuto") + (models[0] ? ` (${models[0]})` : "")], ...models.map((m) => [m, m] as [string, string])],
          (v) => { setModel(v); setModelPref(v); }), t("bkModelS"))}
        <div className="tg" style={{ display: "block" }}>
          <div className="note info"><Icon name="shield" sm /><span>{t("bkPriv")}</span></div>
        </div>
      </>)}

      {!__STATIC__ && group(t("gemT"), <>
        <div className="tg" style={{ display: "block" }}>
          <div className="row sp" style={{ marginBottom: 8 }}>
            <b className="row gap6"><Icon name="cloud" sm />Google Gemini</b>
            <span className={`badge ${gem?.available ? "b-ok" : "b-q"}`}>{gem?.available ? `${t("gemActive")} ${gem.key_hint}` : t("gemNone")}</span>
          </div>
          <small style={{ display: "block", marginBottom: 12 }}>{t("gemS")}</small>
          <form className="row gap8 wrapf" onSubmit={(e) => { e.preventDefault(); if (gemKey.trim()) saveGemini(); }}>
            <input className="input grow" style={{ minWidth: 200 }} type="password" autoComplete="off" value={gemKey}
              placeholder={t("gemPh")} onChange={(e) => setGemKey(e.target.value)} />
            <button type="submit" className="btn btn-primary" disabled={gemBusy || !gemKey.trim()}>
              {gemBusy ? <><span className="spin sm" style={{ borderTopColor: "#fff" }} />{t("gemSaving")}</> : t("gemSave")}
            </button>
          </form>
          {gemErr && <div className="note err" style={{ marginTop: 10 }}><Icon name="alert" sm /><span>{gemErr}</span></div>}
          {gem?.available && <div className="note" style={{ marginTop: 10, background: "var(--success-soft)", color: "var(--success)" }}><Icon name="check" sm /><span>{t("gemReady")} ({gem.model})</span></div>}
          <div className="row sp wrapf gap8" style={{ marginTop: 12 }}>
            <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer noopener" className="row gap6" style={{ fontWeight: 600, fontSize: 14 }}>
              <Icon name="key" sm />{t("gemGet")}</a>
            {gem?.key_set && <button className="btn btn-danger" style={{ minHeight: 36 }} onClick={deleteGemini}><Icon name="trash" sm />{t("gemDel")}</button>}
          </div>
          <div className="note warn" style={{ marginTop: 12 }}><Icon name="info" sm /><span>{t("gemNote")}</span></div>
        </div>
      </>)}

      {__STATIC__ ? group(t("g_priv"), <>
        {line("clock", t("keep"), <span className="muted" style={{ fontWeight: 600 }}>{t("keepB")}</span>)}
        {line("info", t("version"), <span className="muted" style={{ fontWeight: 600 }}>ilmhubstt web</span>)}
      </>) : group(t("g_priv"), <>
        {line("clock", t("keep"), <span className="muted" style={{ fontWeight: 600 }}>{t("hours", { h: config?.retention_hours ?? 24 })}</span>)}
        {line("server", t("server"), (
          <span className={`badge ${health?.ok ? "b-ok" : "b-err"}`}>{health ? (health.ok ? t("ok") : t("missing")) : "…"}</span>
        ), `FFmpeg: ${health?.tools?.ffmpeg ? t("ok") : t("missing")} · ` +
          engines.map((e: any) => `${e.id}: ${e.available ? t("ok") : t("missing")}`).join(" · "))}
        {config?.requires_access_key && (
          <div className="tg" style={{ display: "block" }}>
            <b style={{ marginBottom: 4 }}>{t("accessKey")}</b><small>{t("accessKeyS")}</small>
            <div className="row gap8" style={{ marginTop: 10 }}>
              <input className="input" type="password" value={key} onChange={(e) => setKey(e.target.value)} />
              <button className="btn btn-primary" onClick={() => { setAccessKey(key.trim()); toast(t("saved")); }}>{t("save")}</button>
            </div>
          </div>
        )}
        {line("sparkle", t("k_ai"), (
          <span className={`badge ${health?.proofreader?.available ? "b-ok" : "b-q"}`}>{health?.proofreader?.available ? t("ok") : t("missing")}</span>
        ), health?.proofreader ? `Ollama · ${health.proofreader.model}` : "")}
        {line("info", t("version"), <span className="muted" style={{ fontWeight: 600 }}>ilmhubstt {config?.version || ""}</span>)}
      </>)}

      <button className="btn btn-danger btn-block" style={{ marginTop: 22, minHeight: 50 }}
        onClick={async () => { if (!window.confirm(t("clearQ"))) return; saveHistory([]); await idbClear(); toast(t("clearHist") + " ✓"); }}>
        <Icon name="trash" sm />{t("clearHist")}
      </button>
    </div>
  );
}
