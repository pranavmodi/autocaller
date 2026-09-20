import { apiUrl } from "@/lib/api";

export type ReviewStatus = "new" | "shortlisted" | "needs_info" | "skipped";
export type JobSource = "possibleos" | "external_search";
export type JobAgentConfig = {
  classification_enabled: boolean;
  classification_threshold: number;
  resume_categories: { id: string; name: string; description: string; resume_path: string }[];
  collection_enabled: boolean;
  search: string;
  remote_scope: "any" | "remote" | "global";
  posted_within_days: number | null;
  target_roles: string;
  preferred_industries: string;
  location_preferences: string;
  prefer_overseas_employers: boolean;
  application_notes: string;
};
export type Candidate = {
  processing_revision: number;
  processing_updated_at?: string | null;
  classification?: { status: string; requested?: boolean; category_id?: string | null; category_name?: string | null; confidence?: number; reason: string; resume?: { path: string; filename: string } | null };
  application?: { status: string; stage?: string; phase?: string; failed_phase?: string; retryable?: boolean;
    attempt?: number; error?: string; company_summary?: string; gaps?: string[]; send_requested?: boolean;
    authorized_at?: string | null; send_started_at?: string; prepared_at?: string; sent_at?: string;
    duplicate_checked_at?: string; verification_checked_at?: string; verification_next_at?: string | null;
    verification_rechecks?: number;
    recipient?: { email: string; name: string; reason: string; evidence: {
      source_url: string; text: string; source_type?: "public_page" | "possibleos_contact";
      contact_id?: string | null; source_name?: string | null; observed_at?: string | null;
    } };
    email?: { from: string; to: string; subject: string; body_text: string }; attachment?: { path: string; filename: string }; };
  id: string; status: ReviewStatus; note: string; revision: number;
  created_at: string; updated_at: string; decision_source: string | null;
  email_status: string; form_status: string;
  contact?: { available: boolean; count: number; best: null | {
    contact_id: string; email: string; name: string; title: string; kind: "recruiting" | "routing"; source: string;
  } };
  posting: {
    firm_name: string; title: string; source_url: string; description_summary: string;
    location?: string; work_arrangement?: string; posted_date?: string;
    last_checked_at?: string; status?: string; remote_scope?: string;
    colombia_eligibility?: string; technology_mentions?: string[];
    job_source?: JobSource; discovery_provider?: string;
  };
};
export type CollectionRun = {
  id: string; status: string; total: number; processed: number; remaining: number;
  added: number; updated: number; invalid: number; error: string | null;
  config_revision: number; updated_at: string; completed_at: string | null;
};
export type Overview = {
  processing_counts: Record<string, number>;
  collection: CollectionRun | null; sync_interval_seconds: number;
  config: JobAgentConfig; revision: number; mode: string; execution_connected: boolean;
  last_collected_at: string | null; counts: Record<ReviewStatus, number>;
  source_error: string | null;
  source: null | {
    config: { enabled: boolean; timezone: string; local_time: string };
    next_due_at: string | null; schedule_enabled: boolean; timer_installation: string;
    runs: { id: string; status: string; started_at: string; completed_at: string | null;
      result: {
        new_jobs?: number; verified?: number; closed?: number; duplicates_skipped?: number;
        errors?: unknown[]; job_agent_search?: boolean; search_trigger?: "manual" | "scheduled" | "operator";
        manual_search?: boolean; search_profile?: Record<string, unknown>;
        contacts_found?: number; contacts_inserted?: number;
        interrupted_reason?: "backend_restart";
        [key: string]: unknown;
      } }[];
  };
};
export type AgentEvent = {
  id: number; kind: string; message: string; created_at: string; details: Record<string, unknown>;
};

export async function jobAgentRequest<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(apiUrl(`/api/job-agent${path}`), {
    method: body === undefined ? "GET" : "POST", credentials: "include",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 401) {
    window.location.assign(`/login?next=${encodeURIComponent("/job-agent")}`);
    throw new Error("Please sign in again.");
  }
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not save this request. Check the entered values and try again.");
  return data as T;
}
