import { useState } from "react";
import { useFollowUps, useFollowUp } from "../hooks/queries";
import { AlertTriangle, Loader2, Calendar, ExternalLink, Check, Clock } from "lucide-react";
import { stageColor, fmtDate } from "./Dashboard";
import DetailDrawer from "../components/DetailDrawer";
import { addDays } from "date-fns";
import type { ApplicationDetail } from "../api/types";

function overdueDays(date: string): number {
  return Math.floor((Date.now() - new Date(date).getTime()) / 86400000);
}

export default function FollowUps() {
  const { data, isLoading, isError, refetch } = useFollowUps();
  const followUp = useFollowUp();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [actionId, setActionId] = useState<number | null>(null);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);

  const showToast = (text: string, type: "success" | "error") => {
    setMessage({ text, type });
    setTimeout(() => setMessage(null), 3000);
  };

  const handleQuickAction = async (app: ApplicationDetail, action: "done" | "delay1" | "delay3" | "delay7") => {
    setActionId(app.id);
    let nextFollowUpAt: string | null = null;
    let stage: string | undefined;

    if (action === "done") {
      stage = "APPLIED";
    } else {
      const days = action === "delay1" ? 1 : action === "delay3" ? 3 : 7;
      nextFollowUpAt = addDays(new Date(), days).toISOString();
    }

    try {
      await followUp.mutateAsync({
        id: app.id,
        body: { content: `Quick action: ${action}`, next_follow_up_at: nextFollowUpAt, stage },
      });
      showToast(`Follow-up ${action}`, "success");
    } catch {
      showToast("Action failed", "error");
    } finally {
      setActionId(null);
    }
  };

  if (isLoading) return <div className="loading-state"><Loader2 size={24} /> Loading…</div>;
  if (isError) return (
    <div className="error-state"><AlertTriangle size={24} /><p>Failed</p>
      <button className="btn btn-primary btn-sm" onClick={() => refetch()}>Retry</button>
    </div>
  );

  const f = data!;
  const sections = [
    { key: "overdue", label: "Overdue", items: f.overdue, icon: <AlertTriangle size={14} color="var(--danger)" /> },
    { key: "due_today", label: "Due Today", items: f.due_today, icon: <Calendar size={14} color="var(--primary)" /> },
    { key: "upcoming", label: "Next 7 Days", items: f.upcoming, icon: <Clock size={14} color="var(--warning)" /> },
  ];

  return (
    <div>
      {sections.map((sec) => (
        <div className="section" key={sec.key}>
          <div className="section-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {sec.icon}
            {sec.label}
            <span style={{ fontWeight: 400, color: "var(--text-secondary)", fontSize: 13 }}>
              ({sec.items.length})
            </span>
          </div>
          {sec.items.length === 0 ? (
            <div className="empty-state" style={{ padding: 16 }}>
              <p style={{ fontSize: 12 }}>No items.</p>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Company</th><th>Position</th><th>Stage</th>
                  <th>Last Contact</th><th>Next Follow-up</th><th>Overdue</th>
                  <th>Link</th><th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sec.items.map((a) => (
                  <tr key={a.id}>
                    <td style={{ fontWeight: 500 }}>{a.job_company || "—"}</td>
                    <td style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {a.job_title || "—"}
                    </td>
                    <td><span className={`badge badge-${stageColor(a.stage)}`}>{a.stage}</span></td>
                    <td>{fmtDate(a.last_contact_at)}</td>
                    <td>{fmtDate(a.next_follow_up_at)}</td>
                    <td style={{ color: "var(--danger)", fontWeight: 600 }}>
                      {a.next_follow_up_at && new Date(a.next_follow_up_at) < new Date()
                        ? `${overdueDays(a.next_follow_up_at)}d`
                        : "—"}
                    </td>
                    <td>
                      {a.job_url && (
                        <a href={a.job_url} target="_blank" rel="noopener noreferrer">
                          <ExternalLink size={14} />
                        </a>
                      )}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                        <button
                          className="btn btn-sm"
                          style={{ background: "var(--success-light)", color: "var(--success)", border: "none" }}
                          onClick={() => handleQuickAction(a, "done")}
                          disabled={actionId === a.id}
                        >
                          <Check size={12} /> Done
                        </button>
                        <button className="btn btn-secondary btn-sm" onClick={() => handleQuickAction(a, "delay1")} disabled={actionId === a.id}>
                          +1d
                        </button>
                        <button className="btn btn-secondary btn-sm" onClick={() => handleQuickAction(a, "delay3")} disabled={actionId === a.id}>
                          +3d
                        </button>
                        <button className="btn btn-secondary btn-sm" onClick={() => handleQuickAction(a, "delay7")} disabled={actionId === a.id}>
                          +7d
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={() => setSelectedId(a.id)}>
                          Detail
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}

      {selectedId !== null && (
        <DetailDrawer applicationId={selectedId} onClose={() => setSelectedId(null)} />
      )}
      {message && <div className={`toast toast-${message.type}`}>{message.text}</div>}
    </div>
  );
}
