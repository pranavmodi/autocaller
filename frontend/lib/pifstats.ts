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
  research_status: string;
  staff_research_status: string | null;
  behavioral_data: PifBehavior | null;
  icp_score: number | null;
  icp_tier: string | null;
  score_breakdown: PifScoreBreakdown | null;
  conversation_ids: string[];
  extraction_notes: string | null;
  created_at: string;
  updated_at: string;
}

export async function searchPifFirms(
  query: string,
  limit = 20,
): Promise<PifFirm[]> {
  const params = new URLSearchParams({ search: query, limit: String(limit) });
  const resp = await fetch(`${PIF_BASE}/?${params}`);
  if (!resp.ok) throw new Error(`PIF search failed: ${resp.status}`);
  const data = await resp.json();
  return Array.isArray(data) ? data : data.items ?? data.data ?? [];
}

export async function getPifFirm(pifId: string): Promise<PifFirm> {
  const resp = await fetch(`${PIF_BASE}/${pifId}`);
  if (!resp.ok) throw new Error(`PIF firm fetch failed: ${resp.status}`);
  return resp.json();
}

export async function listPifFirms(
  sort = "icp_score",
  order = "desc",
  limit = 50,
): Promise<PifFirm[]> {
  const params = new URLSearchParams({
    sort,
    order,
    limit: String(limit),
  });
  const resp = await fetch(`${PIF_BASE}/?${params}`);
  if (!resp.ok) throw new Error(`PIF list failed: ${resp.status}`);
  const data = await resp.json();
  return Array.isArray(data) ? data : data.items ?? data.data ?? [];
}

export async function searchPifPeople(
  query: string,
  source = "all",
): Promise<PifLeader[]> {
  const params = new URLSearchParams({ search: query, source });
  const resp = await fetch(`${PIF_BASE}/people?${params}`);
  if (!resp.ok) throw new Error(`PIF people search failed: ${resp.status}`);
  const data = await resp.json();
  return Array.isArray(data) ? data : data.items ?? data.data ?? [];
}
