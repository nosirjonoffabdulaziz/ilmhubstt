import React, { createContext, useContext } from "react";
import type { Config } from "../services/api";
import type { Prefs } from "../services/storage";
import type { Lang, T } from "../i18n";
import { Icon, Logo } from "./Icons";

export interface Ctx {
  t: T;
  prefs: Prefs;
  setPrefs: (p: Partial<Prefs>) => void;
  config: Config | null;
  configError: string | null;
  route: string;
  go: (path: string) => void;
  toast: (msg: string) => void;
  askKey: () => void;
  reloadConfig: () => void;
  dark: boolean;
}
export const AppCtx = createContext<Ctx>(null as any);
export const useApp = () => useContext(AppCtx);

export function Header() {
  const { t, prefs, setPrefs, route, go, dark } = useApp();
  const items: [string, string, string][] = [["/", "mic", t("nav_home")], ["/history", "history", t("nav_history")], ["/settings", "sliders", t("nav_settings")]];
  const active = route.startsWith("/history") ? "/history" : route.startsWith("/settings") ? "/settings" : "/";
  return (
    <header className="hdr">
      <a className="brand" href="#/" onClick={(e) => { e.preventDefault(); go("/"); }}>
        <Logo />
        <div><b>ilmhubstt</b><small>{t("tag")}</small></div>
      </a>
      <nav className="nav">
        {items.map(([p, ic, label]) => (
          <a key={p} href={"#" + p} className={active === p ? "on" : ""} onClick={(e) => { e.preventDefault(); go(p); }}>
            <Icon name={ic} sm />{label}
          </a>
        ))}
      </nav>
      <div className="row gap8">
        <div className="lang" role="group" aria-label="Language">
          {(["uz", "ru", "en"] as Lang[]).map((l) => (
            <button key={l} className={prefs.lang === l ? "on" : ""} onClick={() => setPrefs({ lang: l })} aria-pressed={prefs.lang === l}>
              {l.toUpperCase()}
            </button>
          ))}
        </div>
        <button className="icon-btn" aria-label={t("theme")} title={t("theme")}
          onClick={() => setPrefs({ theme: dark ? "light" : "dark" })}>
          <Icon name={dark ? "sun" : "moon"} />
        </button>
      </div>
    </header>
  );
}

export function BottomNav() {
  const { t, route, go } = useApp();
  const items: [string, string, string][] = [["/", "home", t("navm_home")], ["/history", "history", t("nav_history")], ["/settings", "sliders", t("nav_settings")]];
  const active = route.startsWith("/history") ? "/history" : route.startsWith("/settings") ? "/settings" : "/";
  return (
    <nav className="bnav">
      {items.map(([p, ic, label]) => (
        <a key={p} href={"#" + p} className={active === p ? "on" : ""} onClick={(e) => { e.preventDefault(); go(p); }}>
          <span className="ib"><Icon name={ic} /></span>{label}
        </a>
      ))}
    </nav>
  );
}

export function StatusBadge({ status, progress }: { status: string; progress?: number }) {
  const { t } = useApp();
  if (status === "completed") return <span className="badge b-ok"><span className="dot" />{t("st_completed")}</span>;
  if (status === "failed") return <span className="badge b-err"><Icon name="alert" sm />{t("st_failed")}</span>;
  if (status === "cancelled") return <span className="badge b-q">{t("st_cancelled")}</span>;
  if (status === "expired") return <span className="badge b-q">—</span>;
  if (status === "paused") return <span className="badge b-q"><Icon name="pause" sm />{t("st_paused")}{progress != null ? ` ${Math.floor(progress)}%` : ""}</span>;
  if (status === "queued") return <span className="badge b-q"><Icon name="clock" sm />{t("st_queued")}</span>;
  return (
    <span className="badge b-run"><span className="spin sm" />{t("st_" + status)}{progress != null ? ` ${Math.floor(progress)}%` : ""}</span>
  );
}
