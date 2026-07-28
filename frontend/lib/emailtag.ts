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

export interface ResearchData {
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
  addresses: string[];
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
export type ExportFormat = "json" | "csv";

export interface PifInfoListParams {
  search?: string;
  page?: number;
  page_size?: number;
  sort_by?: PifSortBy;
  research_status?: string;
  icp_tier?: PifTier;
  entity_type?: string;
  recently_researched?: number;
  website_presence?: "any" | "has" | "missing" | "resolved" | "unresolved";
  research_presence?: "any" | "completed" | "missing" | "queued_or_running" | "failed";
  staff_presence?: "any" | "completed" | "missing" | "queued_or_running" | "failed";
  behavior_presence?: "any" | "has" | "missing";
  icp_presence?: "any" | "has" | "missing";
  vendor_presence?: "any" | "has" | "missing";
  vendor?: string;
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
  name?: string;
  firm?: string;
  vendor?: string;
  role_category?: string;
  source?: PeopleSource;
  leader?: LeaderFilter;
  page?: number;
  page_size?: number;
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

function appendParams(path: string, params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

async function possibleFetch<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { Accept: "application/json" },
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
      icp_tier: params.icp_tier,
      entity_type: params.entity_type,
      recently_researched: params.recently_researched,
      website_presence: params.website_presence,
      research_presence: params.research_presence,
      staff_presence: params.staff_presence,
      behavior_presence: params.behavior_presence,
      icp_presence: params.icp_presence,
      vendor_presence: params.vendor_presence,
      vendor: params.vendor,
      manually_added: params.manually_added,
      first_contacted_from: params.first_contacted_from,
      first_contacted_to: params.first_contacted_to,
      active_only: params.active_only,
    }),
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

export async function listPifPeople(params: PifPeopleListParams = {}): Promise<PifPeopleListResponse> {
  return possibleFetch<PifPeopleListResponse>(
    appendParams("/api/pif/people", {
      title: params.title,
      name: params.name,
      firm: params.firm,
      vendor: params.vendor,
      role_category: params.role_category,
      source: params.source,
      leader: params.leader,
      page: params.page ?? 1,
      page_size: params.page_size ?? 25,
    }),
  );
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
  return emailtagFetch<ResearchStartResponse>(`/pif-info/${encodeURIComponent(pifId)}/enrich-all`, {
    method: "POST",
  });
}

export function getFullEnrichmentStatus(taskId: string): Promise<FullEnrichmentStatusResponse> {
  return emailtagFetch<FullEnrichmentStatusResponse>(
    `/pif-info/enrich-all/status/${encodeURIComponent(taskId)}`,
  );
}

export function startResearch(pifId: string): Promise<ResearchStartResponse> {
  return emailtagFetch<ResearchStartResponse>(`/pif-info/${encodeURIComponent(pifId)}/research`, {
    method: "POST",
  });
}

export function startStaffResearch(pifId: string): Promise<ResearchStartResponse> {
  return emailtagFetch<ResearchStartResponse>(
    `/pif-info/${encodeURIComponent(pifId)}/research-staff`,
    { method: "POST" },
  );
}

export function getResearchStatus(taskId: string): Promise<ResearchStatusResponse> {
  return emailtagFetch<ResearchStatusResponse>(
    `/pif-info/research-status/${encodeURIComponent(taskId)}`,
  );
}

export function detectVendors(pifId: string): Promise<VendorDetectionStartResponse> {
  return emailtagFetch<VendorDetectionStartResponse>(
    `/pif-info/${encodeURIComponent(pifId)}/detect-vendors`,
    { method: "POST" },
  );
}

export function analyzeBehavior(pifId: string): Promise<BehaviorAnalysisResponse> {
  return emailtagFetch<BehaviorAnalysisResponse>(
    `/pif-info/${encodeURIComponent(pifId)}/analyze-behavior`,
    { method: "POST" },
  );
}

export function scoreFirm(pifId: string): Promise<PifInfoResponse> {
  return emailtagFetch<PifInfoResponse>(
    `/pif-info/${encodeURIComponent(pifId)}/score`,
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
