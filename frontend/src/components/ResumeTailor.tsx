import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  fetchResumeVersions,
  generateResume,
  markResumeVersionUsed,
  reviewResumeVersion,
  updateResumeVersion,
} from "../api/client";
import { AlertTriangle, Loader2, Check, Copy, Sparkles, ChevronDown, ChevronRight } from "lucide-react";
import type { ResumeVersion, ExperienceBullet } from "../api/types";
import { canEditResumeVersion, getResumeWorkflowAction } from "./resumeWorkflow";

interface Props {
  applicationId: number;
}

const RISK_COLORS: Record<string, string> = {
  SAFE: "var(--success)",
  REVIEW: "var(--warning)",
  BLOCKED: "var(--danger)",
};

function parseJsonArray<T>(value: string | null): T[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function parseJsonObject(value: string | null): Record<string, unknown> {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function ResumeTailor({ applicationId }: Props) {
  const { t } = useTranslation();
  const [versions, setVersions] = useState<ResumeVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [transitioningId, setTransitioningId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [expandedVersion, setExpandedVersion] = useState<number | null>(null);
  const [toast, setToast] = useState("");
  const [showVersions, setShowVersions] = useState(false);

  useEffect(() => { loadVersions(); }, [applicationId]);

  async function loadVersions() {
    setLoading(true);
    setError("");
    try {
      const v = await fetchResumeVersions(applicationId);
      setVersions(v);
    } catch (e: unknown) {
      setError(errorMessage(e, t("resume.loadFailed")));
    }
    finally { setLoading(false); }
  }

  async function handleGenerate() {
    setGenerating(true);
    setError("");
    try {
      const rv = await generateResume(applicationId);
      setVersions((prev) => [rv, ...prev]);
      setExpandedVersion(rv.id);
      setToast(t("resume.generated"));
      setTimeout(() => setToast(""), 2000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Generation failed";
      setError(msg);
    }
    finally { setGenerating(false); }
  }

  async function handleTransition(v: ResumeVersion) {
    const action = getResumeWorkflowAction(v.status);
    if (!action) return;
    setTransitioningId(v.id);
    setError("");
    try {
      const updated = action === "review"
        ? await reviewResumeVersion(v.id)
        : await markResumeVersionUsed(v.id);
      setVersions((prev) => prev.map((item) => item.id === updated.id ? updated : item));
      setToast(action === "review" ? t("resume.reviewed") : t("resume.markedUsed"));
      setTimeout(() => setToast(""), 2000);
    } catch (e: unknown) {
      setError(errorMessage(e, t("resume.transitionFailed")));
    } finally {
      setTransitioningId(null);
    }
  }

  async function handleRejectBullet(version: ResumeVersion, idx: number) {
    try {
      const bullets = parseJsonArray<ExperienceBullet>(version.experience_bullets_json);
      bullets[idx].risk_level = "BLOCKED";
      const updated = await updateResumeVersion(version.id, {
        experience_bullets_json: JSON.stringify(bullets),
      });
      setVersions((prev) => prev.map((item) => item.id === updated.id ? updated : item));
    } catch (e: unknown) {
      setError(errorMessage(e, t("resume.updateFailed")));
    }
  }

  async function handleAcceptBullet(version: ResumeVersion, idx: number) {
    try {
      const bullets = parseJsonArray<ExperienceBullet>(version.experience_bullets_json);
      bullets[idx].risk_level = "SAFE";
      const updated = await updateResumeVersion(version.id, {
        experience_bullets_json: JSON.stringify(bullets),
      });
      setVersions((prev) => prev.map((item) => item.id === updated.id ? updated : item));
    } catch (e: unknown) {
      setError(errorMessage(e, t("resume.updateFailed")));
    }
  }

  const copyText = (text: string) => {
    navigator.clipboard.writeText(text);
    setToast(t("resume.copied"));
    setTimeout(() => setToast(""), 2000);
  };

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5 }}>
          <Sparkles size={14} style={{ marginRight: 4 }} />
          {t("resume.title")}
        </h3>
        <button className="btn btn-primary btn-sm" onClick={handleGenerate} disabled={generating}>
          {generating ? <Loader2 size={14} /> : <Sparkles size={14} />}
          {generating ? ` ${t("resume.generating")}` : ` ${t("resume.generate")}`}
        </button>
      </div>

      {error && (
        <div style={{ background: "var(--danger-light)", padding: 8, borderRadius: 6, fontSize: 12, marginBottom: 8 }}>
          <AlertTriangle size={12} /> {error}
        </div>
      )}

      {loading ? (
        <div style={{ padding: 16, textAlign: "center", color: "var(--text-secondary)" }}>
          <Loader2 size={16} /> {t("resume.loading")}
        </div>
      ) : versions.length === 0 ? (
        <div style={{ padding: 12, fontSize: 12, color: "var(--text-secondary)", textAlign: "center" }}>
          {t("resume.noVersions")}
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
                    {t(`resume.versionStatus.${v.status}`)}
                  </span>
                  {(() => {
                    const gap = parseJsonObject(v.gap_analysis_json);
                    const isLow = gap.context_quality === 'LOW' || v.generation_method === 'low_context_rule_based';
                    return (
                      <>
                        <span className={`badge ${v.generation_method === 'llm' ? 'badge-green' : 'badge-yellow'}`} style={{ marginLeft: 8, fontSize: 10 }}>
                          {v.generation_method === 'llm' ? 'AI' : v.generation_method === 'low_context_rule_based' ? 'DRAFT' : 'RULE'}
                        </span>
                        {isLow && (
                          <span className="badge badge-red" style={{ marginLeft: 4, fontSize: 10 }}>LOW_CONTEXT</span>
                        )}
                      </>
                    );
                  })()}
                  <div style={{ fontSize: 10, color: "var(--text-secondary)", marginTop: 4 }}>
                    {t("resume.createdAt")}: {formatTimestamp(v.created_at)} · {t("resume.reviewedAt")}: {formatTimestamp(v.reviewed_at)} · {t("resume.usedAt")}: {formatTimestamp(v.used_at)}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 4 }}>
                  {getResumeWorkflowAction(v.status) && (
                    <button className="btn btn-sm" style={{ background: "var(--success-light)", color: "var(--success)", border: "none" }}
                      disabled={transitioningId === v.id}
                      onClick={(e) => { e.stopPropagation(); handleTransition(v); }}>
                      {transitioningId === v.id ? <Loader2 size={12} /> : <Check size={12} />}
                      {getResumeWorkflowAction(v.status) === "review" ? t("resume.confirmReview") : t("resume.markUsed")}
                    </button>
                  )}
                  {expandedVersion === v.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </div>
              </div>

              {expandedVersion === v.id && (
                <div style={{ padding: 12, borderTop: "1px solid var(--border)", fontSize: 12 }}>
                  {/* Rule-based / Low-context notices */}
                  {(() => {
                    const gap = parseJsonObject(v.gap_analysis_json);
                    const isLow = gap.context_quality === 'LOW' || v.generation_method === 'low_context_rule_based';
                    if (isLow) {
                      return (
                        <div style={{ background: "var(--danger-light)", padding: 8, borderRadius: 6, marginBottom: 8, fontSize: 11 }}>
                          ⚠ {t("resume.lowContextNotice")}
                        </div>
                      );
                    }
                    if (v.generation_method !== 'llm') {
                      return (
                        <div style={{ background: "var(--warning-light)", padding: 8, borderRadius: 6, marginBottom: 8, fontSize: 11 }}>
                          ⚠ {t("resume.ruleNotice")}
                        </div>
                      );
                    }
                    return null;
                  })()}
                  {/* Summary */}
                  {v.summary_text && (
                    <div style={{ marginBottom: 8 }}>
                      <strong>{t("resume.summary")}:</strong>
                      <p style={{ margin: "4px 0", color: "var(--text-secondary)" }}>{v.summary_text}</p>
                    </div>
                  )}

                  {/* Skills */}
                  {v.skills_json && (
                    <div style={{ marginBottom: 8 }}>
                      <strong>{t("resume.skills")}:</strong>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 4 }}>
                        {parseJsonArray<string>(v.skills_json).map((s: string, i: number) => (
                          <span key={i} className="badge badge-blue" style={{ fontSize: 10 }}>{s}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Experience Bullets Diff */}
                  {parseJsonArray<ExperienceBullet>(v.experience_bullets_json).length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      <strong>{t("resume.experienceChanges")}:</strong>
                      {parseJsonArray<ExperienceBullet>(v.experience_bullets_json).map((b: ExperienceBullet, i: number) => (
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
                            {canEditResumeVersion(v.status) && b.risk_level !== "BLOCKED" && (
                              <button className="btn btn-sm" style={{ background: "var(--danger-light)", color: "var(--danger)", border: "none", fontSize: 10 }}
                                onClick={() => handleRejectBullet(v, i)}>{t("resume.reject")}</button>
                            )}
                            {canEditResumeVersion(v.status) && b.risk_level === "REVIEW" && (
                              <button className="btn btn-sm" style={{ background: "var(--success-light)", color: "var(--success)", border: "none", fontSize: 10 }}
                                onClick={() => handleAcceptBullet(v, i)}>{t("resume.accept")}</button>
                            )}
                          </div>
                          <div style={{ marginTop: 4 }}><em>{t("resume.original")}:</em> {b.original_text}</div>
                          <div style={{ color: "var(--primary)" }}><em>{t("resume.tailored")}:</em> {b.tailored_text}</div>
                          <div style={{ color: "var(--text-secondary)", fontSize: 10 }}>{t("resume.reason")}: {b.reason}</div>
                          <div style={{ color: "var(--text-secondary)", fontSize: 10 }}>{t("resume.evidence")}: {b.evidence_reference || "—"}</div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Gap Analysis */}
                  {v.gap_analysis_json && (() => {
                    const gap = parseJsonObject(v.gap_analysis_json);
                    const unsupported = Array.isArray(gap.unsupported)
                      ? gap.unsupported.filter((item): item is string => typeof item === "string")
                      : [];
                    const warnings = Array.isArray(gap.warnings)
                      ? gap.warnings.filter((item): item is string => typeof item === "string")
                      : [];
                    return (
                      <div style={{ marginBottom: 8 }}>
                        {unsupported.length > 0 && (
                          <div style={{ color: "var(--danger)" }}><strong>{t("resume.unsupported")}:</strong> {unsupported.join(", ")}</div>
                        )}
                        {warnings.length > 0 && (
                          <div style={{ color: "var(--warning)" }}><strong>{t("resume.warnings")}:</strong> {warnings.join("; ")}</div>
                        )}
                      </div>
                    );
                  })()}

                  {/* Full Text */}
                  {v.full_text && (
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                        <strong>{t("resume.fullResume")}:</strong>
                        <button className="btn btn-ghost btn-sm" onClick={() => copyText(v.full_text!)}>
                          <Copy size={12} /> {t("resume.copy")}
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
              {showVersions ? t("resume.showLess") : t("resume.showAll", { count: versions.length })}
            </button>
          )}
        </div>
      )}

      {toast && <div className="toast toast-success">{toast}</div>}
    </div>
  );
}
