import React, { useEffect, useRef, useState } from "react";
import { useApp, StatusBadge } from "../components/Layout";
import { Icon } from "../components/Icons";
import ResultView, { serverBackend } from "../components/ResultView";
import { api, ApiError, Job, Result } from "../services/api";
import { findHistory, upsertHistory } from "../services/storage";
import { errorText, warningText } from "../i18n";
import { clock, human, isVideo } from "../hooks/format";

const FINAL = ["completed", "failed", "cancelled"];
const SPECIAL = ["uploading_cloud", "downloading_model", "loading_model", "checking_gpu", "proofreading", "rate_limited_wait", "cloud_retry"];
const ORDER = ["queued", "converting", "transcribing", "normalizing", "completed"];

export default function JobPage({ id }: { id: string; key?: React.Key }) {
  const { t, go, askKey, config } = useApp();
  const hist = findHistory(id);
  const token = hist?.token || "";
  const [job, setJob] = useState<Job | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(token ? null : "not_found");
  const [cancelling, setCancelling] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!token) return;
    let alive = true;
    let fails = 0;
    const poll = async () => {
      try {
        const j = await api.job(id, token);
        if (!alive) return;
        fails = 0;
        setJob(j);
        setError(null);
        upsertHistory({ id, status: j.status, progress: j.progress, duration: j.duration });
        if (j.status === "completed") {
          const r = await api.result(id, token);
          if (alive) setResult(r);
          return;
        }
        if (FINAL.includes(j.status)) return;
      } catch (e) {
        const err = e as ApiError;
        if (err.code === "access_key_required") askKey();
        if (err.code === "not_found") {
          upsertHistory({ id, status: "expired" });
          if (alive) setError("not_found");
          return;
        }
        fails += 1;
        if (alive && fails >= 3) setError(err.code || "network");
      }
      if (alive) timer.current = window.setTimeout(poll, document.hidden ? 4000 : 1200);
    };
    poll();
    return () => { alive = false; window.clearTimeout(timer.current); };
  }, [id, token]);

  async function cancel() {
    setCancelling(true);
    try { await api.cancel(id, token); } catch { /* holat so'rovida ko'rinadi */ }
  }

  if (result && job) {
    const cloudName = /gemini/i.test(result.model) ? "Google Gemini" : /cloud/i.test(result.model) ? "ElevenLabs" : null;
    return <ResultView job={job} result={result} backend={serverBackend(job, token, t, config?.retention_hours ?? 24, cloudName)} />;
  }

  if (error && !job) {
    return (
      <div className="wrap">
        <div className="card empty">
          <div className="ficon" style={{ margin: "0 auto 14px", background: "var(--danger-soft)", color: "var(--danger)" }}><Icon name="alert" /></div>
          <h2 style={{ marginBottom: 8 }}>{errorText(t, error)}</h2>
          <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => go("/")}><Icon name="upload" sm />{t("newFile")}</button>
        </div>
      </div>
    );
  }
  if (!job) {
    return <div className="wrap"><div className="empty"><span className="spin" style={{ display: "inline-block" }} /></div></div>;
  }

  if (job.status === "failed" || job.status === "cancelled") {
    const failed = job.status === "failed";
    return (
      <div className="wrap" style={{ maxWidth: 720 }}>
        <div className="card" style={{ padding: 28 }}>
          <div className="ficon" style={{ marginBottom: 14, background: failed ? "var(--danger-soft)" : "var(--surface-3)", color: failed ? "var(--danger)" : "var(--muted)" }}>
            <Icon name={failed ? "alert" : "x"} />
          </div>
          <h2 style={{ fontSize: 22, marginBottom: 6 }}>{failed ? t("failedT") : t("cancelledT")}</h2>
          <p className="muted" style={{ marginBottom: 6 }}>{job.filename}</p>
          {failed && <div className="note err" style={{ marginTop: 14 }}><Icon name="alert" sm /><span>{errorText(t, job.error || "internal_error")}</span></div>}
          <button className="btn btn-primary" style={{ marginTop: 20 }} onClick={() => go("/")}><Icon name="refresh" sm />{t("retry")}</button>
        </div>
      </div>
    );
  }

  const dl = job.stage === "downloading_model" ? job.detail : null;
  const dlPct = dl && dl.total_mb ? Math.min(100, ((dl.done_mb || 0) / dl.total_mb) * 100) : 0;
  const stageIdx = Math.max(0, ORDER.indexOf(job.status));
  const stageNo = Math.min(5, stageIdx + 1);
  const steps: { title: string; sub: string }[] = [
    { title: t("step1"), sub: job.queue_position ? t("queuePos", { n: job.queue_position }) : clock(job.duration) },
    { title: t("step2"), sub: t("step2s") },
    { title: SPECIAL.includes(job.stage) ? t("st_" + job.stage) : t("step3"),
      sub: dl ? (dl.total_mb ? t("dlInfo", { done: Math.round(dl.done_mb || 0), total: dl.total_mb, speed: (dl.speed_mbs || 0).toFixed(1) }) : `${Math.round(dl.done_mb || 0)} MB`)
        : job.stage === "loading_model" ? `${job.detail?.model || ""} · ${(job.detail?.device || "").toUpperCase()}`
        : (job.stage === "rate_limited_wait" || job.stage === "cloud_retry") ? t("waitInfo", { s: job.detail?.wait || 0, a: job.detail?.attempt || 1 })
        : job.status === "transcribing" ? t("step3s", { a: clock(job.processed_seconds), b: clock(job.duration) }) : t("waiting") },
    { title: job.stage === "proofreading" ? t("st_proofreading") : t("step4"),
      sub: job.stage === "proofreading" && job.detail?.total ? t("aiProg", { d: job.detail.done || 0, t: job.detail.total, m: job.detail.model || "" }) : t("waiting") },
    { title: t("step5"), sub: t("waiting") },
  ];
  const active = job.status === "queued" ? 0 : stageIdx;

  return (
    <div className="wrap">
      <button className="row gap8 muted" style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }} onClick={() => go("/")}>
        <Icon name="chevl" sm />{t("back")}
      </button>
      <h1 style={{ fontSize: 32, marginBottom: 22 }}>{t("procT")}</h1>
      <div className="two">
        <div className="card" style={{ padding: 26 }}>
          <div className="row gap12">
            <div className="ficon"><Icon name={isVideo(job.filename) ? "video" : "music"} /></div>
            <div className="grow">
              <div className="fname">{job.filename}</div>
              <div className="fmeta">{t("l_" + job.options.language)} · {t("s_" + job.options.script)} · {t("m_" + job.options.mode)} · {clock(job.duration)}</div>
            </div>
          </div>
          <div className="row sp" style={{ alignItems: "flex-end", margin: "24px 0 12px" }}>
            <div>
              <div className="muted" style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{t("stage", { n: stageNo })}</div>
              <div style={{ fontSize: 52, fontWeight: 800, letterSpacing: "-.03em", lineHeight: 1 }}>
                {Math.floor(job.progress)}<span style={{ fontSize: ".5em", color: "var(--muted)" }}>%</span>
              </div>
            </div>
            <StatusBadge status={job.status} />
          </div>
          <div className={`pbar${job.status !== "queued" ? " anim" : ""}`} role="progressbar" aria-valuenow={job.progress} aria-valuemin={0} aria-valuemax={100}>
            <i style={{ width: `${Math.max(2, job.progress)}%` }} />
          </div>
          <div className="row sp muted" style={{ fontSize: 13, marginTop: 10 }}>
            <span>{t("st_" + (SPECIAL.includes(job.stage) ? job.stage : job.status))}</span>
            <span>{dl ? (dl.eta ? t("left", { t: human(dl.eta, t) }) : "") : job.eta_seconds ? t("left", { t: human(job.eta_seconds, t) }) : job.queue_position ? t("queuePos", { n: job.queue_position }) : ""}</span>
          </div>
          {dl && (
            <div className="note info" style={{ marginTop: 16, display: "block" }}>
              <div className="row gap8" style={{ fontWeight: 700, marginBottom: 8 }}><Icon name="download" sm />{t("dlModel")}</div>
              <div className="pbar anim" style={{ height: 8, background: "var(--surface)" }}><i style={{ width: `${Math.max(2, dlPct)}%` }} /></div>
              <div className="row sp" style={{ marginTop: 8, fontWeight: 600 }}>
                <span>{dl.total_mb ? t("dlInfo", { done: Math.round(dl.done_mb || 0), total: dl.total_mb, speed: (dl.speed_mbs || 0).toFixed(1) }) : `${Math.round(dl.done_mb || 0)} MB`}</span>
                <span>{dl.total_mb ? `${Math.floor(dlPct)}%` : ""}</span>
              </div>
              <div style={{ marginTop: 6, fontSize: 12.5, opacity: 0.85 }}>{t("dlTip")}</div>
            </div>
          )}

          <div className="steps" style={{ marginTop: 26 }}>
            {steps.map((s, i) => {
              const done = i < active || (i === 0 && job.status !== "queued");
              const act = i === active && !done;
              return (
                <div key={i} className={`step${done ? " done" : act ? " act" : ""}`}>
                  <div className="sd">{done ? <Icon name="check" sm /> : act ? <span className="spin" /> : i + 1}</div>
                  <div>
                    <b>{s.title}</b><small>{done && i > 0 ? "✓" : s.sub}</small>
                    {act && i === 2 && job.duration > 0 && !dl && job.stage === "transcribing" && (
                      <div className="pbar" style={{ height: 6, marginTop: 10, width: 220, maxWidth: "100%" }}>
                        <i style={{ width: `${Math.min(100, (job.processed_seconds / job.duration) * 100)}%` }} />
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {job.warnings.map((w) => <div key={w} className="note warn" style={{ marginTop: 16 }}><Icon name="info" sm /><span>{warningText(t, w)}</span></div>)}
          <div className="note info" style={{ marginTop: 22 }}><Icon name="shield" sm /><span>{t("safe")}</span></div>
          <button className="btn btn-ghost btn-block" style={{ marginTop: 16 }} onClick={cancel} disabled={cancelling}>
            {cancelling ? <><span className="spin sm" />{t("cancelling")}</> : <><Icon name="x" sm />{t("cancel")}</>}
          </button>
        </div>

        <div className="card" style={{ padding: 24 }}>
          <div className="row sp" style={{ marginBottom: 14 }}>
            <div><h2>{t("live")}</h2><div className="muted" style={{ fontSize: 13, marginTop: 3 }}>{t("liveS")}</div></div>
            {job.duration > 0 && <span className="badge b-q">{clock(job.processed_seconds)} / {clock(job.duration)}</span>}
          </div>
          {job.preview.length === 0 ? (
            <p className="faint" style={{ fontSize: 14, padding: "12px 0" }}>{t("liveEmpty")}</p>
          ) : (
            <div className="segs">
              {job.preview.map((p, i) => (
                <div className="sg" key={i}><span className="ts">{clock(p.t)}</span><p style={{ fontSize: 15 }}>{p.x}</p></div>
              ))}
            </div>
          )}
          {job.status !== "queued" && (
            <div className="sg" aria-hidden="true">
              <span className="ts" style={{ opacity: 0.5 }}>{clock(job.processed_seconds)}</span>
              <div style={{ flex: 1, paddingTop: 6 }}>
                <div style={{ height: 10, borderRadius: 6, background: "var(--surface-3)", width: "90%", marginBottom: 9 }} />
                <div style={{ height: 10, borderRadius: 6, background: "var(--surface-3)", width: "60%" }} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
