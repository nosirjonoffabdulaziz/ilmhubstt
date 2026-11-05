import React, { useEffect, useRef, useState } from "react";
import { useApp } from "./Layout";
import { Icon } from "./Icons";
import KeyBox from "./KeyBox";
import { GeminiError, getKey } from "../services/gemini";
import { loadSummary, makeSummary, parseHms, StoredSummary, storeSummary, summaryMarkdown } from "../services/summary";
import { downloadText, safeName } from "../services/exportLocal";
import { errorText } from "../i18n";
import { nfmt } from "../hooks/format";

// faqat shu oynada bajarilayotgan xulosalar (sahifalar orasida o'tganda ham davom etadi)
const pending = new Map<string, Promise<StoredSummary>>();

export default function SummaryPanel({ summaryKey, transcript, title, onSeek }: {
  summaryKey: string; transcript: string; title: string; onSeek: (t: number) => void;
}) {
  const { t, prefs, setPrefs, toast } = useApp();
  const [data, setData] = useState<StoredSummary | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [chars, setChars] = useState(0);
  const [status, setStatus] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);
  const [hasKey, setHasKey] = useState(!!getKey());
  const [done, setDone] = useState<Record<number, boolean>>({});
  const lang = prefs.summaryLang || prefs.lang;
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    loadSummary(summaryKey).then((s) => { if (alive.current) setData(s || null); }).catch(() => setData(null));
    const p = pending.get(summaryKey);
    if (p) follow(p);
    return () => { alive.current = false; };
  }, [summaryKey]);

  function follow(p: Promise<StoredSummary>) {
    setBusy(true);
    p.then((s) => { if (alive.current) { setData(s); setErr(null); } })
      .catch((e: GeminiError) => {
        if (!alive.current || e.code === "aborted") return;
        setErr(errorText(t, e.code) + (e.detail ? ` (${e.detail.slice(0, 160)})` : ""));
      })
      .finally(() => { if (alive.current) { setBusy(false); setStatus(""); } });
  }

  function run() {
    setErr(null);
    setChars(0);
    const p = makeSummary(transcript, lang, title, {
      onProgress: (n) => alive.current && setChars(n),
      onStatus: (s, d) => alive.current && setStatus(s === "rate_limited_wait" || s === "cloud_retry" ? t("waitInfo", { s: d.wait || 0, a: d.attempt || 1 }) : ""),
    }).then(async (s) => { await storeSummary(summaryKey, s).catch(() => undefined); return s; });
    pending.set(summaryKey, p);
    p.finally(() => pending.delete(summaryKey)).catch(() => undefined);
    follow(p);
  }

  const L: Record<string, string> = {
    title: t("anT"), overview: t("an_overview"), main_idea: t("an_main"), audience: t("an_aud"), key_points: t("an_points"),
    sections: t("an_sections"), facts: t("an_facts"), check: t("an_check"), real_life: t("an_life"), actions: t("an_actions"),
    quotes: t("an_quotes"), terms: t("an_terms"), questions: t("an_questions"), conclusion: t("an_conclusion"),
  };

  const langSel = (
    <div className="seg" style={{ maxWidth: 300 }}>
      {(["uz", "ru", "en"] as const).map((l) => (
        <button key={l} className={lang === l ? "on" : ""} onClick={() => setPrefs({ summaryLang: l })}>{l.toUpperCase()}</button>
      ))}
    </div>
  );

  if (data === undefined) return <div className="empty"><span className="spin" style={{ display: "inline-block" }} /></div>;

  if (!data || busy) {
    return (
      <div className="an-empty">
        <div className="ficon an-ic"><Icon name="sparkle" /></div>
        <h2 style={{ margin: "12px 0 6px" }}>{t("anT")}</h2>
        <p className="muted" style={{ maxWidth: 520, margin: "0 auto 18px", fontSize: 14.5 }}>{t("anIntro")}</p>
        {busy ? (
          <div style={{ maxWidth: 420, margin: "0 auto" }}>
            <div className="pbar anim"><i style={{ width: `${Math.min(95, 8 + chars / 90)}%` }} /></div>
            <div className="muted" style={{ fontSize: 13, marginTop: 10 }}>{status || t("anBusy", { n: nfmt(chars) })}</div>
          </div>
        ) : !hasKey ? (
          <div className="card" style={{ padding: 18, textAlign: "left", maxWidth: 560, margin: "0 auto" }}>
            <KeyBox compact onSaved={() => setHasKey(true)} />
          </div>
        ) : (
          <>
            <div className="row gap10 wrapf" style={{ justifyContent: "center", marginBottom: 14 }}>
              <span className="muted" style={{ fontSize: 13.5, fontWeight: 600 }}>{t("anLang")}</span>{langSel}
            </div>
            <button className="btn btn-primary btn-lg" onClick={run} disabled={!transcript.trim()}><Icon name="sparkle" />{t("anMake")}</button>
            <div className="faint" style={{ fontSize: 12.5, marginTop: 10 }}>{t("anCost")}</div>
          </>
        )}
        {err && <div className="note err" style={{ marginTop: 16, textAlign: "left" }}><Icon name="alert" sm /><span>{err}</span></div>}
      </div>
    );
  }

  const s = data.summary;
  const md = () => summaryMarkdown(s, L);
  const tbtn = (time: string) => {
    const sec = parseHms(time);
    return sec != null ? <button className="ts" onClick={() => onSeek(sec)}>{time.replace(/^00:/, "")}</button> : null;
  };

  return (
    <div className="an">
      <div className="an-head">
        <div className="grow" style={{ minWidth: 0 }}>
          <div className="row gap6 wrapf" style={{ marginBottom: 6 }}>
            {s.genre && <span className="chip">{s.genre}</span>}
            <span className="chip"><Icon name="sparkle" sm />{data.model}</span>
          </div>
          <h2 className="an-title">{s.title || title}</h2>
        </div>
        <div className="row gap8 wrapf">
          <button className="btn btn-ghost" onClick={async () => {
            try { await navigator.clipboard.writeText(md()); toast(t("copied")); } catch { toast("✕"); }
          }}><Icon name="copy" sm />{t("copy")}</button>
          <button className="btn btn-ghost" onClick={() => downloadText(`${safeName(title)}_xulosa.md`, md(), "text/markdown")}><Icon name="download" sm />.md</button>
          <button className="btn btn-ghost" onClick={() => { if (window.confirm(t("anRedo"))) { setData(null); } }} title={t("anRedo")}><Icon name="refresh" sm /></button>
        </div>
      </div>

      {s.overview && <p className="an-lead">{s.overview}</p>}
      {s.main_idea && <div className="an-main"><Icon name="sparkle" sm /><div><b>{L.main_idea}</b><p>{s.main_idea}</p></div></div>}
      {s.audience && <p className="muted" style={{ fontSize: 14, margin: "10px 0 0" }}><b>{L.audience}:</b> {s.audience}</p>}

      <div className="an-grid">
        {s.key_points.length > 0 && (
          <section className="an-box">
            <h3><Icon name="check" sm />{L.key_points}</h3>
            <ul className="an-list">{s.key_points.map((x, i) => <li key={i}>{x}</li>)}</ul>
          </section>
        )}
        {s.actions.length > 0 && (
          <section className="an-box an-act">
            <h3><Icon name="sparkle" sm />{L.actions}</h3>
            <ol className="an-steps">
              {s.actions.map((x, i) => (
                <li key={i} className={done[i] ? "dn" : ""}>
                  <label>
                    <input type="checkbox" checked={!!done[i]} onChange={() => setDone({ ...done, [i]: !done[i] })} />
                    <span><b>{x.step}</b>{x.why && <small>{x.why}</small>}{x.when && <em>{x.when}</em>}</span>
                  </label>
                </li>
              ))}
            </ol>
          </section>
        )}
        {s.real_life.length > 0 && (
          <section className="an-box">
            <h3><Icon name="globe" sm />{L.real_life}</h3>
            <ul className="an-list">{s.real_life.map((x, i) => <li key={i}><b>{x.idea}</b>{x.how && <> — {x.how}</>}</li>)}</ul>
          </section>
        )}
        {s.facts.length > 0 && (
          <section className="an-box">
            <h3><Icon name="info" sm />{L.facts}</h3>
            <ul className="an-facts">
              {s.facts.map((x, i) => (
                <li key={i}>{tbtn(x.time)}<span>{x.fact}{x.check && <span className="badge b-acc" style={{ marginLeft: 6, minHeight: 20, fontSize: 11 }} title={L.check}><Icon name="alert" sm />{L.check}</span>}</span></li>
              ))}
            </ul>
          </section>
        )}
      </div>

      {s.sections.length > 0 && (
        <section className="an-box" style={{ marginTop: 16 }}>
          <h3><Icon name="clock" sm />{L.sections}</h3>
          <div className="an-tl">
            {s.sections.map((x, i) => (
              <div key={i} className="an-tli">{tbtn(x.start)}<div><b>{x.title}</b><p>{x.summary}</p></div></div>
            ))}
          </div>
        </section>
      )}

      <div className="an-grid">
        {s.quotes.length > 0 && (
          <section className="an-box">
            <h3><Icon name="pen" sm />{L.quotes}</h3>
            {s.quotes.map((x, i) => (
              <blockquote key={i} className="an-q">«{x.text}»<footer>{x.speaker && <span>{x.speaker}</span>}{tbtn(x.time)}</footer></blockquote>
            ))}
          </section>
        )}
        {s.terms.length > 0 && (
          <section className="an-box">
            <h3><Icon name="type" sm />{L.terms}</h3>
            <dl className="an-terms">{s.terms.map((x, i) => <React.Fragment key={i}><dt>{x.term}</dt><dd>{x.meaning}</dd></React.Fragment>)}</dl>
          </section>
        )}
        {s.questions.length > 0 && (
          <section className="an-box">
            <h3><Icon name="langs" sm />{L.questions}</h3>
            <ul className="an-list">{s.questions.map((x, i) => <li key={i}>{x}</li>)}</ul>
          </section>
        )}
      </div>

      {s.conclusion && (
        <div className="an-concl"><b>{L.conclusion}</b><p>{s.conclusion}</p></div>
      )}
      <div className="faint" style={{ fontSize: 12, marginTop: 14 }}>
        {t("anFoot", { m: data.model, c: data.usage.cost_usd.toFixed(4) })}
      </div>
    </div>
  );
}
