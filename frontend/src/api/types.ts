// ---- Shared ----

export interface PaginatedResponse<T> {
  total: number;
  limit: number;
  offset: number;
  items: T[];
}

// ---- Dashboard ----

export interface DashboardSummary {
  total_jobs: number;
  shortlisted: number;
  greeting_ready: number;
  contacted: number;
  applied: number;
  replied: number;
  interviews: number;
  offers: number;
  rejected: number;
  due_today: number;
  overdue: number;
  response_rate: number;
  interview_rate: number;
  recommendations: Record<string, number>;
}

export interface FollowUps {
  overdue: ApplicationDetail[];
  due_today: ApplicationDetail[];
  upcoming: ApplicationDetail[];
}

// ---- Job ----

export interface JobScore {
  fit_score: number | null;
  verdict: string | null;
  archetype: string | null;
  authenticity: string | null;
  reasons: string | null;
  highlights: string | null;
  gaps: string | null;
}

export interface Job {
  id: number;
  platform: string;
  job_id: string;
  url: string | null;
  title: string | null;
  company: string | null;
  company_size: string | null;
  industry: string | null;
  salary_text: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_months: number | null;
  city: string | null;
  district: string | null;
  experience: string | null;
  degree: string | null;
  tags: string | null;
  jd_text: string | null;
  jd_status: string | null;
  original_score: number | null;
  enriched_score: number | null;
  recommendation: string | null;
  greeting_text: string | null;
  has_application: boolean;
  application_id: number | null;
  application_stage: string | null;
  score: JobScore | null;
}

// ---- Application ----

export interface ApplicationEvent {
  id: number;
  event_type: string;
  from_stage: string | null;
  to_stage: string | null;
  content: string | null;
  occurred_at: string | null;
}

export interface ApplicationDetail {
  id: number;
  job_pk: number;
  job_title: string | null;
  job_company: string | null;
  job_url: string | null;
  job_recommendation: string | null;
  job_enriched_score: number | null;
  job_salary_text: string | null;
  job_city: string | null;
  job_jd_status: string | null;
  job_original_score: number | null;
  job_greeting_text: string | null;
  stage: string;
  priority: string | null;
  channel: string | null;
  resume_version: string | null;
  applied_at: string | null;
  last_contact_at: string | null;
  next_follow_up_at: string | null;
  notes: string | null;
  created_at: string | null;
  updated_at: string | null;
  events: ApplicationEvent[];
}

// ---- Mutations ----

export interface ApplicationUpdate {
  stage?: string;
  priority?: string | null;
  channel?: string;
  resume_version?: string | null;
  applied_at?: string | null;
  last_contact_at?: string | null;
  next_follow_up_at?: string | null;
  notes?: string | null;
}

export interface JobUpdate {
  jd_status?: string;
  jd_text?: string;
  recommendation?: string;
  greeting_text?: string;
  notes?: string;
}

export interface ApplicationCreate {
  stage: string;
  priority?: string;
  channel?: string;
  resume_version?: string;
  notes?: string;
}

export interface EventCreate {
  event_type: string;
  from_stage?: string;
  to_stage?: string;
  content?: string;
}

export interface ResumeProfile {
  id: number;
  name: string;
  content_text: string | null;
  is_master: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface ExperienceBullet {
  original_text: string;
  tailored_text: string;
  reason: string;
  evidence_reference: string;
  risk_level: "SAFE" | "REVIEW" | "BLOCKED";
}

export interface ResumeVersion {
  id: number;
  application_id: number;
  resume_profile_id: number | null;
  version_name: string | null;
  summary_text: string | null;
  skills_json: string | null;
  experience_bullets_json: string | null;
  gap_analysis_json: string | null;
  full_text: string | null;
  generation_method: string | null;
  status: "DRAFT" | "REVIEWED" | "USED";
  created_at: string | null;
  reviewed_at: string | null;
  used_at: string | null;
  updated_at: string | null;
  status_events: ResumeStatusEvent[];
}

export interface ResumeStatusEvent {
  id: number;
  event_type: "resume_created" | "resume_reviewed" | "resume_used";
  resume_version_id: number;
  application_id: number;
  from_status: "DRAFT" | "REVIEWED" | null;
  to_status: "DRAFT" | "REVIEWED" | "USED";
  timestamp: string | null;
}

export interface ResumeVersionUpdate {
  version_name?: string;
  experience_bullets_json?: string;
}

export interface FollowUpAction {
  content?: string;
  next_follow_up_at?: string | null;
  stage?: string;
}
