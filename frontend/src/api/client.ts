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
  ResumeVersionUpdate,
  AccountDetails,
  PasswordChangeResult,
} from "./types";

const BASE = "/api";

class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export async function request<T>(
  url: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    let message = text || `HTTP ${res.status}`;
    let code: string | undefined;
    try {
      const payload = JSON.parse(text) as {
        detail?: string | { code?: string; message?: string };
      };
      if (typeof payload.detail === "string") message = payload.detail;
      if (payload.detail && typeof payload.detail === "object") {
        code = payload.detail.code;
        if (payload.detail.message) message = payload.detail.message;
      }
    } catch {
      // Keep the response body when the server did not return JSON.
    }
    throw new ApiError(res.status, message, code);
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

// ---- Account ----

export function fetchAccount(): Promise<AccountDetails> {
  return request<AccountDetails>("/account");
}

export function updateAccountUsername(body: {
  current_password: string;
  new_username: string;
}): Promise<AccountDetails> {
  return request<AccountDetails>("/account/username", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function updateAccountPassword(body: {
  current_password: string;
  new_password: string;
}): Promise<PasswordChangeResult> {
  return request<PasswordChangeResult>("/account/password", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
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

// ---- Resume Profiles ----

export function fetchResumeProfiles(): Promise<ResumeProfile[]> {
  return request<ResumeProfile[]>("/resume-profiles");
}

export function createResumeProfile(body: Partial<ResumeProfile>): Promise<ResumeProfile> {
  return request<ResumeProfile>("/resume-profiles", { method: "POST", body: JSON.stringify(body) });
}

export function updateResumeProfile(id: number, body: Partial<ResumeProfile>): Promise<ResumeProfile> {
  return request<ResumeProfile>(`/resume-profiles/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

// ---- Resume Versions ----

export function fetchResumeVersions(appId: number): Promise<ResumeVersion[]> {
  return request<ResumeVersion[]>(`/applications/${appId}/resume-versions`);
}

export function generateResume(appId: number): Promise<ResumeVersion> {
  return request<ResumeVersion>(`/applications/${appId}/resume-tailor`, { method: "POST" });
}

export function fetchResumeVersion(versionId: number): Promise<ResumeVersion> {
  return request<ResumeVersion>(`/resume-versions/${versionId}`);
}

export function updateResumeVersion(versionId: number, body: ResumeVersionUpdate): Promise<ResumeVersion> {
  return request<ResumeVersion>(`/resume-versions/${versionId}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function reviewResumeVersion(versionId: number): Promise<ResumeVersion> {
  return request<ResumeVersion>(`/resume-versions/${versionId}/review`, { method: "POST" });
}

export function markResumeVersionUsed(versionId: number): Promise<ResumeVersion> {
  return request<ResumeVersion>(`/resume-versions/${versionId}/use`, { method: "POST" });
}

import type { ResumeProfile, ResumeVersion } from "./types";

export { ApiError };
