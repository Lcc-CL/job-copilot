import { useDashboard, useFollowUps } from "../hooks/queries";
import { AlertTriangle, Calendar, ChevronRight, Loader2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import DetailDrawer from "../components/DetailDrawer";

const METRICS: { key: string; label: string }[] = [
  { key: "total_jobs", label: "Total Jobs" },
  { key: "greeting_ready", label: "Greeting Ready" },
  { key: "contacted", label: "Contacted" },
  { key: "applied", label: "Applied" },
  { key: "replied", label: "Replied" },
  { key: "interviews", label: "Interviews" },
  { key: "offers", label: "Offers" },
  { key: "due_today", label: "Due Today" },
  { key: "overdue", label: "Overdue" },
];

const STAGE_LABELS: Record<string, string> = {
  greeting_ready: "Greeting Ready",
  contacted: "Contacted",
  applied: "Applied",
  replied: "Replied",
  interviews: "Interviews",
  offers: "Offers",
  rejected: "Rejected",
};

function pct(n: number): string {
  return (n * 100).toFixed(1) + "%";
}

export default function Dashboard() {
  const dash = useDashboard();
  const fu = useFollowUps();
  const navigate = useNavigate();
  const [selectedAppId, setSelectedAppId] = useState<number | null>(null);

  const handleMetricClick = (key: string) => {
    const stageMap: Record<string, string> = {
      greeting_ready: "GREETING_READY",
      contacted: "CONTACTED",
      applied: "APPLIED",
      replied: "REPLIED",
      interviews: "INTERVIEW",
      offers: "OFFER",
    };
    const stage = stageMap[key];
    if (stage) {
      navigate(`/applications?stage=${stage}`);
    } else if (key === "due_today") {
      navigate("/follow-ups");
    } else if (key === "overdue") {
      navigate("/follow-ups");
    }
  };

  if (dash.isLoading && fu.isLoading) {
    return (
      <div className="loading-state">
        <Loader2 size={24} className="spin" /> Loading dashboard…
      </div>
    );
  }

  if (dash.isError || fu.isError) {
    return (
      <div className="error-state">
        <AlertTriangle size={24} />
        <p>Failed to load dashboard data.</p>
        <button className="btn btn-primary" onClick={() => { dash.refetch(); fu.refetch(); }}>
          Retry
        </button>
      </div>
    );
  }

  const d = dash.data!;
  const f = fu.data!;

  const chartData = Object.entries(STAGE_LABELS).map(([k, label]) => ({
    name: label,
    count: Number((d as unknown as Record<string, unknown>)[k]) || 0,
  }));

  const followUps = [...(f.due_today || []), ...(f.overdue || [])];

  return (
    <div>
      {/* Metric cards */}
      <div className="card-grid">
        {METRICS.map(({ key, label }) => (
          <div
            className="stat-card"
            key={key}
            onClick={() => handleMetricClick(key)}
            style={{ cursor: key !== "total_jobs" ? "pointer" : undefined }}
            title={key !== "total_jobs" ? `View ${label}` : undefined}
          >
            <div className="stat-card-label">{label}</div>
            <div className="stat-card-value">{Number((d as unknown as Record<string, unknown>)[key]) ?? 0}</div>
          </div>
        ))}
      </div>

      {/* Rates */}
      <div className="section" style={{ marginTop: 16 }}>
        <div className="section-title">Conversion Rates</div>
        <div className="rate-row">
          <span className="rate-label">Response Rate</span>
          <div className="rate-bar-bg">
            <div
              className="rate-bar-fg"
              style={{
                width: pct(d.response_rate),
                background:
                  d.response_rate >= 0.5
                    ? "var(--success)"
                    : d.response_rate >= 0.2
                      ? "var(--warning)"
                      : "var(--danger)",
              }}
            />
          </div>
          <span className="rate-value">{pct(d.response_rate)}</span>
        </div>
        <div className="rate-row">
          <span className="rate-label">Interview Rate</span>
          <div className="rate-bar-bg">
            <div
              className="rate-bar-fg"
              style={{
                width: pct(d.interview_rate),
                background:
                  d.interview_rate >= 0.3
                    ? "var(--success)"
                    : d.interview_rate >= 0.1
                      ? "var(--warning)"
                      : "var(--danger)",
              }}
            />
          </div>
          <span className="rate-value">{pct(d.interview_rate)}</span>
        </div>
      </div>

      {/* Stage chart */}
      <div className="section">
        <div className="section-title">Stage Distribution</div>
        {chartData.every((c) => c.count === 0) ? (
          <div className="empty-state" style={{ padding: 24 }}>
            <p>No application data yet. Start tracking applications to see the pipeline.</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData}>
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" fill="var(--primary)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Follow-ups */}
      <div className="section">
        <div className="section-title">
          <Calendar size={16} style={{ marginRight: 8 }} />
          Follow-ups
          {d.overdue > 0 && (
            <span className="badge badge-red" style={{ marginLeft: 8 }}>
              {d.overdue} overdue
            </span>
          )}
        </div>
        {followUps.length === 0 ? (
          <div className="empty-state" style={{ padding: 24 }}>
            <p>No follow-ups due. Great job!</p>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Company</th>
                <th>Position</th>
                <th>Stage</th>
                <th>Next Follow-up</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {followUps.map((a) => (
                <tr key={a.id} className="clickable" onClick={() => setSelectedAppId(a.id)}>
                  <td>{a.job_company || "—"}</td>
                  <td>{a.job_title || "—"}</td>
                  <td>
                    <span className={`badge badge-${stageColor(a.stage)}`}>{a.stage}</span>
                  </td>
                  <td>{a.next_follow_up_at ? fmtDate(a.next_follow_up_at) : "—"}</td>
                  <td>
                    <ChevronRight size={14} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selectedAppId !== null && (
        <DetailDrawer
          applicationId={selectedAppId}
          onClose={() => setSelectedAppId(null)}
        />
      )}
    </div>
  );
}

export function stageColor(stage: string): string {
  const map: Record<string, string> = {
    GREETING_READY: "blue",
    CONTACTED: "yellow",
    APPLIED: "blue",
    REPLIED: "yellow",
    INTERVIEW: "green",
    OFFER: "green",
    REJECTED: "red",
    WITHDRAWN: "gray",
    SHORTLISTED: "blue",
    DISCOVERED: "gray",
  };
  return map[stage] || "gray";
}

export function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso.slice(0, 10);
    return d.toLocaleDateString("zh-CN", {
      month: "short",
      day: "numeric",
      hour: d.getHours() !== 0 || d.getMinutes() !== 0 ? "2-digit" : undefined,
      minute: d.getHours() !== 0 || d.getMinutes() !== 0 ? "2-digit" : undefined,
    });
  } catch {
    return iso.slice(0, 10);
  }
}
