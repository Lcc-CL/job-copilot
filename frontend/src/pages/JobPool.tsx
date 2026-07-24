import { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { fetchJobs } from "../api/client";
import { useCreateApplication } from "../hooks/queries";
import { AlertTriangle, Loader2, Search, ExternalLink, Plus, Check } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { translateRecommendation } from "../i18n/helpers";
import type { Job } from "../api/types";

const PAGE_SIZE = 30;

function recBadge(rec: string): string {
  const map: Record<string, string> = {
    APPLY_NOW: "badge-green",
    REVIEW: "badge-yellow",
    SKIP: "badge-red",
    PENDING_JD: "badge-gray",
  };
  return map[rec] || "badge-gray";
}

export default function JobPool() {
  const { t } = useTranslation();
  const [keyword, setKeyword] = useState("");
  const [recommendation, setRecommendation] = useState("");
  const [jdStatus, setJdStatus] = useState("");
  const [minScore, setMinScore] = useState("");
  const [untrackedOnly, setUntrackedOnly] = useState(false);
  const [page, setPage] = useState(0);
  const [addingId, setAddingId] = useState<number | null>(null);
  const [addedIds, setAddedIds] = useState<Set<number>>(new Set());
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);

  const navigate = useNavigate();
  const createApp = useCreateApplication();

  const params = useMemo(() => ({
    keyword: keyword || undefined,
    recommendation: recommendation || undefined,
    jd_status: jdStatus || undefined,
    min_score: minScore ? Number(minScore) : undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  }), [keyword, recommendation, jdStatus, minScore, page]);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["jobs", params],
    queryFn: () => fetchJobs(params),
  });

  const items = useMemo(() => {
    if (!data?.items) return [];
    if (!untrackedOnly) return data.items;
    return data.items.filter((j) => !j.has_application);
  }, [data, untrackedOnly]);

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  const handleAdd = async (job: Job) => {
    setAddingId(job.id);
    const hasGreeting = !!(job.greeting_text && job.greeting_text.length > 10);
    try {
      const result = await createApp.mutateAsync({
        jobId: job.id,
        body: {
          stage: hasGreeting ? "GREETING_READY" : "SHORTLISTED",
          channel: "boss",
        },
      });
      setAddedIds((prev) => new Set(prev).add(job.id));
      setMessage({ text: t("jobPool.addedToast"), type: "success" });
      setTimeout(() => setMessage(null), 2000);
      job.has_application = true;
      job.application_id = result.id;
      job.application_stage = result.stage;
    } catch {
      setMessage({ text: "Failed to add", type: "error" });
      setTimeout(() => setMessage(null), 3000);
    } finally {
      setAddingId(null);
    }
  };

  return (
    <div>
      {/* Toolbar */}
      <div className="toolbar">
        <Search size={14} color="var(--text-secondary)" />
        <input placeholder="Search…" value={keyword} onChange={(e) => { setKeyword(e.target.value); setPage(0); }} />
        <select value={recommendation} onChange={(e) => { setRecommendation(e.target.value); setPage(0); }}>
          <option value="">All Recs</option>
          <option value="APPLY_NOW">APPLY_NOW</option>
          <option value="REVIEW">REVIEW</option>
          <option value="SKIP">SKIP</option>
          <option value="PENDING_JD">PENDING_JD</option>
        </select>
        <select value={jdStatus} onChange={(e) => { setJdStatus(e.target.value); setPage(0); }}>
          <option value="">JD Status</option>
          <option value="PENDING_JD">PENDING_JD</option>
        </select>
        <input
          type="number"
          placeholder="Min score"
          value={minScore}
          onChange={(e) => { setMinScore(e.target.value); setPage(0); }}
          style={{ width: 90 }}
        />
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13 }}>
          <input type="checkbox" checked={untrackedOnly} onChange={(e) => setUntrackedOnly(e.target.checked)} />
          Untracked only
        </label>
        <div style={{ flex: 1 }} />
        <button className="btn btn-secondary btn-sm" onClick={() => refetch()}>Refresh</button>
      </div>

      {isLoading ? (
        <div className="loading-state"><Loader2 size={24} /> Loading…</div>
      ) : isError ? (
        <div className="error-state">
          <AlertTriangle size={24} /><p>Failed to load.</p>
          <button className="btn btn-primary btn-sm" onClick={() => refetch()}>Retry</button>
        </div>
      ) : items.length === 0 ? (
        <div className="empty-state"><p>No jobs found.</p></div>
      ) : (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Title</th><th>Company</th><th>City</th><th>Salary</th>
                  <th>Score</th><th>Rec</th><th>JD</th><th>Greeting</th>
                  <th>Platform</th><th>Link</th><th>Action</th>
                </tr>
              </thead>
              <tbody>
                {items.map((j) => (
                  <tr key={j.id}>
                    <td style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {j.title || "—"}
                    </td>
                    <td>{j.company || "—"}</td>
                    <td>{j.city || "—"}</td>
                    <td>{j.salary_text || "—"}</td>
                    <td>{j.enriched_score ?? j.original_score ?? "—"}</td>
                    <td>
                      {j.recommendation ? (
                        <span className={`badge ${recBadge(j.recommendation)}`}>{translateRecommendation(t, j.recommendation)}</span>
                      ) : "—"}
                    </td>
                    <td>{j.jd_status === "PENDING_JD" ? <span className="badge badge-gray">PENDING_JD</span> : "✓"}</td>
                    <td>{j.greeting_text ? <span className="badge badge-green">Ready</span> : "—"}</td>
                    <td>{j.platform}</td>
                    <td>
                      {j.url && (
                        <a href={j.url} target="_blank" rel="noopener noreferrer">
                          <ExternalLink size={14} />
                        </a>
                      )}
                    </td>
                    <td>
                      {j.has_application || addedIds.has(j.id) ? (
                        <button
                          className="btn btn-sm"
                          style={{ background: "var(--success-light)", color: "var(--success)", cursor: "default", border: "none" }}
                          onClick={() => j.application_id && navigate(`/applications?id=${j.application_id}`)}
                        >
                          <Check size={14} /> Tracked
                        </button>
                      ) : (
                        <button
                          className="btn btn-primary btn-sm"
                          disabled={addingId === j.id}
                          onClick={() => handleAdd(j)}
                        >
                          {addingId === j.id ? (
                            <Loader2 size={14} />
                          ) : (
                            <Plus size={14} />
                          )}
                          Add
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <span>{data!.total} total · Page {page + 1} of {totalPages || 1}</span>
            <div style={{ display: "flex", gap: 8 }}>
              <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Prev</button>
              <button disabled={page >= totalPages - 1} onClick={() => setPage((p) => p + 1)}>Next</button>
            </div>
          </div>
        </>
      )}
      {message && <div className={`toast toast-${message.type}`}>{message.text}</div>}
    </div>
  );
}
