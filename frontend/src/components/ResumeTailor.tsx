import { useState, useEffect } from "react";
import { generateResume, fetchResumeVersions, markVersionUsed, updateResumeVersion } from "../api/client";
import { AlertTriangle, Loader2, Check, Copy, Sparkles, ChevronDown, ChevronRight } from "lucide-react";
import type { ResumeVersion, ExperienceBullet } from "../api/types";

interface Props {
  applicationId: number;
}

const RISK_COLORS: Record<string, string> = {
  SAFE: "var(--success)",
  REVIEW: "var(--warning)",
  BLOCKED: "var(--danger)",
};

export default function ResumeTailor({ applicationId }: Props) {
  const [versions, setVersions] = useState<ResumeVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [expandedVersion, setExpandedVersion] = useState<number | null>(null);
  const [toast, setToast] = useState("");
  const [showVersions, setShowVersions] = useState(false);

  useEffect(() => { loadVersions(); }, [applicationId]);

  async function loadVersions() {
    setLoading(true);
    try {
      const v = await fetchResumeVersions(applicationId);
      setVersions(v);
    } catch { setError("Failed to load versions"); }
    finally { setLoading(false); }
  }

  async function handleGenerate() {
    setGenerating(true);
    setError("");
    try {
      const rv = await generateResume(applicationId);
      setVersions((prev) => [rv, ...prev]);
      setExpandedVersion(rv.id);
      setToast("Resume generated");
      setTimeout(() => setToast(""), 2000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Generation failed";
      setError(msg);
    }
    finally { setGenerating(false); }
  }

  async function handleMarkUsed(v: ResumeVersion) {
    try {
      await markVersionUsed(v.id);
      loadVersions();
      setToast("Marked as used");
      setTimeout(() => setToast(""), 2000);
    } catch { setError("Failed to mark"); }
  }

  async function handleRejectBullet(version: ResumeVersion, idx: number) {
    try {
      const bullets = JSON.parse(version.experience_bullets_json || "[]");
      bullets[idx].risk_level = "BLOCKED";
      await updateResumeVersion(version.id, {
        experience_bullets_json: JSON.stringify(bullets),
      });
      loadVersions();
    } catch { /* ignore */ }
  }

  async function handleAcceptBullet(version: ResumeVersion, idx: number) {
    try {
      const bullets = JSON.parse(version.experience_bullets_json || "[]");
      bullets[idx].risk_level = "SAFE";
      await updateResumeVersion(version.id, {
        experience_bullets_json: JSON.stringify(bullets),
      });
      loadVersions();
    } catch { /* ignore */ }
  }

  const copyText = (text: string) => {
    navigator.clipboard.writeText(text);
    setToast("Copied");
    setTimeout(() => setToast(""), 2000);
  };

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5 }}>
          <Sparkles size={14} style={{ marginRight: 4 }} />
          Resume Tailor
        </h3>
        <button className="btn btn-primary btn-sm" onClick={handleGenerate} disabled={generating}>
          {generating ? <Loader2 size={14} /> : <Sparkles size={14} />}
          {generating ? " Generating…" : " Tailor Resume"}
        </button>
      </div>

      {error && (
        <div style={{ background: "var(--danger-light)", padding: 8, borderRadius: 6, fontSize: 12, marginBottom: 8 }}>
          <AlertTriangle size={12} /> {error}
        </div>
      )}

      {loading ? (
        <div style={{ padding: 16, textAlign: "center", color: "var(--text-secondary)" }}>
          <Loader2 size={16} /> Loading versions…
        </div>
      ) : versions.length === 0 ? (
        <div style={{ padding: 12, fontSize: 12, color: "var(--text-secondary)", textAlign: "center" }}>
          No resume versions yet. Click "Tailor Resume" to generate.
        </div>
      ) : (
        <div>
          {versions.slice(0, showVersions ? versions.length : 1).map((v) => (
            <div key={v.id} style={{ border: "1px solid var(--border)", borderRadius: 8, marginBottom: 8, overflow: "hidden" }}>
              <div
                style={{ padding: "8px 12px", cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center", background: v.status === "USED" ? "var(--success-light)" : "var(--surface)" }}
                onClick={() => setExpandedVersion(expandedVersion === v.id ? null : v.id)}
              >
                <div>
                  <span style={{ fontSize: 12, fontWeight: 600 }}>{v.version_name || `Version #${v.id}`}</span>
                  <span className={`badge ${v.status === "USED" ? "badge-green" : v.status === "REVIEWED" ? "badge-blue" : "badge-gray"}`} style={{ marginLeft: 8, fontSize: 10 }}>
                    {v.status}
                  </span>
                  <span style={{ fontSize: 10, color: "var(--text-secondary)", marginLeft: 8 }}>
                    {v.generation_method} · {v.created_at?.slice(0, 10)}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 4 }}>
                  {v.status !== "USED" && (
                    <button className="btn btn-sm" style={{ background: "var(--success-light)", color: "var(--success)", border: "none" }}
                      onClick={(e) => { e.stopPropagation(); handleMarkUsed(v); }}>
                      <Check size={12} /> Use
                    </button>
                  )}
                  {expandedVersion === v.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </div>
              </div>

              {expandedVersion === v.id && (
                <div style={{ padding: 12, borderTop: "1px solid var(--border)", fontSize: 12 }}>
                  {/* Summary */}
                  {v.summary_text && (
                    <div style={{ marginBottom: 8 }}>
                      <strong>Summary:</strong>
                      <p style={{ margin: "4px 0", color: "var(--text-secondary)" }}>{v.summary_text}</p>
                    </div>
                  )}

                  {/* Skills */}
                  {v.skills_json && (
                    <div style={{ marginBottom: 8 }}>
                      <strong>Skills:</strong>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 4 }}>
                        {JSON.parse(v.skills_json).map((s: string, i: number) => (
                          <span key={i} className="badge badge-blue" style={{ fontSize: 10 }}>{s}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Experience Bullets Diff */}
                  {v.experience_bullets_json && JSON.parse(v.experience_bullets_json).length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      <strong>Experience Changes:</strong>
                      {JSON.parse(v.experience_bullets_json).map((b: ExperienceBullet, i: number) => (
                        <div key={i} style={{
                          margin: "6px 0", padding: 8, borderRadius: 6,
                          background: b.risk_level === "BLOCKED" ? "var(--danger-light)" :
                                      b.risk_level === "REVIEW" ? "var(--warning-light)" : "var(--info-light)",
                          borderLeft: `3px solid ${RISK_COLORS[b.risk_level]}`,
                        }}>
                          <div style={{ display: "flex", justifyContent: "space-between" }}>
                            <span className="badge" style={{
                              background: RISK_COLORS[b.risk_level], color: "white", fontSize: 10,
                            }}>{b.risk_level}</span>
                            {b.risk_level !== "BLOCKED" && (
                              <button className="btn btn-sm" style={{ background: "var(--danger-light)", color: "var(--danger)", border: "none", fontSize: 10 }}
                                onClick={() => handleRejectBullet(v, i)}>Reject</button>
                            )}
                            {b.risk_level === "REVIEW" && (
                              <button className="btn btn-sm" style={{ background: "var(--success-light)", color: "var(--success)", border: "none", fontSize: 10 }}
                                onClick={() => handleAcceptBullet(v, i)}>Accept</button>
                            )}
                          </div>
                          <div style={{ marginTop: 4 }}><em>Original:</em> {b.original_text}</div>
                          <div style={{ color: "var(--primary)" }}><em>Tailored:</em> {b.tailored_text}</div>
                          <div style={{ color: "var(--text-secondary)", fontSize: 10 }}>{b.reason}</div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Gap Analysis */}
                  {v.gap_analysis_json && (() => {
                    const gap = JSON.parse(v.gap_analysis_json);
                    return (
                      <div style={{ marginBottom: 8 }}>
                        {gap.unsupported?.length > 0 && (
                          <div style={{ color: "var(--danger)" }}><strong>Unsupported:</strong> {gap.unsupported.join(", ")}</div>
                        )}
                        {gap.warnings?.length > 0 && (
                          <div style={{ color: "var(--warning)" }}><strong>Warnings:</strong> {gap.warnings.join("; ")}</div>
                        )}
                      </div>
                    );
                  })()}

                  {/* Full Text */}
                  {v.full_text && (
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                        <strong>Full Resume:</strong>
                        <button className="btn btn-ghost btn-sm" onClick={() => copyText(v.full_text!)}>
                          <Copy size={12} /> Copy
                        </button>
                      </div>
                      <pre style={{
                        background: "var(--info-light)", padding: 8, borderRadius: 6,
                        maxHeight: 300, overflow: "auto", fontSize: 11, whiteSpace: "pre-wrap",
                      }}>{v.full_text}</pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {versions.length > 1 && (
            <button className="btn btn-ghost btn-sm" onClick={() => setShowVersions(!showVersions)} style={{ width: "100%" }}>
              {showVersions ? "Show less" : `Show all ${versions.length} versions`}
            </button>
          )}
        </div>
      )}

      {toast && <div className="toast toast-success">{toast}</div>}
    </div>
  );
}
