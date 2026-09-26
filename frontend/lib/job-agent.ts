import { apiUrl } from "@/lib/api";

export type ReviewStatus = "new" | "shortlisted" | "needs_info" | "skipped";
export type JobSource = "possibleos" | "external_search";
export type JobAgentConfig = {
  browser_ai_provider: "gateway" | "openai";
  browser_openai_model: string;
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
  search_source_ids: string[];
  application_notes: string;
};
export type JobSearchSource = {
  id: string;
  name: string;
  url: string;
  method: "public_api" | "public_feed" | "public_page" | "web_search" | "disabled";
  enabled_by_default: boolean;
  note: string;
  aliases: string[];
  available: boolean;
  enabled: boolean;
};
export type Candidate = {
  processing_revision: number;
  processing_updated_at?: string | null;
  classification?: { status: string; requested?: boolean; category_id?: string | null; category_name?: string | null; confidence?: number; reason: string; resume?: { path: string; filename: string } | null };
  application?: { status: string; stage?: string; phase?: string; failed_phase?: string; retryable?: boolean;
    attempt?: number; error?: string; company_summary?: string; gaps?: string[]; send_requested?: boolean;
    started_at?: string; phase_updated_at?: string;
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
    contract_status?: "contract" | "non_contract" | "unknown";
    contract_classification?: { state: "completed" | "error"; version: string; provider: "typesafe";
      model?: string | null; confidence?: number | null;
      probabilities?: Record<"contract" | "non_contract" | "unknown", number> | Record<string, number>;
      classified_at: string; input_sha256: string; error?: string; };
    legal_degree_requirement?: "required" | "unknown";
    legal_degree_reason?: string; legal_degree_evidence?: string | null;
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
  search_sources: { items: JobSearchSource[]; enabled_count: number; available_count: number; total_count: number };
  source_error: string | null;
  source: null | {
    config: { enabled: boolean; timezone: string; local_time: string; max_sources: number };
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

export type ApplicationsResponse = {
  items: Candidate[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  counts: Record<string, number>;
};

export type JobCv = {
  path: string;
  filename: string;
  kind: "application" | "category" | "library";
  size_bytes: number;
  category_ids: string[];
  category_names: string[];
  candidate_id?: string;
  firm_name?: string;
  role_title?: string;
  application_status?: string;
  recipient?: string;
  prepared_at?: string | null;
  updated_at?: string | null;
  sent_verified?: boolean;
};

export type JobCvCatalog = {
  items: JobCv[];
  total: number;
  application_count: number;
  category_count: number;
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
  const contentType = response.headers.get("content-type") || "";
  const raw = await response.text();
  let data: unknown = null;
  if (raw.trim()) {
    try {
      data = JSON.parse(raw) as unknown;
    } catch {
      const kind = contentType.includes("text/html") ? "HTML" : "an invalid response";
      throw new Error(
        `Job Agent API returned ${kind} instead of JSON (HTTP ${response.status}). ` +
        "The backend or proxy may be restarting. Try again in a moment."
      );
    }
  }
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data
      ? (data as { detail?: unknown }).detail
      : undefined;
    throw new Error(typeof detail === "string"
      ? detail
      : `Job Agent request failed (HTTP ${response.status}). Try again.`);
  }
  if (data === null) {
    throw new Error(`Job Agent API returned an empty response (HTTP ${response.status}). Try again.`);
  }
  return data as T;
}
