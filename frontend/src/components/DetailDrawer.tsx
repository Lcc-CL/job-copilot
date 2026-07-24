import { useState, useEffect } from "react";
import { useApplication, useUpdateApplication } from "../hooks/queries";
import {
  X, Loader2, AlertTriangle, Copy, Check, ExternalLink,
  Save, Edit3,
} from "lucide-react";
import { stageColor, fmtDate } from "../pages/Dashboard";
import ResumeTailor from "./ResumeTailor";
import { updateJob } from "../api/client";
import type { ApplicationUpdate } from "../api/types";

const STAGES = [
  "DISCOVERED", "SHORTLISTED", "GREETING_READY", "CONTACTED",
  "APPLIED", "REPLIED", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN",
];

interface Props {
  applicationId: number;
  onClose: () => void;
}

export default function DetailDrawer({ applicationId, onClose }: Props) {
  const { data, isLoading, isError, refetch } = useApplication(applicationId);
  const updateMutation = useUpdateApplication();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<ApplicationUpdate>({});
  const [toast, setToast] = useState<{ type: "success" | "error"; msg: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [jdEditing, setJdEditing] = useState(false);
  const [jdText, setJdText] = useState("");
  const [jdSaving, setJdSaving] = useState(false);
  const [jdLen, setJdLen] = useState(0);

  useEffect(() => {
    if (data) {
      fetch(`/api/jobs/${data.job_pk}`, { credentials: "include" })
        .then(r => r.json()).then(j => {
          setJdLen((j.jd_text || "").length);
          setJdText(j.jd_text || "");
        }).catch(() => {});
    }
  }, [data]);

  async function handleJdSave() {
    if (!data) return;
    setJdSaving(true);
    try {
      await updateJob(data.job_pk, { jd_text: jdText });
      setJdLen(jdText.length);
      setJdEditing(false);
      showToast("success", "JD saved");
    } catch { showToast("error", "Failed to save JD"); }
    finally { setJdSaving(false); }
  }

  useEffect(() => {
    if (data) {
      setForm({
        stage: data.stage,
        priority: data.priority || "",
        channel: data.channel || "",
        resume_version: data.resume_version || "",
        next_follow_up_at: data.next_follow_up_at || "",
        notes: data.notes || "",
      });
    }
  }, [data]);

  // Refetch when drawer opens to get latest events
  useEffect(() => {
    refetch();
  }, [applicationId, refetch]);

  const showToast = (type: "success" | "error", msg: string) => {
    setToast({ type, msg });
    setTimeout(() => setToast(null), 3000);
  };

  const handleSave = async () => {
    const body: ApplicationUpdate = {};
    for (const [k, v] of Object.entries(form)) {
      if (v === "" || v === null || v === undefined) {
        (body as Record<string, string | null>)[k] = null;
      } else {
        (body as Record<string, string>)[k] = v as string;
      }
    }
    try {
      await updateMutation.mutateAsync({ id: applicationId, body });
      showToast("success", "Saved successfully");
      setEditing(false);
      refetch();
    } catch {
      showToast("error", "Failed to save. Please try again.");
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleEsc = (e: KeyboardEvent) => {
    if (e.key === "Escape") onClose();
  };

  useEffect(() => {
    document.addEventListener("keydown", handleEsc);
    return () => document.removeEventListener("keydown", handleEsc);
  }, []);

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <div className="drawer">
        <div className="drawer-header">
          <h2>{data?.job_title || `Application #${applicationId}`}</h2>
          <button className="drawer-close" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="drawer-body">
          {isLoading ? (
            <div className="loading-state"><Loader2 size={20} /> Loading…</div>
          ) : isError ? (
            <div className="error-state">
              <AlertTriangle size={20} />
              <p>Failed to load details.</p>
              <button className="btn btn-primary btn-sm" onClick={() => refetch()}>Retry</button>
            </div>
          ) : data ? (
            <>
              {/* Job Section */}
              <div className="drawer-section">
                <h3>Position</h3>
                <Field label="Title" value={data.job_title} />
                <Field label="Company" value={data.job_company} />
                <Field label="Location" value={data.job_city} />
                <Field label="Salary" value={data.job_salary_text} />
                <Field label="JD Status" value={data.job_jd_status} />
                <div style={{ marginTop: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)" }}>
                      JD Text ({jdLen} chars)
                    </span>
                    {!jdEditing ? (
                      <button className="btn btn-ghost btn-sm" onClick={() => setJdEditing(true)}>
                        <Edit3 size={12} /> Edit
                      </button>
                    ) : (
                      <div style={{ display: "flex", gap: 4 }}>
                        <button className="btn btn-secondary btn-sm" onClick={() => setJdEditing(false)}>Cancel</button>
                        <button className="btn btn-primary btn-sm" onClick={handleJdSave} disabled={jdSaving}>
                          {jdSaving ? <Loader2 size={12} /> : <Save size={12} />} Save
                        </button>
                      </div>
                    )}
                  </div>
                  {jdEditing ? (
                    <textarea
                      value={jdText}
                      onChange={(e) => setJdText(e.target.value)}
                      style={{ width: "100%", minHeight: 120, padding: 8, border: "1px solid var(--border)", borderRadius: 6, fontSize: 12, fontFamily: "inherit" }}
                      placeholder="Paste full job description here (responsibilities + requirements)..."
                    />
                  ) : (
                    <div style={{ fontSize: 12, color: jdLen > 0 ? "var(--text-secondary)" : "var(--danger)", maxHeight: 80, overflow: "auto", whiteSpace: "pre-wrap" }}>
                      {jdLen > 0 ? (jdText || "").slice(0, 300) + (jdLen > 300 ? "..." : "") : "No JD text. Click Edit to paste job description."}
                    </div>
                  )}
                </div>
                <Field label="Original Score" value={data.job_original_score} />
                <Field label="Enriched Score" value={data.job_enriched_score} />
                <Field
                  label="Recommendation"
                  value={data.job_recommendation}
                  badge={data.job_recommendation ? recBadge(data.job_recommendation) : undefined}
                />
                {data.job_url && (
                  <div className="drawer-field">
                    <span className="drawer-field-label">Job URL</span>
                    <a href={data.job_url} target="_blank" rel="noopener noreferrer">
                      Open <ExternalLink size={12} style={{ display: "inline" }} />
                    </a>
                  </div>
                )}
                {data.job_greeting_text && (
                  <div className="drawer-field" style={{ flexDirection: "column", alignItems: "flex-start" }}>
                    <span className="drawer-field-label">Greeting</span>
                    <span style={{ fontSize: 12, marginTop: 4, lineHeight: 1.6, color: "var(--text-secondary)" }}>
                      {data.job_greeting_text}
                    </span>
                    <button className="copy-btn" onClick={() => handleCopy(data.job_greeting_text!)}>
                      {copied ? <Check size={12} /> : <Copy size={12} />}
                      {copied ? " Copied" : " Copy"}
                    </button>
                  </div>
                )}
              </div>

              {/* Application Section */}
              <div className="drawer-section">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <h3>Application</h3>
                  {!editing ? (
                    <button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)}>
                      <Edit3 size={14} /> Edit
                    </button>
                  ) : (
                    <div style={{ display: "flex", gap: 8 }}>
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => { setEditing(false); }}
                        disabled={updateMutation.isPending}
                      >
                        Cancel
                      </button>
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={handleSave}
                        disabled={updateMutation.isPending}
                      >
                        {updateMutation.isPending ? (
                          <><Loader2 size={14} /> Saving…</>
                        ) : (
                          <><Save size={14} /> Save</>
                        )}
                      </button>
                    </div>
                  )}
                </div>
                {editing ? (
                  <>
                    <FormGroup label="Stage">
                      <select
                        value={form.stage || ""}
                        onChange={(e) => setForm({ ...form, stage: e.target.value })}
                      >
                        {STAGES.map((s) => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </select>
                    </FormGroup>
                    <FormGroup label="Priority">
                      <input
                        value={form.priority || ""}
                        onChange={(e) => setForm({ ...form, priority: e.target.value })}
                        placeholder="e.g. 冲刺/稳妥/保底"
                      />
                    </FormGroup>
                    <FormGroup label="Channel">
                      <input
                        value={form.channel || ""}
                        onChange={(e) => setForm({ ...form, channel: e.target.value })}
                      />
                    </FormGroup>
                    <FormGroup label="Resume Version">
                      <input
                        value={form.resume_version || ""}
                        onChange={(e) => setForm({ ...form, resume_version: e.target.value })}
                      />
                    </FormGroup>
                    <FormGroup label="Next Follow-up">
                      <input
                        type="datetime-local"
                        value={toDatetimeLocal(form.next_follow_up_at)}
                        onChange={(e) => setForm({ ...form, next_follow_up_at: e.target.value || null })}
                      />
                    </FormGroup>
                    <FormGroup label="Notes">
                      <textarea
                        value={form.notes || ""}
                        onChange={(e) => setForm({ ...form, notes: e.target.value })}
                        placeholder="Private notes about this application…"
                      />
                    </FormGroup>
                  </>
                ) : (
                  <>
                    <Field
                      label="Stage"
                      value={data.stage}
                      badge={stageBadge(data.stage)}
                    />
                    <Field label="Priority" value={data.priority} />
                    <Field label="Channel" value={data.channel} />
                    <Field label="Resume Version" value={data.resume_version} />
                    <Field label="Applied At" value={fmtDate(data.applied_at)} />
                    <Field label="Last Contact" value={fmtDate(data.last_contact_at)} />
                    <Field
                      label="Next Follow-up"
                      value={fmtDate(data.next_follow_up_at)}
                      style={isOverdue(data.next_follow_up_at) ? { color: "var(--danger)", fontWeight: 600 } : undefined}
                    />
                    {data.notes && (
                      <div className="drawer-field" style={{ flexDirection: "column", alignItems: "flex-start" }}>
                        <span className="drawer-field-label">Notes</span>
                        <span style={{ fontSize: 12, marginTop: 4, whiteSpace: "pre-wrap" }}>
                          {data.notes}
                        </span>
                      </div>
                    )}
                  </>
                )}
              </div>

              {/* Resume Tailor */}
              <ResumeTailor applicationId={applicationId} />

              {/* Events Timeline */}
              <div className="drawer-section">
                <h3>Timeline</h3>
                {data.events.length === 0 ? (
                  <div className="empty-state" style={{ padding: 16 }}>
                    <p style={{ fontSize: 12 }}>No events recorded yet.</p>
                  </div>
                ) : (
                  <div className="timeline">
                    {[...data.events].reverse().map((evt) => (
                      <div className="timeline-item" key={evt.id}>
                        <div className="timeline-event">
                          {evt.event_type === "stage_change" ? (
                            <span>
                              {evt.from_stage || "start"} → {evt.to_stage || "?"}
                            </span>
                          ) : (
                            evt.event_type
                          )}
                        </div>
                        {evt.content && (
                          <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                            {evt.content}
                          </div>
                        )}
                        <div className="timeline-meta">
                          {evt.occurred_at ? fmtDate(evt.occurred_at) : ""}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          ) : null}
        </div>
      </div>
      {toast && (
        <div className={`toast toast-${toast.type}`}>{toast.msg}</div>
      )}
    </>
  );
}

// ---- Helpers ----

function Field({
  label, value, badge, style,
}: {
  label: string;
  value: string | number | null | undefined;
  badge?: { text: string; className: string };
  style?: React.CSSProperties;
}) {
  const display = value !== null && value !== undefined && value !== ""
    ? String(value)
    : "—";
  return (
    <div className="drawer-field">
      <span className="drawer-field-label">{label}</span>
      <span className="drawer-field-value" style={style}>
        {badge ? (
          <span className={`badge ${badge.className}`}>{badge.text}</span>
        ) : (
          display
        )}
      </span>
    </div>
  );
}

function FormGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="form-group">
      <label>{label}</label>
      {children}
    </div>
  );
}

function stageBadge(stage: string) {
  return { text: stage, className: `badge-${stageColor(stage)}` };
}

function recBadge(rec: string) {
  const map: Record<string, string> = {
    APPLY_NOW: "badge-green",
    REVIEW: "badge-yellow",
    SKIP: "badge-red",
    PENDING_JD: "badge-gray",
  };
  return { text: rec, className: map[rec] || "badge-gray" };
}

function isOverdue(date: string | null): boolean {
  if (!date) return false;
  return new Date(date) < new Date();
}

function toDatetimeLocal(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toISOString().slice(0, 16);
  } catch {
    return "";
  }
}
