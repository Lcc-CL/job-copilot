import { createContext, useContext, useState, useEffect, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { ApiError, request } from "../api/client";

interface AuthCtx {
  user: string | null;
  loading: boolean;
  authErrorCode: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  invalidateSession: () => void;
}

const AuthContext = createContext<AuthCtx>({
  user: null, loading: true, authErrorCode: null,
  login: async () => {}, logout: async () => {}, refreshUser: async () => {},
  invalidateSession: () => {},
});

export function useAuth() { return useContext(AuthContext); }

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [authErrorCode, setAuthErrorCode] = useState<string | null>(null);

  const checkAuth = async () => {
    try {
      const r = await request<{ username: string }>("/auth/me");
      setUser(r.username);
      setAuthErrorCode(null);
    } catch (error: unknown) {
      setUser(null);
      if (error instanceof ApiError && error.code === "SESSION_INVALID") {
        setAuthErrorCode(error.code);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { checkAuth(); }, []);

  // Handle 401 globally
  useEffect(() => {
    const orig = window.fetch;
    window.fetch = async (...args) => {
      const res = await orig(...args);
      if (
        res.status === 401
        && !res.url.includes("/auth/me")
        && !res.url.includes("/auth/login")
      ) {
        const payload = await res.clone().json().catch(() => null) as {
          detail?: { code?: string };
        } | null;
        setUser(null);
        setAuthErrorCode(payload?.detail?.code || "SESSION_INVALID");
      }
      return res;
    };
    return () => { window.fetch = orig; };
  }, []);

  const login = async (username: string, password: string) => {
    const result = await request<{ username: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setUser(result.username);
    setAuthErrorCode(null);
  };

  const logout = async () => {
    try {
      await request("/auth/logout", { method: "POST" });
    } catch {}
    setUser(null);
    setAuthErrorCode(null);
  };

  const invalidateSession = () => {
    setUser(null);
    setAuthErrorCode(null);
  };

  return (
    <AuthContext.Provider value={{
      user,
      loading,
      authErrorCode,
      login,
      logout,
      refreshUser: checkAuth,
      invalidateSession,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <div style={{display:"flex",alignItems:"center",justifyContent:"center",minHeight:"100vh",background:"var(--bg,#f8f9fb)",color:"var(--text-secondary,#6b7280)",fontSize:14}}>Job Copilot</div>;
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  return <>{children}</>;
}
