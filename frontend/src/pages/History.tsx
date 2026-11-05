import React, { useEffect, useState } from "react";
import { useApp, StatusBadge } from "../components/Layout";
import { Icon } from "../components/Icons";
import { api, ApiError } from "../services/api";
import { HistoryItem, loadHistory, removeHistory, upsertHistory } from "../services/storage";
import { clock } from "../hooks/format";
import { historyIcon, historyPath } from "./Home";
import { deleteCloudJob } from "../services/cloud";

const ACTIVE = ["queued", "converting", "transcribing", "normalizing"];

export default function HistoryPage() {
  const { t, go, config } = useApp();
  const [list, setList] = useState<HistoryItem[]>(loadHistory);

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      for (const h of loadHistory().filter((x) => x.kind !== "cloud" && x.status !== "expired" && (ACTIVE.includes(x.status) || x.status === "completed"))) {
        try {
          const j = await api.job(h.id, h.token);
          upsertHistory({ id: h.id, status: j.status, progress: j.progress });
        } catch (e) {
          if ((e as ApiError).code === "not_found") upsertHistory({ id: h.id, status: "expired" });
        }
      }
      if (alive) setList(loadHistory());
    };
    refresh();
    const iv = window.setInterval(refresh, 4000);
    return () => { alive = false; window.clearInterval(iv); };
  }, []);

  async function del(h: HistoryItem) {
    if (h.kind === "cloud") { await deleteCloudJob(h.id); setList(loadHistory()); return; }
    try { await api.remove(h.id, h.token); } catch { /* muddati o'tgan bo'lishi mumkin */ }
    setList(removeHistory(h.id));
  }

  return (
    <div className="wrap" style={{ maxWidth: 980 }}>
      <h1 style={{ fontSize: 30, marginBottom: 8 }}>{t("histT")}</h1>
      <p className="muted" style={{ fontSize: 14, marginBottom: 20 }}>{__STATIC__ ? t("histNoteB") : t("histNote", { h: config?.retention_hours ?? 24 })}</p>
      {list.length === 0 ? (
        <div className="card empty">
          <div className="ficon" style={{ margin: "0 auto 14px" }}><Icon name="history" /></div>
          <p style={{ marginBottom: 16 }}>{t("histEmpty")}</p>
          <button className="btn btn-primary" onClick={() => go("/")}><Icon name="upload" sm />{t("choose")}</button>
        </div>
      ) : (
        <div className="card" style={{ padding: 6 }}>
          {list.map((h, i) => (
            <div key={h.id} className="row gap12" style={{ padding: "12px 12px", borderTop: i ? "1px solid var(--border)" : 0 }}>
              <div className="ficon" style={{ width: 40, height: 40, borderRadius: 11 }}><Icon name={historyIcon(h)} sm /></div>
              <button className="grow" style={{ textAlign: "left" }} onClick={() => h.status !== "expired" && go(historyPath(h))} disabled={h.status === "expired"}>
                <div className="fname">{h.filename}</div>
                <div className="fmeta">
                  <span>{t("l_" + h.language)}</span><span>·</span><span>{clock(h.duration)}</span><span>·</span>
                  <span>{new Date(h.created).toLocaleString()}</span>
                </div>
              </button>
              <StatusBadge status={h.status} progress={(ACTIVE.includes(h.status) || h.kind === "cloud") && !["queued", "completed", "failed", "cancelled"].includes(h.status) ? h.progress : undefined} />
              <button className="icon-btn" aria-label={t("remove")} title={t("remove")} onClick={() => del(h)}><Icon name="trash" sm /></button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
