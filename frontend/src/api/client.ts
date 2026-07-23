import type {
  DashboardSummary,
  FollowUps,
  PaginatedResponse,
  Job,
  ApplicationDetail,
  ApplicationUpdate,
  JobUpdate,
  ApplicationCreate,
  EventCreate,
  FollowUpAction,
  ApplicationEvent,
} from "./types";

const BASE = "/api";

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(
  url: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, text || `HTTP ${res.status}`);
  }
  if (res.headers.get("content-type")?.includes("application/json")) {
    return res.json();
  }
  return undefined as unknown as T;
}

function queryString(params: Record<string, string | number | boolean | undefined>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") {
      qs.set(k, String(v));
    }
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

// ---- Dashboard ----

export function fetchDashboard(): Promise<DashboardSummary> {
  return request<DashboardSummary>("/dashboard/summary");
}

export function fetchFollowUps(): Promise<FollowUps> {
  return request<FollowUps>("/follow-ups");
}

// ---- Jobs ----

export function fetchJobs(params: {
  keyword?: string;
  recommendation?: string;
  jd_status?: string;
  company?: string;
  min_score?: number;
  limit?: number;
  offset?: number;
}): Promise<PaginatedResponse<Job>> {
  return request<PaginatedResponse<Job>>(`/jobs${queryString(params)}`);
}

export function fetchJob(id: number): Promise<Job> {
  return request<Job>(`/jobs/${id}`);
}

export function updateJob(id: number, body: JobUpdate): Promise<Job> {
  return request<Job>(`/jobs/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function createApplication(
  jobId: number,
  body: ApplicationCreate,
): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/jobs/${jobId}/application`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ---- Applications ----

export function fetchApplications(params: {
  stage?: string;
  recommendation?: string;
  overdue?: boolean;
  due_before?: string;
  keyword?: string;
  limit?: number;
  offset?: number;
}): Promise<PaginatedResponse<ApplicationDetail>> {
  return request<PaginatedResponse<ApplicationDetail>>(
    `/applications${queryString(params)}`,
  );
}

export function fetchApplication(id: number): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}`);
}

export function updateApplication(
  id: number,
  body: ApplicationUpdate,
): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function followUpApplication(
  id: number,
  body: FollowUpAction,
): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}/follow-up`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function addApplicationEvent(
  id: number,
  body: EventCreate,
): Promise<ApplicationEvent> {
  return request<ApplicationEvent>(`/applications/${id}/events`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ---- Export ----

export function getApplicationsCsvUrl(): string {
  return `${BASE}/export/applications.csv`;
}

export { ApiError };
