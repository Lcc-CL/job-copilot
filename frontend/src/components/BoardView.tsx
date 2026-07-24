import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  DndContext, closestCorners, PointerSensor, useSensor, useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext, verticalListSortingStrategy, useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useUpdateApplication } from "../hooks/queries";
import { ExternalLink, GripVertical, ChevronDown, ChevronRight } from "lucide-react";
import { translateStage, translateRecommendation } from "../i18n/helpers";
import type { ApplicationDetail } from "../api/types";

const COLUMNS = [
  "DISCOVERED", "SHORTLISTED", "GREETING_READY", "CONTACTED",
  "APPLIED", "REPLIED", "INTERVIEW", "OFFER",
];

const CLOSED_STAGES = ["REJECTED", "WITHDRAWN"];

function recColor(rec: string | null): string {
  const map: Record<string, string> = {
    APPLY_NOW: "badge-green", REVIEW: "badge-yellow",
    SKIP: "badge-red", PENDING_JD: "badge-gray",
  };
  return map[rec || ""] || "badge-gray";
}

interface Props {
  applications: ApplicationDetail[];
  onSelect: (id: number) => void;
}

export default function BoardView({ applications, onSelect }: Props) {
  const { t } = useTranslation();
  const updateApp = useUpdateApplication();
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);
  const [showClosed, setShowClosed] = useState(false);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  const columns = new Map<string, ApplicationDetail[]>();
  for (const col of COLUMNS) columns.set(col, []);
  const closed: ApplicationDetail[] = [];
  for (const a of applications) {
    if (CLOSED_STAGES.includes(a.stage)) {
      closed.push(a);
    } else {
      const list = columns.get(a.stage);
      if (list) list.push(a);
      else closed.push(a);
    }
  }

  async function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over) return;
    const appId = Number(active.id);
    const newStage = String(over.id);
    const app = applications.find((a) => a.id === appId);
    if (!app || app.stage === newStage) return;

    // Optimistic update
    app.stage = newStage;
    try {
      await updateApp.mutateAsync({ id: appId, body: { stage: newStage } });
      setMessage({ text: `${t("applications.movedToast")} ${translateStage(t, newStage)}`, type: "success" });
      setTimeout(() => setMessage(null), 2000);
    } catch {
      app.stage = app.stage; // revert
      setMessage({ text: t("applications.moveFailed"), type: "error" });
      setTimeout(() => setMessage(null), 3000);
    }
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCorners} onDragEnd={handleDragEnd}>
      <div style={{ display: "flex", gap: 12, overflowX: "auto", paddingBottom: 12 }}>
        {COLUMNS.map((stage) => {
          const items = columns.get(stage) || [];
          return (
            <Column
              key={stage}
              stage={stage}
              items={items}
              onSelect={onSelect}
              t={t}
            />
          );
        })}
      </div>
      {/* Closed */}
      {closed.length > 0 && (
        <div className="section" style={{ marginTop: 16 }}>
          <div
            className="section-title"
            style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}
            onClick={() => setShowClosed(!showClosed)}
          >
            {showClosed ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            {t("applications.closed")} ({closed.length})
          </div>
          {showClosed && (
            <div style={{ display: "flex", gap: 12, overflowX: "auto", marginTop: 8 }}>
              <ClosedColumn items={closed} onSelect={onSelect} t={t} />
            </div>
          )}
        </div>
      )}
      {message && <div className={`toast toast-${message.type}`}>{message.text}</div>}
    </DndContext>
  );
}

const COLUMN_COLORS: Record<string, string> = {
  DISCOVERED: "var(--info-light)",
  SHORTLISTED: "var(--primary-light)",
  GREETING_READY: "#e8f5e9",
  CONTACTED: "var(--warning-light)",
  APPLIED: "#e3f2fd",
  REPLIED: "#f3e5f5",
  INTERVIEW: "var(--success-light)",
  OFFER: "#e0f2f1",
};

function Column({ stage, items, onSelect, t }: { stage: string; items: ApplicationDetail[]; onSelect: (id: number) => void; t: any }) {
  return (
    <div style={{
      minWidth: 210, maxWidth: 210, background: COLUMN_COLORS[stage] || "var(--info-light)",
      borderRadius: "var(--radius)", padding: 8,
    }}>
      <div style={{ fontSize: 12, fontWeight: 600, padding: "4px 8px", marginBottom: 4 }}>
        {translateStage(t, stage)} <span style={{ color: "var(--text-secondary)", fontWeight: 400 }}>({items.length})</span>
      </div>
      <SortableContext items={items.map((a) => a.id)} strategy={verticalListSortingStrategy}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {items.map((a) => (
            <SortableCard key={a.id} app={a} onSelect={onSelect} t={t} />
          ))}
          {items.length === 0 && (
            <div style={{ padding: 12, fontSize: 12, color: "var(--text-secondary)", textAlign: "center" }}>
              {t("applications.dropHere")}
            </div>
          )}
        </div>
      </SortableContext>
    </div>
  );
}

function ClosedColumn({ items, onSelect, t }: { items: ApplicationDetail[]; onSelect: (id: number) => void; t: any }) {
  return (
    <div style={{ minWidth: 210, maxWidth: 210, background: "var(--info-light)", borderRadius: "var(--radius)", padding: 8 }}>
      {items.map((a) => (
        <div
          key={a.id}
          style={{ padding: "6px 8px", fontSize: 12, cursor: "pointer", borderRadius: 4, marginBottom: 4, background: "var(--surface)" }}
          onClick={() => onSelect(a.id)}
        >
          <div style={{ fontWeight: 500 }}>{a.job_company || "—"}</div>
          <div style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {a.job_title || "—"}
          </div>
          <span className={`badge ${stageBadge(a.stage)}`} style={{ marginTop: 2 }}>{translateStage(t, a.stage)}</span>
        </div>
      ))}
    </div>
  );
}

function SortableCard({ app, onSelect, t }: { app: ApplicationDetail; onSelect: (id: number) => void; t: any }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: app.id });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const overdue = app.next_follow_up_at && new Date(app.next_follow_up_at) < new Date();

  return (
    <div
      ref={setNodeRef}
      style={{
        ...style,
        background: "var(--surface)", borderRadius: 6, padding: "8px 6px",
        boxShadow: "0 1px 2px rgba(0,0,0,0.06)", cursor: "default",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }} onClick={() => onSelect(app.id)}>
          <div style={{ fontSize: 12, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {app.job_company || "—"}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 1 }}>
            {app.job_title || "—"}
          </div>
          <div style={{ display: "flex", gap: 4, marginTop: 4, flexWrap: "wrap" }}>
            {app.job_recommendation && (
              <span className={`badge ${recColor(app.job_recommendation)}`} style={{ fontSize: 10 }}>
                {translateRecommendation(t, app.job_recommendation)}
              </span>
            )}
            {app.job_enriched_score != null && (
              <span style={{ fontSize: 10, color: "var(--text-secondary)" }}>{app.job_enriched_score}</span>
            )}
            {app.priority && (
              <span style={{ fontSize: 10, color: "var(--text-secondary)" }}>{app.priority}</span>
            )}
            {overdue && <span className="badge badge-red" style={{ fontSize: 10 }}>Overdue</span>}
          </div>
          {app.next_follow_up_at && (
            <div style={{ fontSize: 10, color: overdue ? "var(--danger)" : "var(--text-secondary)", marginTop: 2 }}>
              Next: {new Date(app.next_follow_up_at).toLocaleDateString("zh-CN")}
            </div>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, marginLeft: 4 }}>
          <button {...attributes} {...listeners} style={{ background: "none", border: "none", cursor: "grab", padding: 2 }}>
            <GripVertical size={14} color="var(--text-secondary)" />
          </button>
          {app.job_url && (
            <a href={app.job_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>
              <ExternalLink size={12} />
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

function stageBadge(stage: string): string {
  const map: Record<string, string> = {
    GREETING_READY: "badge-blue", CONTACTED: "badge-yellow", APPLIED: "badge-blue",
    REPLIED: "badge-yellow", INTERVIEW: "badge-green", OFFER: "badge-green",
    REJECTED: "badge-red", WITHDRAWN: "badge-gray",
  };
  return map[stage] || "badge-gray";
}
