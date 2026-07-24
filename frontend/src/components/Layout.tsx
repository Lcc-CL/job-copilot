import { NavLink, Outlet, useLocation } from "react-router-dom";
import { LayoutDashboard, ListChecks, RefreshCw, Wifi, WifiOff, Database, CalendarCheck, LogOut } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { fetchDashboard } from "../api/client";
import { useAuth } from "./AuthProvider";

const PAGE_TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/applications": "Applications",
  "/job-pool": "Job Pool",
  "/follow-ups": "Follow-ups",
};

export default function Layout() {
  const qc = useQueryClient();
  const loc = useLocation();
  const { user, logout } = useAuth();
  const { t, i18n } = useTranslation();
  const [ts, setTs] = useState(new Date());
  const [online, setOnline] = useState(true);

  useEffect(() => {
    const check = () => {
      fetchDashboard()
        .then(() => setOnline(true))
        .catch(() => setOnline(false));
    };
    check();
    const iv = setInterval(check, 30_000);
    return () => clearInterval(iv);
  }, []);

  const handleRefresh = () => {
    qc.invalidateQueries();
    setTs(new Date());
  };

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <ListChecks size={20} color="var(--primary)" />
          Job Copilot
        </div>
        <nav className="sidebar-nav">
          <NavLink to="/" end>
            <LayoutDashboard size={16} />
            {t("nav.dashboard")}
          </NavLink>
          <NavLink to="/job-pool">
            <Database size={16} />
            {t("nav.jobPool")}
          </NavLink>
          <NavLink to="/applications">
            <ListChecks size={16} />
            {t("nav.applications")}
          </NavLink>
          <NavLink to="/follow-ups">
            <CalendarCheck size={16} />
            {t("nav.followUps")}
          </NavLink>
        </nav>
        <div style={{ padding: "12px", borderTop: "1px solid var(--border)", fontSize: 12 }}>
          <div style={{ color: "var(--text-secondary)", marginBottom: 6 }}>{user || "—"}</div>
          <button
            onClick={logout}
            style={{
              background: "none", border: "none", cursor: "pointer",
              display: "flex", alignItems: "center", gap: 6,
              color: "var(--text-secondary)", fontSize: 12, padding: 0,
            }}
          >
            <LogOut size={14} /> {t("nav.signOut")}
          </button>
        </div>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <div className="topbar-left">
            <span style={{ color: "var(--text-secondary)", fontWeight: 400, fontSize: 14 }}>
              {PAGE_TITLES[loc.pathname] || "Job Copilot"}
            </span>
          </div>
          <div className="topbar-right">
            <div style={{ display: "flex", gap: 2, fontSize: 12, fontWeight: 500 }}>
              <button
                onClick={() => i18n.changeLanguage("zh-CN")}
                style={{
                  background: i18n.language === "zh-CN" ? "var(--primary)" : "none",
                  color: i18n.language === "zh-CN" ? "white" : "var(--text-secondary)",
                  border: "none", borderRadius: 4, padding: "2px 6px", cursor: "pointer", fontSize: 11,
                }}
              >中文</button>
              <button
                onClick={() => i18n.changeLanguage("en-US")}
                style={{
                  background: i18n.language === "en-US" ? "var(--primary)" : "none",
                  color: i18n.language === "en-US" ? "white" : "var(--text-secondary)",
                  border: "none", borderRadius: 4, padding: "2px 6px", cursor: "pointer", fontSize: 11,
                }}
              >EN</button>
            </div>
            {online ? (
              <Wifi size={14} color="var(--success)" />
            ) : (
              <WifiOff size={14} color="var(--danger)" />
            )}
            <span>{online ? t("common.apiOnline") : t("common.apiOffline")}</span>
            <span>{t("common.updated")} {ts.toLocaleTimeString()}</span>
            <button className="btn btn-ghost btn-sm" onClick={handleRefresh}>
              <RefreshCw size={14} /> {t("common.refresh")}
            </button>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
