import { NavLink, Outlet } from "react-router-dom";
import { LayoutDashboard, ListChecks, RefreshCw, Wifi, WifiOff } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { fetchDashboard } from "../api/client";

export default function Layout() {
  const qc = useQueryClient();
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
            Dashboard
          </NavLink>
          <NavLink to="/applications">
            <ListChecks size={16} />
            Applications
          </NavLink>
        </nav>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <div className="topbar-left">
            <span style={{ color: "var(--text-secondary)", fontWeight: 400, fontSize: 14 }}>
              {window.location.pathname === "/applications"
                ? "Applications"
                : "Dashboard"}
            </span>
          </div>
          <div className="topbar-right">
            {online ? (
              <Wifi size={14} color="var(--success)" />
            ) : (
              <WifiOff size={14} color="var(--danger)" />
            )}
            <span>{online ? "API Online" : "API Offline"}</span>
            <span>Updated {ts.toLocaleTimeString()}</span>
            <button className="btn btn-ghost btn-sm" onClick={handleRefresh}>
              <RefreshCw size={14} /> Refresh
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
