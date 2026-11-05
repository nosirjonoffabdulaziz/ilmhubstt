import React, { useState } from "react";
import { useApp } from "./Layout";
import { Icon } from "./Icons";
import { cleanKey, GeminiError, getKey, keyHint, KEY_RE, setKey, verifyKey } from "../services/gemini";
import { errorText } from "../i18n";

/** Gemini API kalitini kiritish (faqat shu brauzerda saqlanadi). */
export default function KeyBox({ onSaved, compact }: { onSaved?: (models: string[]) => void; compact?: boolean }) {
  const { t, toast } = useApp();
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [remember, setRemember] = useState(true);
  const [cur, setCur] = useState(getKey());

  async function save() {
    const k = cleanKey(val);
    setErr(null);
    if (!KEY_RE.test(k)) { setErr(t("e_cloud_auth_failed")); return; }
    setBusy(true);
    try {
      const models = await verifyKey(k);
      setKey(k, remember);
      setCur(k);
      setVal("");
      toast(t("gemSaved"));
      onSaved?.(models);
    } catch (e) {
      const g = e as GeminiError;
      setErr(errorText(t, g.code) + (g.detail ? ` (Google: ${g.detail.slice(0, 180)})` : ""));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={compact ? "keybox compact" : "keybox"}>
      {!compact && (
        <div className="row sp" style={{ marginBottom: 8 }}>
          <b className="row gap6"><Icon name="key" sm />{t("bkT")}</b>
          <span className={`badge ${cur ? "b-ok" : "b-q"}`}>{cur ? `${t("gemActive")} ${keyHint(cur)}` : t("gemNone")}</span>
        </div>
      )}
      <small className="muted" style={{ display: "block", marginBottom: 10, fontSize: 13 }}>{t("bkS")}</small>
      <form className="row gap8 wrapf" onSubmit={(e) => { e.preventDefault(); if (val.trim()) save(); }}>
        <input className="input grow" style={{ minWidth: 200 }} type="password" autoComplete="off" spellCheck={false}
          value={val} placeholder={t("gemPh")} onChange={(e) => setVal(e.target.value)} aria-label={t("bkT")} />
        <button type="submit" className="btn btn-primary" disabled={busy || !val.trim()}>
          {busy ? <><span className="spin sm" style={{ borderTopColor: "#fff" }} />{t("gemSaving")}</> : t("gemSave")}
        </button>
      </form>
      <label className="row gap8 muted" style={{ fontSize: 13, marginTop: 10, cursor: "pointer" }}>
        <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />{t("bkRemember")}
      </label>
      {err && <div className="note err" style={{ marginTop: 10 }}><Icon name="alert" sm /><span>{err}</span></div>}
      <div className="row sp wrapf gap8" style={{ marginTop: 10 }}>
        <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer noopener" className="row gap6" style={{ fontWeight: 600, fontSize: 14 }}>
          <Icon name="key" sm />{t("gemGet")}</a>
        {cur && !compact && (
          <button className="btn btn-danger" style={{ minHeight: 36 }} onClick={() => { setKey(""); setCur(""); toast(t("bkDeleted")); }}>
            <Icon name="trash" sm />{t("gemDel")}
          </button>
        )}
      </div>
    </div>
  );
}
