import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../components/AuthProvider";
import { ListChecks, Loader2, AlertTriangle, WifiOff } from "lucide-react";

export default function Login() {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const loc = useLocation();
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [offline, setOffline] = useState(false);

  if (user) {
    const to = (loc.state as { from?: string })?.from || "/";
    navigate(to, { replace: true });
    return null;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) return;
    setLoading(true);
    setError("");
    setOffline(false);
    try {
      await login(username, password);
      const to = (loc.state as { from?: string })?.from || "/";
      navigate(to, { replace: true });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Login failed";
      if (msg.includes("NetworkError") || msg.includes("Failed to fetch")) {
        setOffline(true);
      } else {
        setError(msg.includes("401") ? t("login.invalidCredentials") : msg);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
      background: "var(--bg)",
    }}>
      <div style={{
        background: "var(--surface)", borderRadius: 12, padding: 32,
        boxShadow: "var(--shadow)", width: 360, maxWidth: "90vw",
      }}>
        <div style={{ textAlign: "center", marginBottom: 24 }}>
          <ListChecks size={28} color="var(--primary)" style={{ marginBottom: 8 }} />
          <h1 style={{ fontSize: 20, fontWeight: 700 }}>{t("login.title")}</h1>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 4 }}>
            {t("login.subtitle")}
          </p>
        </div>

        {offline && (
          <div style={{
            background: "var(--danger-light)", borderRadius: 8, padding: 12, marginBottom: 16,
            display: "flex", alignItems: "center", gap: 8, fontSize: 13,
          }}>
            <WifiOff size={16} color="var(--danger)" />
            {t("login.apiUnavailable")}
          </div>
        )}

        {error && (
          <div style={{
            background: "var(--danger-light)", borderRadius: 8, padding: 12, marginBottom: 16,
            fontSize: 13, color: "var(--danger)",
          }}>
            <AlertTriangle size={14} style={{ marginRight: 6 }} />
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>{t("login.username")}</label>
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          </div>
          <div className="form-group">
            <label>{t("login.password")}</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading || !username || !password}
            style={{ width: "100%", marginTop: 8, justifyContent: "center" }}
          >
            {loading ? <Loader2 size={16} /> : t("login.signIn")}
          </button>
        </form>
      </div>
    </div>
  );
}
