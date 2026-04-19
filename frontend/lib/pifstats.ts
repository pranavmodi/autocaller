/**
 * PIF Stats API client — connects to the email processing platform
 * at emailprocessing.mediflow360.com for firm intelligence.
 */

const PIF_BASE = "https://emailprocessing.mediflow360.com/api/v1/pif-info";

export interface PifContact {
  name: string;
  title: string;
  email: string | null;
  phone: string;
  extension: string;
}

export interface PifLeader {
  name: string;
  title: string;
  email: string | null;
  phone: string | null;
  linkedin: string | null;
  bio: string | null;
  image_url: string | null;
}

export interface PifBehavior {
  analyzed_at: string;
  total_email_count: number;
  monthly_email_volume: number[];
  days_since_last_contact: number;
  last_contact_date: string;
  after_hours_ratio: number;
  peak_contact_days: string[];
  primary_pain_point: string;
  topic_distribution: Record<string, number>;
  sender_roles: Record<string, number>;
}

export interface PifScoreBreakdown {
  total: number;
  scored_at: string;
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
}

export interface PifResearch {
  firm_size: string;
  founded_year: string;
  practice_areas: string[];
  notable_cases: string[];
  awards_recognition: string[];
  office_locations: string[];
  bar_associations: string[];
  social_media: Record<string, string>;
  additional_info: string;
  sources: string[];
}

export interface PifFirm {
  id: string;
  firm_name: string;
  website: string | null;
  emails: string[];
  phones: string[];
  fax: string | null;
  addresses: string[];
  contacts: PifContact[];
  leadership: PifLeader[];
  staff: PifLeader[] | null;
  research_data: PifResearch | null;
  research_status: string | null;
  staff_research_status: string | null;
  behavioral_data: PifBehavior | null;
  icp_score: number | null;
  icp_tier: string | null;
  score_breakdown: PifScoreBreakdown | null;
  conversation_ids: string[];
  extraction_notes: string | null;
  last_researched_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PifListResponse {
  items: PifFirm[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export async function listPifFirms(params: {
  search?: string;
  page?: number;
  page_size?: number;
  sort?: string;
  order?: string;
  research_status?: string;
  icp_tier?: string;
}): Promise<PifListResponse> {
  const qs = new URLSearchParams();
  if (params.search) qs.set("search", params.search);
  qs.set("page", String(params.page ?? 1));
  qs.set("page_size", String(params.page_size ?? 25));
  if (params.sort) qs.set("sort", params.sort);
  if (params.order) qs.set("order", params.order);
  if (params.research_status) qs.set("research_status", params.research_status);
  if (params.icp_tier) qs.set("icp_tier", params.icp_tier);
  const resp = await fetch(`${PIF_BASE}/?${qs}`);
  if (!resp.ok) throw new Error(`PIF list failed: ${resp.status}`);
  return resp.json();
}

export async function getPifFirm(pifId: string): Promise<PifFirm> {
  const resp = await fetch(`${PIF_BASE}/${pifId}`);
  if (!resp.ok) throw new Error(`PIF firm fetch failed: ${resp.status}`);
  return resp.json();
}

export interface PifPersonResult extends PifLeader {
  firm_name?: string;
  firm_id?: string;
  source?: string;
  role_category?: string;
}

// --- Research triggers ---

export interface ResearchTriggerResponse {
  pif_id: string;
  firm_name: string;
  task_id: string;
  status: string;
  message: string;
}

export interface ResearchStatusResponse {
  pif_id: string;
  firm_name: string;
  task_id: string;
  status: string; // "queued" | "started" | "completed" | "failed"
  leadership: PifLeader[] | null;
  research_data: PifResearch | null;
  message: string;
}

export async function triggerResearch(pifId: string): Promise<ResearchTriggerResponse> {
  const resp = await fetch(`${PIF_BASE}/${pifId}/research`, { method: "POST" });
  if (!resp.ok) throw new Error(`Research trigger failed: ${resp.status}`);
  return resp.json();
}

export async function triggerStaffResearch(pifId: string): Promise<ResearchTriggerResponse> {
  const resp = await fetch(`${PIF_BASE}/${pifId}/research-staff`, { method: "POST" });
  if (!resp.ok) throw new Error(`Staff research trigger failed: ${resp.status}`);
  return resp.json();
}

export async function triggerBehaviorAnalysis(pifId: string): Promise<{ message: string }> {
  const resp = await fetch(`${PIF_BASE}/${pifId}/analyze-behavior`, { method: "POST" });
  if (!resp.ok) throw new Error(`Behavior analysis failed: ${resp.status}`);
  return resp.json();
}

export async function triggerIcpScore(pifId: string): Promise<PifFirm> {
  const resp = await fetch(`${PIF_BASE}/${pifId}/score`, { method: "POST" });
  if (!resp.ok) throw new Error(`ICP scoring failed: ${resp.status}`);
  return resp.json();
}

export async function pollResearchStatus(taskId: string): Promise<ResearchStatusResponse> {
  const resp = await fetch(`${PIF_BASE}/research-status/${taskId}`);
  if (!resp.ok) throw new Error(`Research status poll failed: ${resp.status}`);
  return resp.json();
}

export async function searchPifPeople(
  query: string,
  source = "all",
): Promise<PifPersonResult[]> {
  const params = new URLSearchParams({ search: query, source });
  const resp = await fetch(`${PIF_BASE}/people?${params}`);
  if (!resp.ok) throw new Error(`PIF people search failed: ${resp.status}`);
  const data = await resp.json();
  return Array.isArray(data) ? data : data.items ?? data.data ?? [];
}
