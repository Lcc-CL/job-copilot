import { useState, useMemo, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useApplications } from "../hooks/queries";
import { AlertTriangle, Loader2, Search, ExternalLink, Table, Columns } from "lucide-react";
import DetailDrawer from "../components/DetailDrawer";
import BoardView from "../components/BoardView";
import { stageColor, fmtDate } from "./Dashboard";
import type { ApplicationDetail } from "../api/types";

const STAGES = [
  "DISCOVERED", "SHORTLISTED", "GREETING_READY", "CONTACTED",
  "APPLIED", "REPLIED", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN",
];

const RECOMMENDATIONS = ["APPLY_NOW", "REVIEW", "SKIP", "PENDING_JD"];

const PAGE_SIZE = 25;

function recColor(rec: string): string {
  const map: Record<string, string> = {
    APPLY_NOW: "green",
    REVIEW: "yellow",
    SKIP: "red",
    PENDING_JD: "gray",
  };
  return map[rec] || "gray";
}

export default function Applications() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [keyword, setKeyword] = useState(searchParams.get("keyword") || "");
  const [stage, setStage] = useState(searchParams.get("stage") || "");
  const [recommendation, setRecommendation] = useState(searchParams.get("recommendation") || "");
  const [overdue, setOverdue] = useState(false);
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [view, setView] = useState<"table" | "board">("table");

  // Auto-open detail from URL param
  useEffect(() => {
    const idParam = searchParams.get("id");
    if (idParam) {
      const id = Number(idParam);
      if (id) setSelectedId(id);
    }
  }, [searchParams]);

  const params = useMemo(() => ({
    keyword: keyword || undefined,
    stage: stage || undefined,
    recommendation: recommendation || undefined,
    overdue: overdue || undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  }), [keyword, stage, recommendation, overdue, page]);

  const { data, isLoading, isError, refetch } = useApplications(params);
  const items = data?.items || [];

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  return (
    <div>
      {/* Toolbar */}
      <div className="toolbar">
        <Search size={14} color="var(--text-secondary)" />
        <input
          placeholder="Search company or position…"
          value={keyword}
          onChange={(e) => { setKeyword(e.target.value); setPage(0); }}
        />
        <select
          value={stage}
          onChange={(e) => {
            setStage(e.target.value); setPage(0);
            if (e.target.value) {
              setSearchParams({ stage: e.target.value });
            } else {
              setSearchParams({});
            }
          }}
        >
          <option value="">All Stages</option>
          {STAGES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          value={recommendation}
          onChange={(e) => { setRecommendation(e.target.value); setPage(0); }}
        >
          <option value="">All Recommendations</option>
          {RECOMMENDATIONS.map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13 }}>
          <input
            type="checkbox"
            checked={overdue}
            onChange={(e) => { setOverdue(e.target.checked); setPage(0); }}
          />
          Overdue only
        </label>
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", border: "1px solid var(--border)", borderRadius: 6, overflow: "hidden" }}>
          <button
            className="btn btn-sm"
            style={{
              background: view === "table" ? "var(--primary)" : "var(--surface)",
              color: view === "table" ? "white" : "var(--text)",
              border: "none",
              borderRadius: 0,
            }}
            onClick={() => setView("table")}
          >
            <Table size={14} />
          </button>
          <button
            className="btn btn-sm"
            style={{
              background: view === "board" ? "var(--primary)" : "var(--surface)",
              color: view === "board" ? "white" : "var(--text)",
              border: "none",
              borderRadius: 0,
            }}
            onClick={() => setView("board")}
          >
            <Columns size={14} />
          </button>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={() => refetch()}>
          Refresh
        </button>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="loading-state"><Loader2 size={24} /> Loading applications…</div>
      ) : isError ? (
        <div className="error-state">
          <AlertTriangle size={24} />
          <p>Failed to load applications.</p>
          <button className="btn btn-primary" onClick={() => refetch()}>Retry</button>
        </div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <p>No applications found.</p>
          {keyword || stage || recommendation || overdue ? (
            <button className="btn btn-ghost btn-sm" onClick={() => {
              setKeyword(""); setStage(""); setRecommendation(""); setOverdue(false);
            }}>
              Clear filters
            </button>
          ) : (
            <p style={{ fontSize: 13, marginTop: 8 }}>
              Run <code>python -m job_copilot web import-tracking</code> to import tracking data.
            </p>
          )}
        </div>
      ) : view === "board" ? (
        <BoardView applications={items} onSelect={(id) => setSelectedId(id)} />
      ) : (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Position</th>
                  <th>Stage</th>
                  <th>Recommendation</th>
                  <th>Priority</th>
                  <th>Score</th>
                  <th>Last Contact</th>
                  <th>Next Follow-up</th>
                  <th>Updated</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {items.map((a) => (
                  <AppRow
                    key={a.id}
                    app={a}
                    onClick={() => setSelectedId(a.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="pagination">
            <span>
              {data!.total} total · Page {page + 1} of {totalPages || 1}
            </span>
            <div style={{ display: "flex", gap: 8 }}>
              <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                Previous
              </button>
              <button disabled={page >= totalPages - 1} onClick={() => setPage((p) => p + 1)}>
                Next
              </button>
            </div>
          </div>
        </>
      )}

      {selectedId !== null && (
        <DetailDrawer
          applicationId={selectedId}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}

function AppRow({ app, onClick }: { app: ApplicationDetail; onClick: () => void }) {
  return (
    <tr className="clickable" onClick={onClick}>
      <td style={{ fontWeight: 500 }}>{app.job_company || "—"}</td>
      <td>{app.job_title || "—"}</td>
      <td>
        <span className={`badge badge-${stageColor(app.stage)}`}>{app.stage}</span>
      </td>
      <td>
        {app.job_recommendation ? (
          <span className={`badge badge-${recColor(app.job_recommendation)}`}>
            {app.job_recommendation}
          </span>
        ) : (
          "—"
        )}
      </td>
      <td>{app.priority || "—"}</td>
      <td>{app.job_enriched_score ?? "—"}</td>
      <td>{app.last_contact_at ? fmtDate(app.last_contact_at) : "—"}</td>
      <td style={{ color: isOverdue(app.next_follow_up_at) ? "var(--danger)" : undefined }}>
        {app.next_follow_up_at ? fmtDate(app.next_follow_up_at) : "—"}
      </td>
      <td>{app.updated_at ? fmtDate(app.updated_at) : "—"}</td>
      <td>
        {app.job_url && (
          <a
            href={app.job_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            title="Open job page"
          >
            <ExternalLink size={14} />
          </a>
        )}
      </td>
    </tr>
  );
}

function isOverdue(date: string | null): boolean {
  if (!date) return false;
  return new Date(date) < new Date();
}
