const EMAILTAG_BASE = "/emailtag";

export class EmailtagAuthError extends Error {
  readonly status = 401;
  readonly detail: string;

  constructor(detail = "PIFStats authentication required") {
    super(detail);
    this.name = "EmailtagAuthError";
    this.detail = detail;
  }
}

export interface EmailtagApiErrorDetails {
  status: number;
  detail: string;
}

export class EmailtagApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor({ status, detail }: EmailtagApiErrorDetails) {
    super(detail);
    this.name = "EmailtagApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface PifContact {
  name: string;
  title: string;
  email: string;
  phone: string;
  extension: string;
  linkedin?: string | null;
}

export interface LeadershipMember {
  name: string;
  title: string;
  email: string | null;
  phone: string | null;
  linkedin: string | null;
  bio: string | null;
  image_url: string | null;
  education?: string[];
  experience?: string[];
  skills?: string[];
  certifications?: string[];
  publications?: string[];
  cases_handled?: string[];
  bar_admissions?: string[];
}

export interface StaffMember {
  name: string;
  title: string;
  role_category: string;
  email: string | null;
  phone: string | null;
  linkedin: string | null;
  bio: string | null;
}

export interface JobPosting {
  title: string;
  location: string | null;
  employment_type: string | null;
  remote_eligibility?: string | null;
  posted_date: string;
  description_summary: string;
  responsibilities: string[];
  qualifications: string[];
  source_name: string;
  source_url: string;
  role_category?: string;
  trigger_tags?: string[];
  technology_mentions?: string[];
  gtm_relevance?: "high" | "medium" | "low";
  classification_confidence?: number;
  work_arrangement?: "remote" | "hybrid" | "onsite" | "unclear";
  remote_scope?: "global" | "country_restricted" | "location_restricted" | "unclear" | "not_remote";
  global_remote?: boolean;
  global_remote_evidence?: string[];
  global_remote_confidence?: number;
  classification_provider?: string;
  classification_version?: string;
  classified_at?: string;
}

export interface JobPostingsResearch {
  has_recent_openings: boolean;
  window_days: number;
  window_start: string;
  window_end: string;
  researched_at: string;
  postings: JobPosting[];
  classification_status?: string;
  classification_version?: string;
  classified_at?: string;
}

export interface PifJobPostingResult {
  first_seen_at?: string;
  last_checked_at?: string;
  ats_created_at?: string;
  ats_updated_at?: string;
  recency_label?: string;
  colombia_eligibility?: string;
  status?: string;
  job_id?: string;
  firm_id: string;
  firm_name: string;
  entity_type: string | null;
  website: string | null;
  updated_at: string | null;
  found_at: string | null;
  title: string;
  location: string | null;
  employment_type: string | null;
  remote_eligibility: string | null;
  posted_date: string | null;
  description_summary: string;
  source_name: string;
  source_url: string;
  role_category: string | null;
  trigger_tags: string[];
  technology_mentions: string[];
  gtm_relevance: "high" | "medium" | "low" | null;
  classification_confidence: number | null;
  work_arrangement: "remote" | "hybrid" | "onsite" | "unclear" | null;
  remote_scope: "global" | "country_restricted" | "location_restricted" | "unclear" | "not_remote" | null;
  global_remote: boolean;
  global_remote_evidence: string[];
  global_remote_confidence: number | null;
  contract_status: "contract" | "non_contract" | "unknown";
  contract_classification: {
    state: "completed" | "error";
    version: string;
    provider: "typesafe";
    model?: string | null;
    confidence?: number | null;
    probabilities?: Record<string, number>;
    classified_at: string;
    input_sha256: string;
    error?: string;
  } | null;
}

export interface PifJobPostingsListParams {
  search?: string;
  role_category?: string;
  trigger_tag?: string;
  technology?: string;
  gtm_relevance?: "high" | "medium" | "low";
  remote_scope?: "remote" | "global" | "not_global";
  contract_status?: "contract" | "non_contract" | "unknown";
  global_remote?: boolean;
  posted_within_days?: number;
  order?: "posted_desc" | "found_desc";
  page?: number;
  page_size?: number;
}

export interface PifJobPostingsListResponse {
  items: PifJobPostingResult[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface PifJobResearchDailyStat {
  date: string;
  firms_processed: number;
  firms_completed: number;
  firms_failed: number;
  firms_with_openings: number;
  job_postings_found: number;
  research_attempts: number;
}

export interface PifJobResearchDailyStatsResponse {
  timezone: string;
  days: number;
  today: PifJobResearchDailyStat;
  daily: PifJobResearchDailyStat[];
  queue: {
    queued: number;
    in_progress: number;
  };
  generated_at: string;
}

export interface AIAdoptionPosture {
  adoption_stage: "unknown" | "exploring" | "piloting" | "adopted" | "scaling" | "restricted";
  leadership_stance: "unknown" | "supportive" | "cautious" | "opposed" | "mixed";
  summary: string;
  confidence: number;
  checked_at?: string;
  searched_sources: string[];
  statements: {
    speaker_name: string | null;
    speaker_title: string | null;
    source_url: string;
    source_type: string;
    published_at: string | null;
    quote: string | null;
    summary: string;
    scope: "firm_adoption" | "personal_opinion" | "industry_commentary";
    tools: string[];
    use_cases: string[];
  }[];
}

export interface ResearchData {
  ai_adoption?: AIAdoptionPosture;
  ai_adoption_history?: AIAdoptionPosture[];
  practice_areas: string[];
  founded_year: string | null;
  firm_size: string | null;
  office_locations: string[];
  notable_cases: string[];
  awards_recognition: string[];
  bar_associations: string[];
  social_media: Record<string, string>;
  additional_info: string | null;
  sources: string[];
  leadership_email_history?: unknown[];
  job_postings?: JobPostingsResearch;
  job_postings_research_status?: string | null;
  last_job_postings_researched_at?: string | null;
  sitemap_monitor?: SitemapMonitorSummary;
  local_enrichment?: LocalEnrichmentState;
}

export interface SitemapMonitorSummary {
  status: "completed" | "missing" | "failed" | string;
  provider?: string;
  checked_at?: string | null;
  website?: string | null;
  sitemap_urls?: string[];
  url_count?: number;
  changed?: boolean | null;
  added_count?: number;
  removed_count?: number;
  added_urls?: string[];
  removed_urls?: string[];
  truncated?: boolean;
  snapshot_id?: string;
  error?: string | null;
}

export interface SitemapSnapshot {
  id: string;
  website?: string | null;
  status: string;
  sitemap_urls: string[];
  url_count: number;
  added_count: number;
  removed_count: number;
  added_urls: string[];
  removed_urls: string[];
  truncated: boolean;
  error?: string | null;
  fetched_at: string;
}

export interface SitemapHistoryResponse {
  pif_id: string;
  items: SitemapSnapshot[];
}

export interface EnrichmentStage {
  key: string;
  label: string;
  status: "pending" | "in_progress" | "completed" | "failed" | "skipped" | string;
  message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  details?: Record<string, unknown> | null;
}

export interface LocalEnrichmentState {
  task_id?: string | null;
  status?: string | null;
  current_stage?: string | null;
  progress_percent?: number | null;
  stages?: EnrichmentStage[];
  warning_count?: number;
  message?: string | null;
  error?: string | null;
  dirty?: boolean;
}

export interface BehavioralData {
  total_email_count: number;
  monthly_email_volume: number[];
  last_contact_date: string | null;
  days_since_last_contact: number | null;
  topic_distribution: Record<string, number>;
  primary_pain_point: string | null;
  sender_roles: Record<string, number>;
  peak_contact_days: string[];
  after_hours_ratio: number;
  analyzed_at: string;
}

export interface ScoreBreakdown {
  email_volume_score: number;
  email_volume_reason: string;
  recency_score: number;
  recency_reason: string;
  pain_signals_score: number;
  pain_signals_reason: string;
  firm_size_score: number;
  firm_size_reason: string;
  completeness_score: number;
  completeness_reason: string;
  total: number;
  scored_at: string | null;
}

export interface VendorStackEntry {
  vendor: string;
  source: string;
  confidence?: string;
  known?: boolean;
  evidence?: string;
}

export interface PifAddress {
  street?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  country?: string;
  source?: string;
  source_url?: string;
  [key: string]: unknown;
}

export interface PifInfoResponse {
  id: string;
  firm_name: string;
  entity_type: string;
  manually_added: boolean;
  website: string | null;
  canonical_website: string | null;
  website_status: string | null;
  website_source: string | null;
  website_confidence: number | null;
  emails: string[];
  phones: string[];
  fax: string | null;
  addresses: Array<string | PifAddress>;
  contacts: PifContact[];
  first_contacted_precise_at: string | null;
  conversation_ids: string[];
  extraction_notes: string | null;
  leadership: LeadershipMember[] | null;
  research_data: ResearchData | null;
  research_status: string | null;
  last_researched_at: string | null;
  staff: StaffMember[] | null;
  staff_research_status: string | null;
  behavioral_data: BehavioralData | null;
  icp_score: number | null;
  icp_tier: string | null;
  score_breakdown: ScoreBreakdown | null;
  icp_scored_at: string | null;
  vendor_stack: VendorStackEntry[] | null;
  created_at: string;
  updated_at: string;
}

export interface PifInfoListResponse {
  items: PifInfoResponse[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ResearchStartResponse {
  pif_id: string;
  firm_name: string;
  task_id: string;
  status: string;
  message: string;
}

export interface FullEnrichmentStatusResponse {
  task_id: string;
  status: string;
  message: string;
  pif_id?: string | null;
  firm_name?: string | null;
  result?: Record<string, unknown> | null;
  current_stage?: string | null;
  progress_percent?: number;
  stages?: EnrichmentStage[];
  warning_count?: number;
  requested_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface ResearchStatusResponse {
  task_id: string;
  status: string;
  message: string;
  pif_id?: string | null;
  firm_name?: string | null;
  leadership?: LeadershipMember[] | null;
  staff?: StaffMember[] | null;
  research_data?: ResearchData | null;
  result?: Record<string, unknown> | null;
  current_stage?: string | null;
  progress_percent?: number;
  stages?: EnrichmentStage[];
  warning_count?: number;
}

export interface VendorDetectionStartResponse {
  pif_id: string;
  firm_name: string;
  task_id: string;
  status: string;
  message: string;
}

export interface BehaviorAnalysisResponse {
  message?: string;
  pif_id?: string;
  firm_name?: string;
  behavioral_data?: BehavioralData | null;
  result?: Record<string, unknown> | null;
}

export interface AuthResponse {
  authenticated: boolean;
  username: string;
}

export interface LogoutResponse {
  authenticated?: boolean;
  message?: string;
}

export type PifSortBy = "conversation_count" | "firm_name" | "updated_at" | "first_contacted_precise_at";
export type PifTier = "A" | "B" | "C" | "D";
export type PresenceFilter =
  | "any"
  | "has"
  | "missing"
  | "resolved"
  | "unresolved"
  | "completed"
  | "queued_or_running"
  | "failed";
export type PeopleSource = "leadership" | "staff" | "contacts" | "all";
export type LeaderFilter = "leader" | "non_leader" | "any";
export type EmailPresence = "has" | "missing" | "any";
export type ExportFormat = "json" | "csv";

export interface PifInfoListParams {
  search?: string;
  page?: number;
  page_size?: number;
  sort_by?: PifSortBy;
  research_status?: string;
  icp_tier?: PifTier;
  icp_tiers?: PifTier[];
  entity_type?: string;
  entity_types?: string[];
  recently_researched?: number;
  contact_email_min?: number;
  contact_email_max?: number;
  contact_email_ranges?: string[];
  staff_count_min?: number;
  staff_count_max?: number;
  staff_count_ranges?: string[];
  autorespond_window?: string;
  autorespond_type?: string;
  autorespond_types?: string[];
  website_presence?: "any" | "has" | "missing" | "resolved" | "unresolved";
  research_presence?: "any" | "completed" | "missing" | "queued_or_running" | "failed";
  research_presences?: string[];
  staff_presence?: "any" | "completed" | "missing" | "queued_or_running" | "failed";
  staff_presences?: string[];
  job_postings_presence?: "any" | "has" | "none" | "not_researched" | "queued_or_running" | "failed";
  job_postings_presences?: string[];
  job_posting_role?: "intake" | "marketing" | "case_operations" | "firm_operations" | "technology";
  job_posting_roles?: string[];
  job_posting_tag?: string;
  job_posting_tags?: string[];
  job_posting_query?: string;
  job_posted_within_days?: number;
  behavior_presence?: "any" | "has" | "missing";
  icp_presence?: "any" | "has" | "missing";
  vendor_presence?: "any" | "has" | "missing";
  vendor?: string;
  vendors?: string[];
  manually_added?: boolean;
  first_contacted_from?: string;
  first_contacted_to?: string;
  active_only?: boolean;
}

export interface PifVendorOption {
  vendor: string;
  label: string;
  count: number;
}

export interface PifVendorOptionsResponse {
  vendors: PifVendorOption[];
  total_vendors: number;
  total_firms: number;
}

export interface PifSyncResult {
  fetched?: number;
  created?: number;
  updated?: number;
  skipped?: number;
  pages?: number;
  aliases_touched?: number;
  total_reported?: number;
  synced_at?: string;
  full?: boolean;
  previous_watermark?: string | null;
  candidate_watermark?: string | null;
  watermark?: string | null;
  watermark_advanced?: boolean;
  stopped_by_limit_with_more?: boolean;
  items?: PifSyncItem[];
  items_truncated?: boolean;
  items_inferred?: boolean;
}

export interface PifSyncItem {
  firm_id: string;
  firm_name: string;
  status: "created" | "updated" | "skipped" | "synced" | string;
  canonical_website?: string | null;
  source_updated_at?: string | null;
  people_count?: number;
  aliases_touched?: number | null;
}

export interface PifSyncStatusResponse {
  total_firms: number;
  alias_count: number;
  watermark: string | null;
  last_synced_at: string | null;
  last_result: PifSyncResult;
  api_base: string;
}

export interface PifPeopleListParams {
  title?: string;
  titles?: string[];
  name?: string;
  firm?: string;
  vendor?: string;
  role_category?: string;
  role_categories?: string[];
  source?: PeopleSource;
  leader?: LeaderFilter;
  email_presence?: EmailPresence;
  page?: number;
  page_size?: number;
}

export interface SavedLeadSearchCriteria {
  name?: string;
  firm?: string;
  vendor?: string;
  titles?: string[];
  role_categories?: string[];
  source: PeopleSource;
  leader: LeaderFilter;
  email_presence: EmailPresence;
}

export interface SavedLeadSearch {
  id: string;
  name: string;
  view: "contacts";
  criteria: SavedLeadSearchCriteria;
  schema_version: number;
  created_by: string;
  updated_by: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface SavedFirmTriggerSearchCriteria {
  search?: string;
  sort_by: PifSortBy;
  icp_tier?: PifTier[];
  entity_type?: string[];
  recently_researched?: string;
  contact_email_range?: string[];
  staff_count_range?: string[];
  autorespond_window: string;
  autorespond_type?: string[];
  website_presence: NonNullable<PifInfoListParams["website_presence"]>;
  research_presence: string[];
  staff_presence: string[];
  job_postings_presence: string[];
  job_posting_role?: string[];
  job_posting_tag?: string[];
  job_posting_query?: string;
  job_posted_within_days?: string;
  behavior_presence: NonNullable<PifInfoListParams["behavior_presence"]>;
  icp_presence: NonNullable<PifInfoListParams["icp_presence"]>;
  vendor_presence: NonNullable<PifInfoListParams["vendor_presence"]>;
  vendor?: string[];
  record_origin: "any" | "manual" | "synced";
  first_contact_period: "any" | "last_1_month" | "last_6_months" | "custom";
  first_contacted_from?: string;
  first_contacted_to?: string;
  trigger_event_types: string[];
  trigger_categories: string[];
  trigger_within_days: string;
  trigger_min_score: string;
  trigger_min_confidence: string;
  trigger_match_mode: "any" | "all";
  priority_sort: "priority" | "newest" | "fit";
  active_only: boolean;
}

export interface SavedFirmTriggerSearch {
  id: string;
  name: string;
  view: "firms";
  criteria: SavedFirmTriggerSearchCriteria;
  schema_version: number;
  created_by: string;
  updated_by: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface FirmTriggerEvent {
  id: string;
  pif_id: string;
  event_type: string;
  category: string;
  title: string;
  summary: string | null;
  old_value: Record<string, unknown>;
  new_value: Record<string, unknown>;
  evidence: Array<{
    source?: string | null;
    source_url?: string | null;
    published_at?: string | null;
    excerpt?: string | null;
    confidence?: number | null;
  }>;
  source_date: string | null;
  detected_at: string | null;
  expires_at: string | null;
  confidence: number;
  severity: number;
  score: number;
  active: boolean;
}

export interface FirmResearchFreshness {
  module: string;
  status: string;
  last_attempt_at: string | null;
  last_success_at: string | null;
  next_due_at: string | null;
  fresh: boolean;
  failure_count: number;
  last_error: string | null;
}

export interface PriorityFirmResult {
  firm: {
    id: string;
    firm_name: string;
    entity_type: string;
    website: string | null;
    metro: string | null;
    staff_count: number;
    icp_score: number | null;
    icp_tier: string | null;
    leadership: LeadershipMember[];
    emails: string[];
    phones: string[];
  };
  fit_score: number;
  trigger_score: number;
  priority_score: number;
  latest_trigger_at: string;
  triggers: FirmTriggerEvent[];
  freshness: {
    fresh_modules: number;
    total_modules: number;
    percent: number;
    modules: FirmResearchFreshness[];
  };
  vendors: Array<{
    vendor: string;
    product: string;
    first_seen_at: string;
    last_seen_at: string;
    confidence: number;
  }>;
}

export interface PriorityFirmsListParams {
  search?: string;
  event_types?: string[];
  categories?: string[];
  within_days?: number;
  min_score?: number;
  min_confidence?: number;
  match_mode?: "any" | "all";
  icp_tiers?: string[];
  entity_types?: string[];
  staff_count_min?: number;
  staff_count_max?: number;
  staff_count_ranges?: string[];
  vendors?: string[];
  sort_by?: "priority" | "newest" | "fit";
  page?: number;
  page_size?: number;
}

export interface PriorityFirmsListResponse {
  items: PriorityFirmResult[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  within_days: number;
  generated_at: string;
}

export interface TriggerFilterOptions {
  categories: Array<{ value: string; count: number }>;
  event_types: Array<{ value: string; category: string; count: number }>;
}

export interface PifPersonResult {
  name: string;
  title: string;
  role_category?: string | null;
  source?: PeopleSource | string;
  firm_name?: string | null;
  firm_id?: string | null;
  email?: string | null;
  phone?: string | null;
  linkedin?: string | null;
  bio?: string | null;
  is_decision_maker?: boolean | null;
  updated_at?: string | null;
}

export interface PifPeopleListResponse {
  items: PifPersonResult[];
  total?: number;
  page?: number;
  page_size?: number;
  total_pages?: number;
}

export interface PifPeopleFilterOption {
  value: string;
  count: number;
}

export interface PifPeopleFilterOptionsResponse {
  titles: PifPeopleFilterOption[];
  roles: PifPeopleFilterOption[];
  total_titles: number;
  total_roles: number;
  total_people: number;
}

export interface DownloadedEmailtagExport {
  blob: Blob;
  filename: string;
}

export const ENTITY_TYPE_LABELS: Record<string, string> = {
  pi_law_firm: "PI Law Firm",
  medical_referring: "Medical Referring",
  medical_facility: "Medical Facility",
  insurance: "Insurance",
  funding: "Funding",
  collections: "Collections",
  legal_other: "Legal (Other)",
  administrative: "Administrative",
  patient_adjacent: "Patient Adjacent",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function extractDetail(payload: unknown): string | null {
  if (!isRecord(payload)) return null;
  const detail = payload.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(String).join(", ");
  const message = payload.message;
  return typeof message === "string" ? message : null;
}

function buildUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${EMAILTAG_BASE}${normalized}`;
}

function appendParams(
  path: string,
  params: Record<string, string | number | boolean | readonly string[] | undefined>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item) search.append(key, item);
      });
    } else {
      search.set(key, String(value));
    }
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

async function possibleFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers,
  });
  const contentType = response.headers.get("content-type") ?? "";
  const payload: unknown =
    contentType.includes("application/json") ? await response.json().catch(() => null) : null;

  if (response.status === 401) {
    throw new EmailtagAuthError(extractDetail(payload) ?? undefined);
  }
  if (!response.ok) {
    throw new EmailtagApiError({
      status: response.status,
      detail: extractDetail(payload) ?? `Possible OS request failed: ${response.status}`,
    });
  }

  return payload as T;
}

export async function emailtagFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type") && typeof init.body === "string") {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(buildUrl(path), {
    ...init,
    credentials: "include",
    headers,
  });

  const contentType = response.headers.get("content-type") ?? "";
  const payload: unknown =
    contentType.includes("application/json") ? await response.json().catch(() => null) : null;

  if (response.status === 401) {
    throw new EmailtagAuthError(extractDetail(payload) ?? undefined);
  }
  if (!response.ok) {
    throw new EmailtagApiError({
      status: response.status,
      detail: extractDetail(payload) ?? `EmailTag request failed: ${response.status}`,
    });
  }

  return payload as T;
}

export function loginEmailtag(username: string, password: string): Promise<AuthResponse> {
  return emailtagFetch<AuthResponse>("/pifstats-auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function checkEmailtagAuth(): Promise<AuthResponse> {
  return emailtagFetch<AuthResponse>("/pifstats-auth/check");
}

export function logoutEmailtag(): Promise<LogoutResponse> {
  return emailtagFetch<LogoutResponse>("/pifstats-auth/logout", { method: "POST" });
}

export function listPifInfo(params: PifInfoListParams = {}): Promise<PifInfoListResponse> {
  return emailtagFetch<PifInfoListResponse>(
    // No trailing slash: the `/emailtag/pif-info` rewrite maps this to
    // emailtag's `/pif-info/` so FastAPI doesn't cross-origin 307-redirect.
    appendParams("/pif-info", {
      search: params.search,
      page: params.page ?? 1,
      page_size: params.page_size ?? 25,
      sort_by: params.sort_by,
      research_status: params.research_status,
      icp_tier: params.icp_tier,
      entity_type: params.entity_type,
      recently_researched: params.recently_researched,
      contact_email_min: params.contact_email_min,
      contact_email_max: params.contact_email_max,
      staff_count_min: params.staff_count_min,
      staff_count_max: params.staff_count_max,
      autorespond_window: params.autorespond_window,
      autorespond_type: params.autorespond_type,
      website_presence: params.website_presence,
      research_presence: params.research_presence,
      staff_presence: params.staff_presence,
      behavior_presence: params.behavior_presence,
      icp_presence: params.icp_presence,
      vendor_presence: params.vendor_presence,
      first_contacted_from: params.first_contacted_from,
      first_contacted_to: params.first_contacted_to,
      active_only: params.active_only,
    }),
  );
}

export function listMirroredPifInfo(params: PifInfoListParams = {}): Promise<PifInfoListResponse> {
  return possibleFetch<PifInfoListResponse>(
    appendParams("/api/pif/firms", {
      search: params.search,
      page: params.page ?? 1,
      page_size: params.page_size ?? 25,
      sort_by: params.sort_by,
      research_status: params.research_status,
      icp_tier: params.icp_tiers,
      entity_type: params.entity_types,
      recently_researched: params.recently_researched,
      contact_email_min: params.contact_email_min,
      contact_email_max: params.contact_email_max,
      contact_email_range: params.contact_email_ranges,
      staff_count_min: params.staff_count_min,
      staff_count_max: params.staff_count_max,
      staff_count_range: params.staff_count_ranges,
      autorespond_window: params.autorespond_window,
      autorespond_type: params.autorespond_types,
      website_presence: params.website_presence,
      research_presence: params.research_presences,
      staff_presence: params.staff_presences,
      job_postings_presence: params.job_postings_presences,
      job_posting_role: params.job_posting_roles,
      job_posting_tag: params.job_posting_tags,
      job_posting_query: params.job_posting_query,
      job_posted_within_days: params.job_posted_within_days,
      behavior_presence: params.behavior_presence,
      icp_presence: params.icp_presence,
      vendor_presence: params.vendor_presence,
      vendor: params.vendors,
      manually_added: params.manually_added,
      first_contacted_from: params.first_contacted_from,
      first_contacted_to: params.first_contacted_to,
      active_only: params.active_only,
    }),
  );
}

export function listPriorityPifFirms(
  params: PriorityFirmsListParams = {},
): Promise<PriorityFirmsListResponse> {
  return possibleFetch<PriorityFirmsListResponse>(
    appendParams("/api/pif/priority-firms", {
      search: params.search,
      event_type: params.event_types,
      category: params.categories,
      within_days: params.within_days ?? 30,
      min_score: params.min_score,
      min_confidence: params.min_confidence,
      match_mode: params.match_mode,
      icp_tier: params.icp_tiers,
      entity_type: params.entity_types,
      staff_count_min: params.staff_count_min,
      staff_count_max: params.staff_count_max,
      staff_count_range: params.staff_count_ranges,
      vendor: params.vendors,
      sort_by: params.sort_by,
      page: params.page ?? 1,
      page_size: params.page_size ?? 25,
    }),
  );
}

export function getPifTriggerOptions(): Promise<TriggerFilterOptions> {
  return possibleFetch<TriggerFilterOptions>("/api/pif/trigger-options");
}

export function getPifFirmTriggers(pifId: string): Promise<{
  pif_id: string;
  firm_name: string;
  events: FirmTriggerEvent[];
  research_freshness: FirmResearchFreshness[];
  vendor_history: Array<Record<string, unknown>>;
}> {
  return possibleFetch(`/api/pif/firms/${encodeURIComponent(pifId)}/triggers`);
}

export function listMirroredPifJobPostings(
  params: PifJobPostingsListParams = {},
): Promise<PifJobPostingsListResponse> {
  return possibleFetch<PifJobPostingsListResponse>(
    appendParams("/api/pif/job-postings", {
      search: params.search,
      role_category: params.role_category,
      trigger_tag: params.trigger_tag,
      technology: params.technology,
      gtm_relevance: params.gtm_relevance,
      remote_scope: params.remote_scope,
      contract_status: params.contract_status,
      global_remote: params.global_remote,
      posted_within_days: params.posted_within_days,
      order: params.order,
      page: params.page ?? 1,
      page_size: params.page_size ?? 25,
    }),
  );
}

export function getPifJobResearchDailyStats(days = 14): Promise<PifJobResearchDailyStatsResponse> {
  return possibleFetch<PifJobResearchDailyStatsResponse>(
    appendParams("/api/pif/job-postings/daily-stats", { days }),
  );
}

export function listPifVendors(): Promise<PifVendorOptionsResponse> {
  return possibleFetch<PifVendorOptionsResponse>("/api/pif/vendors");
}

export function getPifSyncStatus(): Promise<PifSyncStatusResponse> {
  return possibleFetch<PifSyncStatusResponse>("/api/pif/sync-status");
}

export function getFirm(pifId: string): Promise<PifInfoResponse> {
  return emailtagFetch<PifInfoResponse>(`/pif-info/${encodeURIComponent(pifId)}`);
}

export function getMirroredFirm(pifId: string): Promise<PifInfoResponse> {
  return possibleFetch<PifInfoResponse>(`/api/pif/firms/${encodeURIComponent(pifId)}`);
}

export function getCareerSearchStatus(): Promise<{
  schedule_enabled: boolean;
  next_due_at: string | null;
  config: { local_time: string; timezone: string };
  runs: { id: string; status: string; started_at: string; result: { new_jobs: number; verified: number; errors: { error: string }[]; candidate_rejections?: { source_url?: string; reason: string }[] } }[];
}> {
  return possibleFetch("/api/pif/career-search/status");
}

export function getFirmSitemapHistory(pifId: string): Promise<SitemapHistoryResponse> {
  return possibleFetch<SitemapHistoryResponse>(
    `/api/pif/firms/${encodeURIComponent(pifId)}/sitemap-history`,
  );
}

export async function listPifPeople(params: PifPeopleListParams = {}): Promise<PifPeopleListResponse> {
  return possibleFetch<PifPeopleListResponse>(
    appendParams("/api/pif/people", {
      title: params.titles?.length ? params.titles : params.title,
      name: params.name,
      firm: params.firm,
      vendor: params.vendor,
      role_category: params.role_categories?.length ? params.role_categories : params.role_category,
      source: params.source,
      leader: params.leader,
      email_presence: params.email_presence,
      page: params.page ?? 1,
      page_size: params.page_size ?? 25,
    }),
  );
}

export function listSavedLeadSearches(): Promise<{ saved_searches: SavedLeadSearch[] }> {
  return possibleFetch<{ saved_searches: SavedLeadSearch[] }>(
    "/api/pif/saved-searches?view=contacts",
  );
}

export function createSavedLeadSearch(input: {
  name: string;
  criteria: SavedLeadSearchCriteria;
}): Promise<{ saved_search: SavedLeadSearch }> {
  return possibleFetch<{ saved_search: SavedLeadSearch }>("/api/pif/saved-searches", {
    method: "POST",
    body: JSON.stringify({ ...input, view: "contacts" }),
  });
}

export function updateSavedLeadSearch(
  id: string,
  input: { name?: string; criteria?: SavedLeadSearchCriteria },
): Promise<{ saved_search: SavedLeadSearch }> {
  return possibleFetch<{ saved_search: SavedLeadSearch }>(
    `/api/pif/saved-searches/${encodeURIComponent(id)}`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}

export function deleteSavedLeadSearch(id: string): Promise<{ deleted: boolean; id: string }> {
  return possibleFetch<{ deleted: boolean; id: string }>(
    `/api/pif/saved-searches/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
}

export function listSavedFirmTriggerSearches(): Promise<{ saved_searches: SavedFirmTriggerSearch[] }> {
  return possibleFetch<{ saved_searches: SavedFirmTriggerSearch[] }>(
    "/api/pif/saved-searches?view=firms",
  );
}

export function createSavedFirmTriggerSearch(input: {
  name: string;
  criteria: SavedFirmTriggerSearchCriteria;
}): Promise<{ saved_search: SavedFirmTriggerSearch }> {
  return possibleFetch<{ saved_search: SavedFirmTriggerSearch }>("/api/pif/saved-searches", {
    method: "POST",
    body: JSON.stringify({ ...input, view: "firms" }),
  });
}

export function updateSavedFirmTriggerSearch(
  id: string,
  input: { name?: string; criteria?: SavedFirmTriggerSearchCriteria },
): Promise<{ saved_search: SavedFirmTriggerSearch }> {
  return possibleFetch<{ saved_search: SavedFirmTriggerSearch }>(
    `/api/pif/saved-searches/${encodeURIComponent(id)}`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}

export function deleteSavedFirmTriggerSearch(id: string): Promise<{ deleted: boolean; id: string }> {
  return deleteSavedLeadSearch(id);
}

export function getPifPeopleFilterOptions(): Promise<PifPeopleFilterOptionsResponse> {
  return possibleFetch<PifPeopleFilterOptionsResponse>("/api/pif/people/filter-options");
}

function filenameFromContentDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const utfMatch = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utfMatch?.[1]) return decodeURIComponent(utfMatch[1].replace(/"/g, ""));
  const plainMatch = header.match(/filename="?([^";]+)"?/i);
  return plainMatch?.[1] ?? fallback;
}

export async function downloadEmailtagExport(options: {
  format: ExportFormat;
  pifId?: string;
  include_merged?: boolean;
}): Promise<DownloadedEmailtagExport> {
  const path = options.pifId
    ? appendParams(`/pif-info/${encodeURIComponent(options.pifId)}/export`, {
        format: options.format,
      })
    : appendParams("/pif-info/export", {
        format: options.format,
        include_merged: options.include_merged ?? false,
      });

  const response = await fetch(buildUrl(path), {
    credentials: "include",
    headers: { Accept: options.format === "json" ? "application/json" : "text/csv" },
  });

  if (response.status === 401) throw new EmailtagAuthError();
  if (!response.ok) {
    throw new EmailtagApiError({
      status: response.status,
      detail: `EmailTag export failed: ${response.status}`,
    });
  }

  const blob = await response.blob();
  return {
    blob,
    filename: filenameFromContentDisposition(
      response.headers.get("content-disposition"),
      options.pifId ? `emailtag-${options.pifId}.${options.format}` : `emailtag-firms.${options.format}`,
    ),
  };
}

export function startFullEnrichment(pifId: string): Promise<ResearchStartResponse> {
  return possibleFetch<ResearchStartResponse>(
    `/api/pif/firms/${encodeURIComponent(pifId)}/research`,
    { method: "POST" },
  );
}

export function getFullEnrichmentStatus(taskId: string): Promise<FullEnrichmentStatusResponse> {
  return possibleFetch<FullEnrichmentStatusResponse>(
    `/api/pif/enrichment-status/${encodeURIComponent(taskId)}`,
  );
}

export function startResearch(pifId: string): Promise<ResearchStartResponse> {
  return startFullEnrichment(pifId);
}

export function startJobPostingsResearch(pifId: string): Promise<ResearchStartResponse> {
  return possibleFetch<ResearchStartResponse>(
    `/api/pif/firms/${encodeURIComponent(pifId)}/research-job-postings`,
    { method: "POST" },
  );
}

export function getProxiedResearchStatus(taskId: string): Promise<ResearchStatusResponse> {
  return possibleFetch<ResearchStatusResponse>(
    `/api/pif/research-status/${encodeURIComponent(taskId)}`,
  );
}

export function startStaffResearch(pifId: string): Promise<ResearchStartResponse> {
  return startFullEnrichment(pifId);
}

export function getResearchStatus(taskId: string): Promise<ResearchStatusResponse> {
  return possibleFetch<ResearchStatusResponse>(
    `/api/pif/enrichment-status/${encodeURIComponent(taskId)}`,
  );
}

export function detectVendors(pifId: string): Promise<VendorDetectionStartResponse> {
  return startFullEnrichment(pifId);
}

export function analyzeBehavior(pifId: string): Promise<BehaviorAnalysisResponse> {
  return possibleFetch<BehaviorAnalysisResponse>(
    `/api/pif/firms/${encodeURIComponent(pifId)}/analyze-behavior`,
    { method: "POST" },
  );
}

export function scoreFirm(pifId: string): Promise<PifInfoResponse> {
  return possibleFetch<PifInfoResponse>(
    `/api/pif/firms/${encodeURIComponent(pifId)}/score`,
    { method: "POST" },
  );
}

// ---------------------------------------------------------------------------
// Legacy /firms compatibility shims (replacing the removed lib/pifstats.ts).
// The existing /firms pages were built against the old pifstats client, which
// hit emailtag cross-origin with no auth. These thin wrappers map those call
// signatures onto this authenticated same-origin proxy client so /firms keeps
// working (and now shares the pifstats_session cookie) after pifstats.ts is
// deleted. Prefer the primary exports above for new code.
// ---------------------------------------------------------------------------

/** @deprecated legacy /firms alias — use PifInfoResponse. */
export type PifFirm = PifInfoResponse;
/** @deprecated legacy /firms alias — use LeadershipMember. */
export type PifLeader = LeadershipMember;

/** @deprecated legacy /firms alias — use listPifInfo. */
export function listPifFirms(params: {
  search?: string;
  page?: number;
  page_size?: number;
  sort?: string;
  order?: string;
  research_status?: string;
  icp_tier?: string;
  recently_researched?: number;
}): Promise<PifInfoListResponse> {
  return listPifInfo({
    search: params.search,
    page: params.page,
    page_size: params.page_size,
    sort_by: params.sort as PifSortBy | undefined,
    research_status: params.research_status,
    icp_tier: params.icp_tier as PifTier | undefined,
    recently_researched: params.recently_researched,
  });
}

/** @deprecated legacy /firms alias — use getFirm. */
export const getPifFirm = getFirm;
/** @deprecated legacy /firms alias — use startResearch. */
export const triggerResearch = startResearch;
/** @deprecated legacy /firms alias — use startStaffResearch. */
export const triggerStaffResearch = startStaffResearch;
/** @deprecated legacy /firms alias — use analyzeBehavior. */
export const triggerBehaviorAnalysis = analyzeBehavior;
/** @deprecated legacy /firms alias — use getResearchStatus. */
export const pollResearchStatus = getResearchStatus;

/** @deprecated legacy /firms alias — ICP score trigger (POST /pif-info/{id}/score). */
export const triggerIcpScore = scoreFirm;

/** @deprecated legacy /firms alias — free-text people search. */
export async function searchPifPeople(
  query: string,
  source: PeopleSource | string = "all",
): Promise<PifPersonResult[]> {
  const path = appendParams("/pif-info/people", { search: query, source });
  const data = await emailtagFetch<PifPeopleListResponse | PifPersonResult[]>(path);
  return Array.isArray(data) ? data : data.items ?? [];
}
