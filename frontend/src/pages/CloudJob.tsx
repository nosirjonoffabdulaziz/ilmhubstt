import React, { useEffect, useMemo, useState } from "react";
import { useApp, StatusBadge } from "../components/Layout";
import { Icon } from "../components/Icons";
import ResultView, { Media, ResultBackend } from "../components/ResultView";
import KeyBox from "../components/KeyBox";
import {
  buildResult, cancelCloudJob, CloudJob, deleteCloudJob, isRunning, loadCloudJob, mediaUrl, RUNNING, saveCloudEdit, startCloudJob, subscribe,
} from "../services/cloud";
import { getKey } from "../services/gemini";
import { exportLocal } from "../services/exportLocal";
import { youtubeThumb } from "../services/youtube";
import { errorText, warningText } from "../i18n";
import { clock } from "../hooks/format";
import type { Job } from "../services/api";

export default function CloudJobPage({ id }: { id: string; key?: React.Key }) {
  const { t, go } = useApp();
  const [job, setJob] = useState<CloudJob | null | undefined>(undefined);
  const [src, setSrc] = useState<string | null>(null);
  const [hasKey, setHasKey] = useState(!!getKey());

  useEffect(() => {
    let alive = true;
    loadCloudJob(id).then((j) => { if (alive) setJob(j ? { ...j } : null); });
    const un = subscribe(id, (j) => alive && setJob(j));
    return () => { alive = false; un(); };
  }, [id]);

  const done = job?.status === "completed";
  useEffect(() => {
    if (!done || !job || job.source.type === "youtube") return;
    let url: string | null = null;
    mediaUrl(job).then((u) => { url = u; setSrc(u); });
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [done, job?.id]);

  const result = useMemo(() => (job && done ? buildResult(job) : null), [job, done]);

  if (job === undefined) return <div className="wrap"><div className="empty"><span className="spin" style={{ display: "inline-block" }} /></div></div>;
  if (job === null) {
    return (
      <div className="wrap">
        <div className="card empty">
          <div className="ficon" style={{ margin: "0 auto 14px", background: "var(--danger-soft)", color: "var(--danger)" }}><Icon name="alert" /></div>
          <h2 style={{ marginBottom: 8 }}>{errorText(t, "not_found")}</h2>
          <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => go("/")}><Icon name="upload" sm />{t("newFile")}</button>
        </div>
      </div>
    );
  }

  const resume = () => { if (getKey()) startCloudJob(id); else setHasKey(false); };

  if (result && done) {
    const media: Media = job.source.type === "youtube" && job.source.videoId ? { kind: "youtube", id: job.source.videoId }
      : src ? { kind: "audio", src } : { kind: "none" };
    const backend: ResultBackend = {
      save: (text) => saveCloudEdit(id, text),
      exportFile: async (fmt, text) => exportLocal(result, text, fmt),
      remove: () => deleteCloudJob(id),
      media, cloud: true,
      privacyTitle: t("cloudPriv", { n: "Google Gemini" }),
      privacySub: t("browserStore"),
      summaryKey: id,
      onContinue: resume,
    };
    const fakeJob = { job_id: id, filename: job.source.name, duration: job.duration } as unknown as Job;
    return <ResultView key={job.finished || 0} job={fakeJob} result={result} backend={backend} />;
  }

  const s = job.source;
  const running = RUNNING.includes(job.status) && isRunning(id);
  const failed = job.status === "failed";
  const stopped = job.status === "paused" || job.status === "cancelled" || (RUNNING.includes(job.status) && !isRunning(id));

  const steps: { k: string; title: string; sub: string }[] = [
    { k: "src", title: s.type === "youtube" ? t("cs_yt") : s.type === "url" ? t("cs_link") : t("cs_upload"),
      sub: job.stage === "uploading" ? `${job.detail.upload ?? 0}%` : job.stage === "downloading" && job.detail.done_mb != null ? `${Math.round(job.detail.done_mb)} MB` : t("waiting") },
    { k: "proc", title: t("cs_google"), sub: t("waiting") },
    { k: "tr", title: job.stage === "rate_limited_wait" || job.stage === "cloud_retry" ? t("st_" + job.stage) : t("step3"),
      sub: job.stage === "rate_limited_wait" || job.stage === "cloud_retry"
        ? t("waitInfo", { s: job.detail.wait || 0, a: job.detail.attempt || 1 }) + (job.detail.model ? ` · ${job.detail.model}` : "")
          + (job.detail.message ? ` — Google: ${job.detail.message}` : "")
        : job.duration ? t("step3s", { a: clock(job.processed), b: clock(job.duration) }) : clock(job.processed) },
    { k: "fin", title: job.options.summaryLang ? t("cs_summary") : t("step5"), sub: t("waiting") },
  ];
  const activeIdx = ["queued", "downloading", "uploading"].includes(job.status) ? 0 : job.status === "processing" ? 1 : job.status === "summarizing" ? 3 : 2;
  const segsTail = job.segments.slice(-8);

  return (
    <div className="wrap">
      <button className="row gap8 muted" style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }} onClick={() => go("/")}>
        <Icon name="chevl" sm />{t("back")}
      </button>
      <h1 style={{ fontSize: 32, marginBottom: 22 }}>{t("procT")}</h1>
      <div className="two">
        <div className="card" style={{ padding: 26 }}>
          <div className="row gap12">
            {s.type === "youtube" && s.videoId
              ? <img className="yt-thumb" src={youtubeThumb(s.videoId)} alt="" onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
              : <div className="ficon"><Icon name={s.type === "url" ? "link" : (s.mime || "").startsWith("video") ? "video" : "music"} /></div>}
            <div className="grow" style={{ minWidth: 0 }}>
              <div className="fname">{s.name}</div>
              <div className="fmeta">{t("l_" + job.options.language)} · {t("m_" + job.options.mode)}{job.duration ? ` · ${clock(job.duration)}` : ""} · Gemini</div>
            </div>
          </div>

          {failed || stopped ? (
            <>
              <div className={`note ${failed ? "err" : "warn"}`} style={{ marginTop: 20 }}>
                <Icon name="alert" sm />
                <span>
                  {failed ? errorText(t, job.error || "cloud_error") : job.status === "cancelled" ? t("cancelledT") : t("pausedT")}
                  {failed && job.errorDetail ? <small style={{ display: "block", marginTop: 6, opacity: 0.85 }}>Google: {job.errorDetail.slice(0, 300)}</small> : null}
                </span>
              </div>
              {job.segments.length > 0 && <div className="muted" style={{ fontSize: 13.5, marginTop: 10 }}>{t("savedPart", { a: clock(job.segments[job.segments.length - 1].end) })}</div>}
              {!hasKey ? <div className="card" style={{ padding: 16, marginTop: 16 }}><KeyBox compact onSaved={() => setHasKey(true)} /></div> : (
                <div className="row gap10 wrapf" style={{ marginTop: 18 }}>
                  <button className="btn btn-primary" onClick={resume}><Icon name="refresh" sm />{job.segments.length ? t("continueJob") : t("retry")}</button>
                  <button className="btn btn-ghost" onClick={async () => { await deleteCloudJob(id); go("/"); }}><Icon name="trash" sm />{t("del")}</button>
                </div>
              )}
            </>
          ) : (
            <>
              <div className="row sp" style={{ alignItems: "flex-end", margin: "24px 0 12px" }}>
                <div style={{ fontSize: 52, fontWeight: 800, letterSpacing: "-.03em", lineHeight: 1 }}>
                  {Math.floor(job.progress)}<span style={{ fontSize: ".5em", color: "var(--muted)" }}>%</span>
                </div>
                <StatusBadge status={job.status} />
              </div>
              <div className="pbar anim" role="progressbar" aria-valuenow={job.progress} aria-valuemin={0} aria-valuemax={100}>
                <i style={{ width: `${Math.max(2, job.progress)}%` }} />
              </div>
              <div className="steps" style={{ marginTop: 26 }}>
                {steps.map((st, i) => {
                  const d = i < activeIdx;
                  const act = i === activeIdx;
                  return (
                    <div key={st.k} className={`step${d ? " done" : act ? " act" : ""}`}>
                      <div className="sd">{d ? <Icon name="check" sm /> : act ? <span className="spin" /> : i + 1}</div>
                      <div><b>{st.title}</b><small>{d ? "✓" : st.sub}</small></div>
                    </div>
                  );
                })}
              </div>
              <div className="note info" style={{ marginTop: 22 }}><Icon name="info" sm /><span>{t("keepOpen")}</span></div>
              <button className="btn btn-ghost btn-block" style={{ marginTop: 16 }} onClick={() => cancelCloudJob(id)} disabled={!running}>
                <Icon name="x" sm />{t("cancel")}
              </button>
            </>
          )}
          {job.warnings.filter((w) => w !== "blob_not_saved").map((w) => <div key={w} className="note warn" style={{ marginTop: 14 }}><Icon name="info" sm /><span>{warningText(t, w)}</span></div>)}
        </div>

        <div className="card" style={{ padding: 24 }}>
          <div className="row sp" style={{ marginBottom: 14 }}>
            <div><h2>{t("live")}</h2><div className="muted" style={{ fontSize: 13, marginTop: 3 }}>{t("liveSc")}</div></div>
            {job.processed > 0 && <span className="badge b-q">{clock(job.processed)}{job.duration ? ` / ${clock(job.duration)}` : ""}</span>}
          </div>
          {segsTail.length === 0 && job.live.length === 0 ? (
            <p className="faint" style={{ fontSize: 14, padding: "12px 0" }}>{t("liveEmpty")}</p>
          ) : (
            <div className="segs">
              {segsTail.map((p, i) => <div className="sg" key={"s" + i}><span className="ts">{clock(p.start)}</span><p style={{ fontSize: 15 }}>{p.text}</p></div>)}
              {job.live.map((l, i) => {
                const [tm, tx] = l.split("\u0001");
                return <div className="sg live" key={"l" + i}><span className="ts">{tm.replace(/^00:/, "")}</span><p style={{ fontSize: 15 }}>{tx}</p></div>;
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
