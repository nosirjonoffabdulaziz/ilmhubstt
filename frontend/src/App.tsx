import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AppCtx, BottomNav, Ctx, Header } from "./components/Layout";
import { Icon } from "./components/Icons";
import { translator, errorText } from "./i18n";
import { api, ApiError, Config, getAccessKey, setAccessKey } from "./services/api";
import { loadPrefs, Prefs, savePrefs } from "./services/storage";
import HomePage from "./pages/Home";
import JobPage from "./pages/Job";
import HistoryPage from "./pages/History";
import SettingsPage from "./pages/Settings";
import CloudJobPage from "./pages/CloudJob";
import { anyRunning } from "./services/cloud";

function currentRoute(): string {
  const h = window.location.hash.replace(/^#/, "");
  return h || "/";
}

export default function App() {
  const [prefs, setPrefsState] = useState<Prefs>(loadPrefs);
  const [route, setRoute] = useState(currentRoute);
  const [config, setConfig] = useState<Config | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const [keyOpen, setKeyOpen] = useState(false);
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false);

  const t = useMemo(() => translator(prefs.lang), [prefs.lang]);
  const dark = prefs.theme === "dark" || (prefs.theme === "system" && systemDark);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#10182C" : "#FFFFFF");
  }, [dark]);
  useEffect(() => { document.documentElement.lang = prefs.lang; }, [prefs.lang]);
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const fn = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener?.("change", fn);
    return () => mq.removeEventListener?.("change", fn);
  }, []);
  useEffect(() => {
    const fn = () => { setRoute(currentRoute()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", fn);
    return () => window.removeEventListener("hashchange", fn);
  }, []);

  // brauzerda ish ketayotganda sahifani yopishdan ogohlantirish
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (anyRunning()) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  const loadConfig = useCallback(() => {
    if (__STATIC__) return;
    api.config().then((c) => {
      setConfig(c);
      setConfigError(null);
      if (c.requires_access_key && !getAccessKey()) setKeyOpen(true);
    }).catch((e: ApiError) => setConfigError(e.code || "network"));
  }, []);
  useEffect(loadConfig, [loadConfig]);

  const setPrefs = useCallback((p: Partial<Prefs>) => {
    setPrefsState((old) => { const n = { ...old, ...p }; savePrefs(n); return n; });
  }, []);
  const go = useCallback((path: string) => { window.location.hash = path; }, []);
  const toast = useCallback((msg: string) => {
    setToastMsg(msg);
    window.setTimeout(() => setToastMsg((m) => (m === msg ? null : m)), 2600);
  }, []);

  const ctx: Ctx = { t, prefs, setPrefs, config, configError, route, go, toast, askKey: () => setKeyOpen(true), reloadConfig: loadConfig, dark };

  let page: React.ReactNode;
  const m = route.match(/^\/job\/([0-9a-f]{32})$/);
  const mc = route.match(/^\/c\/([0-9a-f]{32})$/);
  if (m) page = <JobPage key={m[1]} id={m[1]} />;
  else if (mc) page = <CloudJobPage key={mc[1]} id={mc[1]} />;
  else if (route.startsWith("/history")) page = <HistoryPage />;
  else if (route.startsWith("/settings")) page = <SettingsPage />;
  else page = <HomePage />;

  const demoOnly = config && !config.engines.some((e) => e.available && e.id !== "dummy");

  return (
    <AppCtx.Provider value={ctx}>
      <Header />
      {demoOnly && <div className="demo-banner">{t("demoBanner")}</div>}
      {configError && (
        <div className="wrap" style={{ paddingBottom: 0 }}>
          <div className="note err"><Icon name="alert" sm /><span>{errorText(t, configError)}</span>
            <button className="btn btn-ghost" style={{ marginLeft: "auto", minHeight: 34 }} onClick={loadConfig}><Icon name="refresh" sm /></button>
          </div>
        </div>
      )}
      <main>{page}</main>
      <BottomNav />
      {toastMsg && <div className="toast" role="status">{toastMsg}</div>}
      {keyOpen && <KeyModal t={t} onClose={() => { setKeyOpen(false); loadConfig(); }} />}
    </AppCtx.Provider>
  );
}

function KeyModal({ t, onClose }: { t: (k: string) => string; onClose: () => void }) {
  const [val, setVal] = useState(getAccessKey());
  return (
    <div className="modal-bg" role="dialog" aria-modal="true">
      <form className="card modal" onSubmit={(e) => { e.preventDefault(); setAccessKey(val.trim()); onClose(); }}>
        <div className="ficon" style={{ marginBottom: 14 }}><Icon name="key" /></div>
        <h2 style={{ marginBottom: 6 }}>{t("keyT")}</h2>
        <p className="muted" style={{ fontSize: 14, marginBottom: 16 }}>{t("keyS")}</p>
        <input className="input" type="password" autoFocus value={val} onChange={(e) => setVal(e.target.value)} placeholder={t("accessKey")} />
        <div className="row gap8" style={{ marginTop: 16 }}>
          <button type="button" className="btn btn-ghost" onClick={onClose}>✕</button>
          <button type="submit" className="btn btn-primary grow">{t("save")}</button>
        </div>
      </form>
    </div>
  );
}
