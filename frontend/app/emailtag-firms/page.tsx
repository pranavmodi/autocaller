"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import type React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  BarChart3,
  Bookmark,
  Briefcase,
  Building2,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  Database,
  Download,
  ExternalLink,
  FileJson,
  Filter,
  Globe,
  Loader2,
  Linkedin,
  Mail,
  MapPin,
  PanelRightOpen,
  PhoneCall,
  Play,
  RefreshCw,
  Search,
  Save,
  SlidersHorizontal,
  Sparkles,
  Star,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { CommsTable } from "@/components/CommsTable";
import { JobApplicationControls } from "@/components/JobApplicationControls";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { jobAgentRequest, type Candidate, type JobAgentConfig } from "@/lib/job-agent";
import {
  deleteFirm,
  getFirmCalls,
  getFirmReviews,
  getFirmReviewResearchStatus,
  getReviewCorpusProgress,
  listFirmCommunications,
  putFirmReviews,
  startFirmReviewResearch,
  type DeleteFirmResult,
  type FirmReviews,
  type ReviewCorpusProgress,
} from "@/lib/api";
import {
  ENTITY_TYPE_LABELS,
  EmailtagAuthError,
  analyzeBehavior,
  createSavedFirmTriggerSearch,
  createSavedLeadSearch,
  deleteSavedFirmTriggerSearch,
  deleteSavedLeadSearch,
  detectVendors,
  downloadEmailtagExport,
  getFullEnrichmentStatus,
  getCareerSearchStatus,
  getFirmSitemapHistory,
  getMirroredFirm,
  getPifJobResearchDailyStats,
  getPifTriggerOptions,
  getPifPeopleFilterOptions,
  getPifSyncStatus,
  getResearchStatus,
  getProxiedResearchStatus,
  listMirroredPifInfo,
  listMirroredPifJobPostings,
  listPriorityPifFirms,
  listPifPeople,
  listPifVendors,
  listSavedFirmTriggerSearches,
  listSavedLeadSearches,
  scoreFirm,
  startFullEnrichment,
  startJobPostingsResearch,
  startResearch,
  startStaffResearch,
  updateSavedLeadSearch,
  updateSavedFirmTriggerSearch,
  type EmailPresence,
  type AIAdoptionPosture,
  type ExportFormat,
  type PifInfoListParams,
  type PifInfoListResponse,
  type PifInfoResponse,
  type SitemapMonitorSummary,
  type PifJobPostingResult,
  type PifJobPostingsListParams,
  type PifJobResearchDailyStat,
  type JobPostingsResearch,
  type PriorityFirmResult,
  type PriorityFirmsListParams,
  type PriorityFirmsListResponse,
  type PifAddress,
  type PifPeopleListParams,
  type PifPeopleFilterOption,
  type PifPersonResult,
  type ResearchStartResponse,
  type PifSyncStatusResponse,
  type PifTier,
  type PifVendorOption,
  type SavedLeadSearch,
  type SavedLeadSearchCriteria,
  type SavedFirmTriggerSearch,
  type SavedFirmTriggerSearchCriteria,
  type TriggerFilterOptions,
} from "@/lib/emailtag";

const PAGE_SIZE = 25;
const BATCH_PAGE_SIZE = 100;
const PRESENCE = ["any", "has", "missing"] as const;
const STATUS_PRESENCE = ["any", "completed", "missing", "queued_or_running", "failed"] as const;
const WEBSITE_PRESENCE = ["any", "has", "missing", "resolved", "unresolved"] as const;
const TERMINAL_TASK_STATUSES = new Set(["completed", "failed", "error", "success"]);

type SortBy = NonNullable<PifInfoListParams["sort_by"]>;
type WebsitePresence = NonNullable<PifInfoListParams["website_presence"]>;
type SimplePresence = NonNullable<PifInfoListParams["behavior_presence"]>;
type PeopleSource = NonNullable<PifPeopleListParams["source"]>;
type LeaderFilter = NonNullable<PifPeopleListParams["leader"]>;
type LeadsView = "priority" | "firms" | "contacts" | "job_listings";
type FirstContactPeriod = "any" | "last_1_month" | "last_6_months" | "custom";
type RecordOrigin = "any" | "manual" | "synced";
type WorkflowStepState = "completed" | "running" | "failed" | "waiting" | "skipped";

interface WorkflowStepInfo {
  label: string;
  detail: string;
  state: WorkflowStepState;
}

interface BatchResearchRow {
  pif_id: string;
  firm_name: string;
  task_id: string | null;
  status: string;
  message: string;
}

interface BatchResearchRun {
  requested: number;
  rows: BatchResearchRow[];
}

interface ContactLookupOption {
  value: string;
  label: string;
  secondary?: string;
}

type ExtractedQuote = {
  quote: string;
  reviewer_name: string | null;
  review_date: string | null;
  star_rating: number | null;
  confidence: number;
};

type ExtractedReviews = {
  extractor_version?: string;
  extracted_at?: string;
  pain_points?: Record<string, ExtractedQuote[]>;
  absent_pain_points?: Record<string, string>;
};

interface FiltersState {
  search: string;
  sort_by: SortBy;
  icp_tier: PifTier[];
  entity_type: string[];
  recently_researched: string;
  contact_email_range: string[];
  staff_count_range: string[];
  autorespond_window: string;
  autorespond_type: string[];
  website_presence: WebsitePresence;
  research_presence: string[];
  staff_presence: string[];
  job_postings_presence: string[];
  job_posting_role: string[];
  job_posting_tag: string[];
  job_posting_query: string;
  job_posted_within_days: string;
  behavior_presence: SimplePresence;
  icp_presence: SimplePresence;
  vendor_presence: SimplePresence;
  vendor: string[];
  record_origin: RecordOrigin;
  first_contact_period: FirstContactPeriod;
  first_contacted_from: string;
  first_contacted_to: string;
  trigger_event_types: string[];
  trigger_categories: string[];
  trigger_within_days: string;
  trigger_min_score: string;
  trigger_min_confidence: string;
  trigger_match_mode: "any" | "all";
  priority_sort: "priority" | "newest" | "fit";
  active_only: boolean;
}

const DEFAULT_FILTERS: FiltersState = {
  search: "",
  sort_by: "updated_at",
  icp_tier: [],
  entity_type: [],
  recently_researched: "",
  contact_email_range: [],
  staff_count_range: [],
  autorespond_window: "any",
  autorespond_type: [],
  website_presence: "any",
  research_presence: [],
  staff_presence: [],
  job_postings_presence: [],
  job_posting_role: [],
  job_posting_tag: [],
  job_posting_query: "",
  job_posted_within_days: "",
  behavior_presence: "any",
  icp_presence: "any",
  vendor_presence: "any",
  vendor: [],
  record_origin: "any",
  first_contact_period: "any",
  first_contacted_from: "",
  first_contacted_to: "",
  trigger_event_types: [],
  trigger_categories: [],
  trigger_within_days: "30",
  trigger_min_score: "0",
  trigger_min_confidence: "0",
  trigger_match_mode: "any",
  priority_sort: "priority",
  active_only: true,
};

const CONTACT_QUERY_KEYS = [
  "contact_name",
  "contact_firm",
  "vendor",
  "title",
  "role",
  "source",
  "leader",
  "email",
  "contact_page",
  "contact_page_size",
] as const;

function peopleFiltersFromParams(params: URLSearchParams): PifPeopleListParams {
  const page = Math.max(1, Number(params.get("contact_page")) || 1);
  const pageSize = Math.max(1, Math.min(100, Number(params.get("contact_page_size")) || 25));
  const titles = params.getAll("title").filter(Boolean);
  const roles = params.getAll("role").filter(Boolean);
  return {
    name: params.get("contact_name") || undefined,
    firm: params.get("contact_firm") || undefined,
    vendor: params.get("vendor") || undefined,
    titles: titles.length ? titles : undefined,
    role_categories: roles.length ? roles : undefined,
    source: (params.get("source") as PeopleSource | null) ?? "all",
    leader: (params.get("leader") as LeaderFilter | null) ?? "any",
    email_presence: (params.get("email") as EmailPresence | null) ?? "any",
    page,
    page_size: pageSize,
  };
}

function writePeopleFilters(params: URLSearchParams, filters: PifPeopleListParams) {
  CONTACT_QUERY_KEYS.forEach((key) => params.delete(key));
  if (filters.name) params.set("contact_name", filters.name);
  if (filters.firm) params.set("contact_firm", filters.firm);
  if (filters.vendor) params.set("vendor", filters.vendor);
  (filters.titles ?? (filters.title ? [filters.title] : [])).forEach((value) => params.append("title", value));
  (filters.role_categories ?? (filters.role_category ? [filters.role_category] : [])).forEach((value) => params.append("role", value));
  if (filters.source && filters.source !== "all") params.set("source", filters.source);
  if (filters.leader && filters.leader !== "any") params.set("leader", filters.leader);
  if (filters.email_presence && filters.email_presence !== "any") params.set("email", filters.email_presence);
  if ((filters.page ?? 1) > 1) params.set("contact_page", String(filters.page));
  if ((filters.page_size ?? 25) !== 25) params.set("contact_page_size", String(filters.page_size));
}

function criteriaFromPeopleFilters(filters: PifPeopleListParams): SavedLeadSearchCriteria {
  return {
    name: filters.name || undefined,
    firm: filters.firm || undefined,
    vendor: filters.vendor || undefined,
    titles: filters.titles ?? (filters.title ? [filters.title] : []),
    role_categories: filters.role_categories ?? (filters.role_category ? [filters.role_category] : []),
    source: filters.source ?? "all",
    leader: filters.leader ?? "any",
    email_presence: filters.email_presence ?? "any",
  };
}

function peopleFiltersFromSavedSearch(
  search: SavedLeadSearch,
  pageSize: number,
): PifPeopleListParams {
  return {
    ...search.criteria,
    page: 1,
    page_size: pageSize,
  };
}

function isAuthError(error: unknown): error is EmailtagAuthError {
  return error instanceof EmailtagAuthError;
}

function tierColor(tier: string | null) {
  if (tier === "A") return "bg-emerald-100 text-emerald-800";
  if (tier === "B") return "bg-sky-100 text-sky-800";
  if (tier === "C") return "bg-amber-100 text-amber-800";
  if (tier === "D") return "bg-rose-100 text-rose-800";
  return "bg-neutral-100 text-neutral-500";
}

function statusColor(status: string | null) {
  if (status === "completed") return "bg-emerald-50 text-emerald-700";
  if (status === "failed" || status === "error") return "bg-rose-50 text-rose-700";
  if (status === "queued" || status === "running" || status === "started") {
    return "bg-amber-50 text-amber-700";
  }
  return "bg-neutral-100 text-neutral-500";
}

function websiteStatusColor(status: string | null) {
  if (status === "resolved") return "bg-emerald-50 text-emerald-700";
  if (status === "unresolved" || status === "missing") return "bg-amber-50 text-amber-700";
  return "bg-neutral-100 text-neutral-500";
}

function display(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatDateOnly(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function formatLabel(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function safeWebsiteUrl(value: string | null) {
  if (!value) return null;
  return value.startsWith("http://") || value.startsWith("https://") ? value : `https://${value}`;
}

function safeLinkedInUrl(value: string | null | undefined) {
  const trimmed = value?.trim();
  if (!trimmed) return null;
  const candidate = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed.replace(/^\/+/, "")}`;
  try {
    const url = new URL(candidate);
    const hostname = url.hostname.toLowerCase();
    if (hostname === "linkedin.com" || hostname.endsWith(".linkedin.com")) return url.toString();
  } catch {
    return null;
  }
  return null;
}

function linkedInSearchUrl(person: { name?: string | null; firm_name?: string | null }) {
  const query = [
    "site:linkedin.com/in",
    person.name,
    person.firm_name,
  ].filter(Boolean).join(" ");
  return `https://www.google.com/search?q=${encodeURIComponent(query)}`;
}

function frontConversationUrl(conversationId: string) {
  return `https://app.frontapp.com/open/${encodeURIComponent(conversationId)}`;
}

function emailtagFirmHref(pifId: string) {
  return `/emailtag-firms?firm=${encodeURIComponent(pifId)}`;
}

function painLabel(pain: string) {
  return pain
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function parseExtractedReviews(blob: string | null | undefined): ExtractedReviews | null {
  if (!blob) return null;
  const match = blob.match(/<!--\s*EXTRACTED v\d+\s*([\s\S]*?)\s*-->/);
  if (!match) return null;
  try {
    const parsed = JSON.parse(match[1]);
    return parsed && typeof parsed === "object" ? (parsed as ExtractedReviews) : null;
  } catch {
    return null;
  }
}

const STATE_NAMES: Record<string, string> = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas",
  CA: "California", CO: "Colorado", CT: "Connecticut", DE: "Delaware",
  FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho",
  IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas",
  KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland",
  MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi",
  MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada",
  NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
  NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma",
  OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina",
  SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah",
  VT: "Vermont", VA: "Virginia", WA: "Washington", WV: "West Virginia",
  WI: "Wisconsin", WY: "Wyoming", DC: "District of Columbia",
};

function formatAddress(address: string | PifAddress | null | undefined): string {
  if (!address) return "";
  if (typeof address === "string") return address.trim();
  return [address.street, address.city, address.state, address.postal_code, address.country]
    .filter((part): part is string => typeof part === "string" && Boolean(part.trim()))
    .map((part) => part.trim())
    .join(", ");
}

function extractState(address: string | PifAddress | null | undefined): string {
  if (!address) return "";
  if (typeof address !== "string" && typeof address.state === "string") {
    const state = address.state.trim();
    return STATE_NAMES[state.toUpperCase()] ?? state;
  }
  const formatted = formatAddress(address);
  const match = formatted.match(/\b([A-Z]{2})\b\s*\d{5}(?:-\d{4})?\b/);
  const abbreviation = (match?.[1] ?? "").toUpperCase();
  return STATE_NAMES[abbreviation] ?? "";
}

function outcomeColor(outcome: string): string {
  switch (outcome) {
    case "demo_scheduled":
      return "bg-emerald-100 text-emerald-800";
    case "callback_requested":
      return "bg-sky-100 text-sky-800";
    case "voicemail":
      return "bg-violet-100 text-violet-800";
    case "gatekeeper_only":
      return "bg-amber-100 text-amber-800";
    case "not_interested":
      return "bg-rose-100 text-rose-800";
    case "wrong_number":
      return "bg-neutral-200 text-neutral-700";
    case "completed":
      return "bg-neutral-100 text-neutral-700";
    case "failed":
    case "disconnected":
      return "bg-neutral-100 text-neutral-500";
    default:
      return "bg-neutral-100 text-neutral-600";
  }
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function isWorkflowRunning(status: string | null | undefined) {
  return Boolean(status && !TERMINAL_TASK_STATUSES.has(status));
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : error ? "Request failed" : undefined;
}

function getRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : null;
}

function persistedEnrichmentTaskId(firm: PifInfoResponse) {
  const state = firm.research_data?.local_enrichment;
  return typeof state?.task_id === "string" && state.task_id ? state.task_id : null;
}

function firmContactCount(firm: PifInfoResponse) {
  return (firm.contacts?.length ?? 0) + (firm.leadership?.length ?? 0) + (firm.staff?.length ?? 0);
}

function visibleRange(data: PifInfoListResponse | undefined) {
  if (!data || data.total === 0) return "0";
  const start = (data.page - 1) * data.page_size + 1;
  const end = Math.min(data.page * data.page_size, data.total);
  return `${start}-${end}`;
}

function updateBatchResearchRow(
  current: BatchResearchRun | null,
  pifId: string,
  patch: Partial<BatchResearchRow>,
) {
  if (!current) return current;
  return {
    ...current,
    rows: current.rows.map((row) => (row.pif_id === pifId ? { ...row, ...patch } : row)),
  };
}

function dateInputValue(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function subtractMonths(date: Date, months: number) {
  const day = date.getDate();
  const result = new Date(date);
  result.setDate(1);
  result.setMonth(result.getMonth() - months);
  const lastDayOfMonth = new Date(result.getFullYear(), result.getMonth() + 1, 0).getDate();
  result.setDate(Math.min(day, lastDayOfMonth));
  return result;
}

function firstContactRange(filters: FiltersState) {
  if (filters.first_contact_period === "last_1_month") {
    return { from: dateInputValue(subtractMonths(new Date(), 1)), to: undefined };
  }
  if (filters.first_contact_period === "last_6_months") {
    return { from: dateInputValue(subtractMonths(new Date(), 6)), to: undefined };
  }
  if (filters.first_contact_period === "custom") {
    return {
      from: filters.first_contacted_from.trim() || undefined,
      to: filters.first_contacted_to.trim() || undefined,
    };
  }
  return { from: undefined, to: undefined };
}

function filtersToParams(filters: FiltersState, page: number): PifInfoListParams {
  const recently = Number(filters.recently_researched);
  const firstContact = firstContactRange(filters);
  return {
    search: filters.search.trim() || undefined,
    page,
    page_size: PAGE_SIZE,
    sort_by: filters.sort_by,
    icp_tiers: filters.icp_tier,
    entity_types: filters.entity_type,
    recently_researched:
      filters.recently_researched.trim() && Number.isFinite(recently) ? recently : undefined,
    contact_email_ranges: filters.contact_email_range,
    staff_count_ranges: filters.staff_count_range,
    autorespond_window: filters.autorespond_window,
    autorespond_types: filters.autorespond_type,
    website_presence: filters.website_presence,
    research_presences: filters.research_presence,
    staff_presences: filters.staff_presence,
    job_postings_presences: filters.job_postings_presence,
    job_posting_roles: filters.job_posting_role,
    job_posting_tags: filters.job_posting_tag,
    job_posting_query: filters.job_posting_query.trim() || undefined,
    job_posted_within_days:
      filters.job_posted_within_days && Number.isFinite(Number(filters.job_posted_within_days))
        ? Number(filters.job_posted_within_days)
        : undefined,
    behavior_presence: filters.behavior_presence,
    icp_presence: filters.icp_presence,
    vendor_presence: filters.vendor.length ? "any" : filters.vendor_presence,
    vendors: filters.vendor,
    manually_added:
      filters.record_origin === "manual" ? true : filters.record_origin === "synced" ? false : undefined,
    first_contacted_from: firstContact.from,
    first_contacted_to: firstContact.to,
    active_only: filters.active_only,
  };
}

function criteriaFromFirmFilters(filters: FiltersState): SavedFirmTriggerSearchCriteria {
  return { ...filters };
}

function filtersToPriorityParams(filters: FiltersState, page: number): PriorityFirmsListParams {
  return {
    search: filters.search.trim() || undefined,
    event_types: filters.trigger_event_types,
    categories: filters.trigger_categories,
    within_days: Math.max(1, Number(filters.trigger_within_days) || 30),
    min_score: Math.max(0, Number(filters.trigger_min_score) || 0),
    min_confidence: Math.max(0, Math.min(1, Number(filters.trigger_min_confidence) || 0)),
    match_mode: filters.trigger_match_mode,
    icp_tiers: filters.icp_tier,
    entity_types: filters.entity_type,
    staff_count_ranges: filters.staff_count_range,
    vendors: filters.vendor,
    sort_by: filters.priority_sort,
    page,
    page_size: PAGE_SIZE,
  };
}

function firmFiltersFromSavedTrigger(search: SavedFirmTriggerSearch): FiltersState {
  return {
    ...DEFAULT_FILTERS,
    ...search.criteria,
    icp_tier: selectedStringValues(search.criteria.icp_tier) as PifTier[],
    entity_type: selectedStringValues(search.criteria.entity_type),
    research_presence: selectedStringValues(search.criteria.research_presence),
    staff_presence: selectedStringValues(search.criteria.staff_presence),
    job_postings_presence: selectedStringValues(search.criteria.job_postings_presence),
    job_posting_role: selectedStringValues(search.criteria.job_posting_role),
    job_posting_tag: selectedStringValues(search.criteria.job_posting_tag),
    vendor: selectedStringValues(search.criteria.vendor),
    contact_email_range: selectedCountRanges(search.criteria.contact_email_range),
    staff_count_range: selectedCountRanges(search.criteria.staff_count_range),
    autorespond_type: selectedStringValues(search.criteria.autorespond_type),
  };
}

function selectedStringValues(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string" && item.length > 0);
  }
  return typeof value === "string" && value ? [value] : [];
}

const selectedCountRanges = selectedStringValues;

const COUNT_RANGES = ["0-0", "1-5", "6-10", "11-25", "26-50", "51-100", "101+"] as const;
const COUNT_RANGE_OPTIONS = COUNT_RANGES.map((value) => ({ value }));
const formatCountRange = (value: string) => value === "0-0" ? "0" : value;
const JOB_TRIGGER_TAGS = [
  "rapid_lead_followup",
  "lead_conversion",
  "high_volume",
  "after_hours_or_24_7",
  "crm_management",
  "case_management_system",
  "call_tracking",
  "marketing_attribution",
  "kpi_reporting",
  "workflow_automation",
  "ai_adoption",
  "client_status_updates",
  "new_office_or_market",
  "spanish_language_capacity",
  "team_expansion",
] as const;
const ENTITY_TYPES = [
  "pi_law_firm",
  "law_firm",
  "personal_injury_law_firm",
  "medical_referring",
  "medical_facility",
  "administrative",
  "insurance",
  "funding",
  "patient_adjacent",
  "collections",
  "legal_other",
  "legal_technology_vendor",
] as const;
const AUTORESPOND_TYPES = [
  "apt_status_req",
  "bill_balance_request",
  "bill_offer",
  "medical_records",
  "psl_lien",
  "asl_lien",
  "missing_lien_request",
  "case_updates",
  "unknown_sig_lien",
] as const;
const AUTORESPOND_TYPE_OPTIONS = AUTORESPOND_TYPES.map((value) => ({ value }));
const ICP_TIER_OPTIONS = (["A", "B", "C", "D"] as const).map((value) => ({ value }));
const ENTITY_TYPE_OPTIONS = ENTITY_TYPES.map((value) => ({
  value,
  label: ENTITY_TYPE_LABELS[value] ?? formatLabel(value),
}));
const STATUS_FILTER_OPTIONS = STATUS_PRESENCE
  .filter((value) => value !== "any")
  .map((value) => ({ value }));
const JOB_POSTING_PRESENCE_OPTIONS = [
  { value: "has", label: "Has recent openings" },
  { value: "none", label: "No recent openings" },
  { value: "not_researched", label: "Not researched" },
  { value: "queued_or_running", label: "Queued or running" },
  { value: "failed", label: "Failed" },
];
const JOB_POSTING_ROLE_OPTIONS = [
  { value: "intake", label: "Intake and reception" },
  { value: "marketing", label: "Marketing and growth" },
  { value: "case_operations", label: "Case operations" },
  { value: "firm_operations", label: "Firm operations" },
  { value: "technology", label: "Technology and systems" },
];
const JOB_TRIGGER_TAG_OPTIONS = JOB_TRIGGER_TAGS.map((value) => ({ value }));

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedValue(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [delayMs, value]);

  return debouncedValue;
}

export default function EmailtagFirmsPage() {
  return (
    <Suspense fallback={<EmailtagFirmsFallback />}>
      <EmailtagFirmsContent />
    </Suspense>
  );
}

function EmailtagFirmsFallback() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center text-sm text-neutral-500">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      Loading leads...
    </div>
  );
}

function EmailtagFirmsContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const selectedFirmId = searchParams.get("firm") ?? "";
  const [batchResearchLimit, setBatchResearchLimit] = useState("10");
  const [batchResearchRun, setBatchResearchRun] = useState<BatchResearchRun | null>(null);
  const [jobPostingResearchLimit, setJobPostingResearchLimit] = useState("25");
  const [jobPostingResearchRun, setJobPostingResearchRun] = useState<BatchResearchRun | null>(null);
  const [filters, setFilters] = useState<FiltersState>(DEFAULT_FILTERS);
  const [page, setPage] = useState(1);
  const [view, setView] = useState<LeadsView>(() => {
    const requestedView = searchParams.get("view");
    return requestedView === "contacts" || requestedView === "job_listings" || requestedView === "firms"
      ? requestedView
      : "priority";
  });
  const [activeTriggerSearchId, setActiveTriggerSearchId] = useState("");
  const [activeSavedSearchId, setActiveSavedSearchId] = useState(searchParams.get("saved") ?? "");
  const [peopleFiltersState, setPeopleFiltersState] = useState<PifPeopleListParams>(() =>
    peopleFiltersFromParams(new URLSearchParams(searchParams.toString())),
  );
  const peopleFilters = peopleFiltersState;
  const setPeopleFilters: React.Dispatch<React.SetStateAction<PifPeopleListParams>> = (update) => {
    setActiveSavedSearchId("");
    setPeopleFiltersState(update);
  };
  const debouncedPeopleFilters = useDebouncedValue(peopleFilters, 250);

  const listParams = useMemo(() => filtersToParams(filters, page), [filters, page]);
  const priorityParams = useMemo(() => filtersToPriorityParams(filters, page), [filters, page]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (view === "contacts") {
      params.set("view", "contacts");
      writePeopleFilters(params, peopleFilters);
      if (activeSavedSearchId) params.set("saved", activeSavedSearchId);
      else params.delete("saved");
    } else if (view === "job_listings") {
      params.set("view", "job_listings");
      params.delete("saved");
      CONTACT_QUERY_KEYS.forEach((key) => params.delete(key));
    } else if (view === "firms") {
      params.set("view", "firms");
      params.delete("saved");
      CONTACT_QUERY_KEYS.forEach((key) => params.delete(key));
    } else {
      params.delete("view");
      params.delete("saved");
      CONTACT_QUERY_KEYS.forEach((key) => params.delete(key));
    }
    const query = params.toString();
    const nextUrl = query ? `${pathname}?${query}` : pathname;
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    if (nextUrl !== currentUrl) router.replace(nextUrl, { scroll: false });
  }, [activeSavedSearchId, pathname, peopleFilters, router, view]);

  const setSelectedFirm = (pifId: string | null) => {
    const params = new URLSearchParams(searchParams.toString());
    if (pifId) {
      params.set("firm", pifId);
    } else {
      params.delete("firm");
    }
    const query = params.toString();
    const basePath = pathname?.startsWith("/leads") ? "/leads" : "/emailtag-firms";
    router.push(query ? `${basePath}?${query}` : basePath);
  };

  const firmsQuery = useQuery({
    queryKey: ["emailtag", "firms", listParams],
    queryFn: () => listMirroredPifInfo(listParams),
    enabled: view === "firms",
    refetchInterval: 60_000,
  });

  const priorityQuery = useQuery({
    queryKey: ["pif", "priority-firms", priorityParams],
    queryFn: () => listPriorityPifFirms(priorityParams),
    enabled: view === "priority",
    refetchInterval: 60_000,
  });

  const triggerOptionsQuery = useQuery<TriggerFilterOptions>({
    queryKey: ["pif", "trigger-options"],
    queryFn: getPifTriggerOptions,
    enabled: view === "priority",
    staleTime: 5 * 60_000,
  });

  const reviewCorpusQuery = useQuery<ReviewCorpusProgress>({
    queryKey: ["firm-review-corpus-progress"],
    queryFn: getReviewCorpusProgress,
    refetchInterval: 15_000,
  });

  const syncStatusQuery = useQuery({
    queryKey: ["pif", "sync-status"],
    queryFn: getPifSyncStatus,
    refetchInterval: 5 * 60_000,
  });

  const vendorOptionsQuery = useQuery({
    queryKey: ["pif", "vendors"],
    queryFn: listPifVendors,
    staleTime: 5 * 60_000,
  });

  const peopleQuery = useQuery({
    queryKey: ["emailtag", "people", debouncedPeopleFilters],
    queryFn: () => listPifPeople(debouncedPeopleFilters),
    enabled: view === "contacts",
  });

  const peopleFilterOptionsQuery = useQuery({
    queryKey: ["pif", "people-filter-options"],
    queryFn: getPifPeopleFilterOptions,
    enabled: view === "contacts",
    staleTime: 5 * 60_000,
  });

  const savedSearchesQuery = useQuery({
    queryKey: ["pif", "saved-lead-searches", "contacts"],
    queryFn: listSavedLeadSearches,
  });

  const triggerSearchesQuery = useQuery({
    queryKey: ["pif", "saved-lead-searches", "firms"],
    queryFn: listSavedFirmTriggerSearches,
  });

  const createTriggerSearchMutation = useMutation({
    mutationFn: (name: string) => createSavedFirmTriggerSearch({
      name,
      criteria: criteriaFromFirmFilters(filters),
    }),
    onSuccess: async ({ saved_search: savedSearch }) => {
      setActiveTriggerSearchId(savedSearch.id);
      await queryClient.invalidateQueries({ queryKey: ["pif", "saved-lead-searches", "firms"] });
    },
  });

  const updateTriggerSearchMutation = useMutation({
    mutationFn: (searchId: string) => updateSavedFirmTriggerSearch(searchId, {
      criteria: criteriaFromFirmFilters(filters),
    }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["pif", "saved-lead-searches", "firms"] });
    },
  });

  const deleteTriggerSearchMutation = useMutation({
    mutationFn: deleteSavedFirmTriggerSearch,
    onSuccess: async () => {
      setActiveTriggerSearchId("");
      await queryClient.invalidateQueries({ queryKey: ["pif", "saved-lead-searches", "firms"] });
    },
  });

  const createSavedSearchMutation = useMutation({
    mutationFn: (name: string) => createSavedLeadSearch({
      name,
      criteria: criteriaFromPeopleFilters(peopleFilters),
    }),
    onSuccess: async ({ saved_search: savedSearch }) => {
      setActiveSavedSearchId(savedSearch.id);
      await queryClient.invalidateQueries({ queryKey: ["pif", "saved-lead-searches"] });
    },
  });

  const updateSavedSearchMutation = useMutation({
    mutationFn: (searchId: string) => updateSavedLeadSearch(searchId, {
      criteria: criteriaFromPeopleFilters(peopleFilters),
    }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["pif", "saved-lead-searches"] });
    },
  });

  const deleteSavedSearchMutation = useMutation({
    mutationFn: deleteSavedLeadSearch,
    onSuccess: async () => {
      setActiveSavedSearchId("");
      await queryClient.invalidateQueries({ queryKey: ["pif", "saved-lead-searches"] });
    },
  });

  const exportAll = useMutation({
    mutationFn: (format: ExportFormat) => downloadEmailtagExport({ format, include_merged: false }),
    onSuccess: ({ blob, filename }) => downloadBlob(blob, filename),
  });

  const queueMissingResearch = useMutation({
    mutationFn: async () => {
      const requested = Math.max(1, Math.min(100, Number(batchResearchLimit) || 1));
      const selected: PifInfoResponse[] = [];
      let lookupPage = 1;
      let totalPages = 1;

      while (selected.length < requested && lookupPage <= totalPages) {
        const payload = await listMirroredPifInfo({
          page: lookupPage,
          page_size: BATCH_PAGE_SIZE,
          sort_by: "updated_at",
          research_presence: "missing",
          active_only: true,
        });
        totalPages = payload.total_pages || 1;
        for (const firm of payload.items) {
          if (!firm.research_status && selected.length < requested) selected.push(firm);
        }
        lookupPage += 1;
      }

      setBatchResearchRun({
        requested,
        rows: selected.map((firm) => ({
          pif_id: firm.id,
          firm_name: firm.firm_name,
          task_id: null,
          status: "remaining",
          message: "Waiting to queue",
        })),
      });

      const queued = await Promise.all(
        selected.map(async (firm) => {
          const response = await startResearch(firm.id);
          setBatchResearchRun((current) => updateBatchResearchRow(current, firm.id, {
            task_id: response.task_id,
            status: response.status || "queued",
            message: response.message || "Queued",
          }));
          return response;
        }),
      );
      return { requested, selected, queued };
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["emailtag", "firms"] });
    },
  });

  const queueFilteredJobPostings = useMutation({
    mutationFn: async () => {
      const requested = Math.max(1, Math.min(100, Number(jobPostingResearchLimit) || 1));
      const selected: PifInfoResponse[] = [];
      let lookupPage = 1;
      let totalPages = 1;

      while (selected.length < requested && lookupPage <= totalPages) {
        const payload = await listMirroredPifInfo({
          ...filtersToParams(filters, lookupPage),
          page: lookupPage,
          page_size: BATCH_PAGE_SIZE,
        });
        totalPages = payload.total_pages || 1;
        for (const firm of payload.items) {
          const status = firm.research_data?.job_postings_research_status;
          if (!isWorkflowRunning(status) && selected.length < requested) selected.push(firm);
        }
        lookupPage += 1;
      }

      setJobPostingResearchRun({
        requested: selected.length,
        rows: selected.map((firm) => ({
          pif_id: firm.id,
          firm_name: firm.firm_name,
          task_id: null,
          status: "remaining",
          message: "Waiting to queue",
        })),
      });

      const queued: ResearchStartResponse[] = [];
      for (let offset = 0; offset < selected.length; offset += 5) {
        const chunk = selected.slice(offset, offset + 5);
        const responses = await Promise.all(chunk.map(async (firm) => {
          try {
            const response = await startJobPostingsResearch(firm.id);
            setJobPostingResearchRun((current) => updateBatchResearchRow(current, firm.id, {
              task_id: response.task_id,
              status: response.status || "queued",
              message: response.message || "Queued",
            }));
            return response;
          } catch (error) {
            setJobPostingResearchRun((current) => updateBatchResearchRow(current, firm.id, {
              status: "failed",
              message: error instanceof Error ? error.message : "Could not queue job-posting research",
            }));
            return null;
          }
        }));
        queued.push(...responses.filter((response): response is ResearchStartResponse => response !== null));
      }
      return { requested, selected, queued };
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["emailtag", "firms"] });
    },
  });

  const batchTaskKey = useMemo(
    () =>
      batchResearchRun?.rows
        .map((row) => row.task_id)
        .filter((taskId): taskId is string => Boolean(taskId))
        .sort()
        .join(",") ?? "",
    [batchResearchRun],
  );

  const batchStatusQuery = useQuery({
    queryKey: ["emailtag", "batch-research-status", batchTaskKey],
    queryFn: async () => {
      const rows = batchResearchRun?.rows.filter((row) => row.task_id) ?? [];
      return Promise.all(
        rows.map(async (row) => ({
          pif_id: row.pif_id,
          status: await getResearchStatus(row.task_id ?? ""),
        })),
      );
    },
    enabled:
      Boolean(batchTaskKey) &&
      Boolean(batchResearchRun?.rows.some((row) => row.task_id && !TERMINAL_TASK_STATUSES.has(row.status))),
    refetchInterval: (query) => {
      const statuses = query.state.data?.map((item) => item.status.status) ?? [];
      return statuses.length > 0 && statuses.every((status) => TERMINAL_TASK_STATUSES.has(status)) ? false : 5_000;
    },
  });

  const jobPostingTaskKey = useMemo(
    () =>
      jobPostingResearchRun?.rows
        .map((row) => row.task_id)
        .filter((taskId): taskId is string => Boolean(taskId))
        .sort()
        .join(",") ?? "",
    [jobPostingResearchRun],
  );

  const jobPostingStatusQuery = useQuery({
    queryKey: ["emailtag", "job-posting-research-status", jobPostingTaskKey],
    queryFn: async () => {
      const rows = jobPostingResearchRun?.rows.filter((row) => row.task_id) ?? [];
      return Promise.all(
        rows.map(async (row) => ({
          pif_id: row.pif_id,
          status: await getProxiedResearchStatus(row.task_id ?? ""),
        })),
      );
    },
    enabled:
      Boolean(jobPostingTaskKey) &&
      Boolean(jobPostingResearchRun?.rows.some((row) => row.task_id && !TERMINAL_TASK_STATUSES.has(row.status))),
    refetchInterval: (query) => {
      const statuses = query.state.data?.map((item) => item.status.status) ?? [];
      return statuses.length > 0 && statuses.every((status) => TERMINAL_TASK_STATUSES.has(status)) ? false : 5_000;
    },
  });

  useEffect(() => {
    const updates = batchStatusQuery.data;
    if (!updates?.length) return;
    setBatchResearchRun((current) => {
      if (!current) return current;
      return {
        ...current,
        rows: current.rows.map((row) => {
          const update = updates.find((item) => item.pif_id === row.pif_id);
          if (!update) return row;
          return {
            ...row,
            status: update.status.status,
            message: update.status.message,
          };
        }),
      };
    });
    if (updates.some((item) => TERMINAL_TASK_STATUSES.has(item.status.status))) {
      void queryClient.invalidateQueries({ queryKey: ["emailtag", "firms"] });
    }
  }, [batchStatusQuery.data, queryClient]);

  useEffect(() => {
    const updates = jobPostingStatusQuery.data;
    if (!updates?.length) return;
    setJobPostingResearchRun((current) => {
      if (!current) return current;
      return {
        ...current,
        rows: current.rows.map((row) => {
          const update = updates.find((item) => item.pif_id === row.pif_id);
          if (!update) return row;
          return {
            ...row,
            status: update.status.status,
            message: update.status.message,
          };
        }),
      };
    });
    if (updates.some((item) => TERMINAL_TASK_STATUSES.has(item.status.status))) {
      void queryClient.invalidateQueries({ queryKey: ["emailtag", "firms"] });
    }
  }, [jobPostingStatusQuery.data, queryClient]);

  function updateFilter<K extends keyof FiltersState>(key: K, value: FiltersState[K]) {
    setActiveTriggerSearchId("");
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  }

  function showFirmContacts(firm: PifInfoResponse) {
    setPeopleFiltersState((current) => ({
      firm: firm.firm_name || firm.id,
      source: "all",
      leader: "any",
      page: 1,
      page_size: current.page_size ?? 25,
    }));
    setActiveSavedSearchId("");
    setView("contacts");
  }

  function applySavedSearch(search: SavedLeadSearch) {
    setPeopleFiltersState(peopleFiltersFromSavedSearch(search, peopleFilters.page_size ?? 25));
    setActiveSavedSearchId(search.id);
    setView("contacts");
  }

  function applyTriggerSearch(search: SavedFirmTriggerSearch) {
    setFilters(firmFiltersFromSavedTrigger(search));
    setPage(1);
    setActiveTriggerSearchId(search.id);
    setView("priority");
  }

  const data = firmsQuery.data;
  const priorityData = priorityQuery.data;
  const firms = data?.items ?? [];
  const totalPages = data?.total_pages ?? 1;
  const peopleData = peopleQuery.data;
  const peopleTotalPages = peopleData?.total_pages ?? 1;
  const pageSummary = {
    missingWebsite: firms.filter((firm) => !(firm.canonical_website ?? firm.website)).length,
    scored: firms.filter((firm) => firm.icp_score != null).length,
  };
  const refreshLeads = () => {
    if (view === "contacts") return peopleQuery.refetch();
    if (view === "job_listings") return queryClient.invalidateQueries({ queryKey: ["pif", "job-postings"] });
    if (view === "priority") return priorityQuery.refetch();
    return firmsQuery.refetch();
  };
  const refreshing = view === "contacts"
    ? peopleQuery.isFetching
    : view === "firms"
      ? firmsQuery.isFetching
      : view === "priority"
        ? priorityQuery.isFetching
        : false;

  return (
    <div className="-mx-3 -my-4 min-h-screen bg-[#f3f6f7] px-3 py-4 sm:-mx-4 sm:px-4 md:-mx-8 md:-my-6 md:px-8 md:py-6">
      <div className="mx-auto max-w-[1600px] space-y-4">
        <header className="overflow-hidden rounded-lg border border-[#d8e1e5] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.04)]">
          <div className="flex h-1" aria-hidden="true">
            <div className="w-[38%] bg-[#176b70]" />
            <div className="w-[24%] bg-[#2f6fca]" />
            <div className="w-[20%] bg-[#e5a424]" />
            <div className="flex-1 bg-[#cf5b65]" />
          </div>
          <div className="flex flex-col gap-4 px-4 py-4 sm:px-5 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-[#164e52] text-white shadow-sm">
                <Activity className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <div className="text-[10px] font-semibold uppercase text-[#567079]">Lead intelligence</div>
                <h1 className="text-xl font-semibold text-[#12272d]">Leads</h1>
                <p className="truncate text-sm text-[#61757c]">
                  {view === "contacts"
                    ? `${peopleData?.total?.toLocaleString() ?? "—"} contacts from the local EmailTag mirror.`
                    : view === "job_listings"
                      ? "Job listings from the local EmailTag mirror."
                      : view === "priority"
                        ? `${priorityData?.total?.toLocaleString() ?? "—"} firms with timely GTM triggers.`
                        : `${data?.total?.toLocaleString() ?? "—"} firms from the local EmailTag mirror.`}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => void refreshLeads()}
                disabled={refreshing}
                className="inline-flex items-center gap-1.5 rounded-md border border-[#b8d2d3] bg-[#edf7f6] px-3 py-2 text-xs font-semibold text-[#165c61] hover:bg-[#dff0ef] disabled:opacity-40"
              >
                {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                Refresh
              </button>
              <button
                type="button"
                onClick={() => exportAll.mutate("json")}
                disabled={exportAll.isPending}
                className="inline-flex items-center gap-1.5 rounded-md border border-[#d6e0e4] bg-white px-3 py-2 text-xs font-medium text-[#40565e] hover:border-[#aebfc5] hover:bg-[#f7fafb] disabled:opacity-40"
              >
                <FileJson className="h-3.5 w-3.5 text-[#2f6fca]" />
                Export JSON
              </button>
              <button
                type="button"
                onClick={() => exportAll.mutate("csv")}
                disabled={exportAll.isPending}
                className="inline-flex items-center gap-1.5 rounded-md border border-[#d6e0e4] bg-white px-3 py-2 text-xs font-medium text-[#40565e] hover:border-[#aebfc5] hover:bg-[#f7fafb] disabled:opacity-40"
              >
                <Download className="h-3.5 w-3.5 text-[#b37a0e]" />
                Export CSV
              </button>
            </div>
          </div>
        </header>

        {reviewCorpusQuery.data && (
          <section aria-label="Review corpus progress" className="overflow-hidden rounded-lg border border-[#bfe4d3] bg-white shadow-sm">
            <div className="grid gap-4 p-4 lg:grid-cols-[minmax(260px,0.9fr)_minmax(420px,1.1fr)] lg:items-center">
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[#e7f7ef] text-[#18734f]">
                  <Star className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <div className="text-xs font-semibold text-[#25443a]">Review intelligence corpus</div>
                    <div className="text-[11px] font-medium text-[#348065]">
                      {reviewCorpusQuery.data.distinct_reviews.toLocaleString()} / {reviewCorpusQuery.data.target_distinct_reviews.toLocaleString()} distinct
                    </div>
                  </div>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#e1f1e9]" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={reviewCorpusQuery.data.progress_percent}>
                    <div className="h-full bg-[#21a46e] transition-[width]" style={{ width: `${Math.min(100, reviewCorpusQuery.data.progress_percent)}%` }} />
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-2 divide-x divide-[#d7e9df] rounded-md bg-[#f3faf6] sm:grid-cols-4">
                <CorpusStat label="Firms" value={reviewCorpusQuery.data.firms_with_reviews} />
                <CorpusStat label="Classified" value={reviewCorpusQuery.data.classified_reviews} />
                <CorpusStat label="Queued" value={reviewCorpusQuery.data.task_counts.queued ?? 0} />
                <CorpusStat label="Running" value={reviewCorpusQuery.data.task_counts.in_progress ?? 0} />
              </div>
            </div>
          </section>
        )}

      {view === "firms" && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricTile tone="blue" icon={<Database className="h-4 w-4" />} label="Matching firms" value={data?.total ?? 0} />
          <MetricTile tone="teal" icon={<SlidersHorizontal className="h-4 w-4" />} label="Showing" value={visibleRange(data)} />
          <MetricTile tone="amber" icon={<Globe className="h-4 w-4" />} label="Missing websites on page" value={pageSummary.missingWebsite} />
          <MetricTile tone="green" icon={<BarChart3 className="h-4 w-4" />} label="Scored on page" value={pageSummary.scored} />
        </div>
      )}

      <SyncStatusPanel status={syncStatusQuery.data} loading={syncStatusQuery.isLoading} />

      <LeadsViewTabs
        value={view}
        onChange={setView}
      />

      {view === "priority" ? (
        <PriorityFirmsView
          data={priorityData}
          loading={priorityQuery.isLoading}
          error={priorityQuery.error}
          filters={filters}
          updateFilter={updateFilter}
          clearFilters={() => {
            setFilters(DEFAULT_FILTERS);
            setActiveTriggerSearchId("");
            setPage(1);
          }}
          options={triggerOptionsQuery.data}
          vendorOptions={vendorOptionsQuery.data?.vendors ?? []}
          savedSearches={triggerSearchesQuery.data?.saved_searches ?? []}
          activeSearchId={activeTriggerSearchId}
          onApplySearch={applyTriggerSearch}
          onCreateSearch={(name) => createTriggerSearchMutation.mutate(name)}
          onUpdateSearch={() => {
            if (activeTriggerSearchId) updateTriggerSearchMutation.mutate(activeTriggerSearchId);
          }}
          onDeleteSearch={() => {
            if (activeTriggerSearchId) deleteTriggerSearchMutation.mutate(activeTriggerSearchId);
          }}
          savedSearchPending={
            triggerSearchesQuery.isLoading
            || createTriggerSearchMutation.isPending
            || updateTriggerSearchMutation.isPending
            || deleteTriggerSearchMutation.isPending
          }
          savedSearchError={
            triggerSearchesQuery.error
            || createTriggerSearchMutation.error
            || updateTriggerSearchMutation.error
            || deleteTriggerSearchMutation.error
          }
          page={priorityData?.page ?? page}
          totalPages={priorityData?.total_pages ?? 1}
          onPageChange={setPage}
          onOpenFirm={setSelectedFirm}
        />
      ) : view === "firms" ? (
        <>
          <BatchResearchPanel
            title="Queue missing firm research"
            description="Most recently updated firms first, only where research has never been started."
            buttonLabel="Queue research"
            limit={batchResearchLimit}
            setLimit={setBatchResearchLimit}
            onQueue={() => queueMissingResearch.mutate()}
            pending={queueMissingResearch.isPending}
            result={queueMissingResearch.data}
            error={queueMissingResearch.error}
            run={batchResearchRun}
            polling={batchStatusQuery.isFetching}
          />

          <TriggerSearchBar
            savedSearches={triggerSearchesQuery.data?.saved_searches ?? []}
            activeSearchId={activeTriggerSearchId}
            qualifyingCount={data?.total ?? 0}
            onApply={applyTriggerSearch}
            onCreate={(name) => createTriggerSearchMutation.mutate(name)}
            onUpdate={() => {
              if (activeTriggerSearchId) updateTriggerSearchMutation.mutate(activeTriggerSearchId);
            }}
            onDelete={() => {
              if (activeTriggerSearchId) deleteTriggerSearchMutation.mutate(activeTriggerSearchId);
            }}
            pending={
              triggerSearchesQuery.isLoading
              || createTriggerSearchMutation.isPending
              || updateTriggerSearchMutation.isPending
              || deleteTriggerSearchMutation.isPending
            }
            error={
              triggerSearchesQuery.error
              || createTriggerSearchMutation.error
              || updateTriggerSearchMutation.error
              || deleteTriggerSearchMutation.error
            }
          />

          <FilterBar filters={filters} updateFilter={updateFilter} clearFilters={() => {
            setFilters(DEFAULT_FILTERS);
            setActiveTriggerSearchId("");
            setPage(1);
          }} vendorOptions={vendorOptionsQuery.data?.vendors ?? []} />

          <BatchResearchPanel
            title="Research job postings for filtered firms"
            description={`${data?.total ?? 0} firms match the current filters. Firms already running job-posting research are skipped.`}
            buttonLabel="Research job postings"
            limit={jobPostingResearchLimit}
            setLimit={setJobPostingResearchLimit}
            onQueue={() => queueFilteredJobPostings.mutate()}
            pending={queueFilteredJobPostings.isPending}
            result={queueFilteredJobPostings.data}
            error={queueFilteredJobPostings.error}
            run={jobPostingResearchRun}
            polling={jobPostingStatusQuery.isFetching}
          />

          <div className="overflow-hidden rounded-lg border border-[#cfdde2] bg-white shadow-sm">
            {firmsQuery.isLoading && (
              <div className="px-5 py-8 text-center text-xs text-neutral-400">Loading leads...</div>
            )}
            {firmsQuery.isError && !isAuthError(firmsQuery.error) && (
              <div className="px-5 py-8 text-center text-xs text-rose-600">
                {firmsQuery.error instanceof Error ? firmsQuery.error.message : "Lead list failed"}
              </div>
            )}
            {!firmsQuery.isLoading && firms.length === 0 && (
              <div className="px-5 py-8 text-center text-xs text-neutral-400">No firms match the filters.</div>
            )}
            {firms.length > 0 && (
              <div className="mobile-table-card overflow-hidden">
                <table className="w-full table-fixed divide-y divide-neutral-100 text-sm">
                  <thead className="bg-[#edf3f5] text-left text-[11px] uppercase text-[#5a717a]">
                    <tr>
                      <th className="w-[3%] px-2 py-2" />
                      <th className="w-[15%] px-2 py-2 font-medium">Firm</th>
                      <th className="hidden w-[8%] px-2 py-2 font-medium 2xl:table-cell">Entity</th>
                      <th className="w-[15%] px-2 py-2 font-medium">Website</th>
                      <th className="w-[8%] px-2 py-2 font-medium">Staff</th>
                      <th className="w-[7%] px-2 py-2 font-medium">ICP</th>
                      <th className="w-[8%] px-2 py-2 font-medium">Research</th>
                      <th className="w-[10%] px-2 py-2 font-medium">First contact</th>
                      <th className="hidden w-[11%] px-2 py-2 font-medium xl:table-cell">Signals</th>
                      <th className="w-[8%] px-2 py-2 font-medium">Updated</th>
                      <th className="w-[9%] px-2 py-2 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-100">
                    {firms.map((firm) => (
                      <FirmTableRows
                        key={firm.id}
                        firm={firm}
                        onOpen={() => setSelectedFirm(firm.id)}
                        onViewContacts={() => showFirmContacts(firm)}
                        onAuthError={() => undefined}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="flex items-center justify-between text-xs text-neutral-500">
            <span>
              Page {data?.page ?? page} of {totalPages} ({data?.total?.toLocaleString() ?? 0} firms)
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={page <= 1}
                className="inline-flex items-center gap-1 rounded-md border border-neutral-300 px-2.5 py-1 text-xs font-medium disabled:opacity-30"
              >
                <ChevronLeft className="h-3 w-3" />
                Prev
              </button>
              <button
                type="button"
                onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                disabled={page >= totalPages}
                className="inline-flex items-center gap-1 rounded-md border border-neutral-300 px-2.5 py-1 text-xs font-medium disabled:opacity-30"
              >
                Next
                <ChevronRight className="h-3 w-3" />
              </button>
            </div>
          </div>
        </>
      ) : view === "contacts" ? (
        <ContactsView
          filters={peopleFilters}
          setFilters={setPeopleFilters}
          items={peopleData?.items ?? []}
          loading={peopleQuery.isLoading}
          error={peopleQuery.error}
          page={peopleData?.page ?? peopleFilters.page ?? 1}
          total={peopleData?.total ?? 0}
          totalPages={peopleTotalPages}
          titleOptions={peopleFilterOptionsQuery.data?.titles ?? []}
          roleOptions={peopleFilterOptionsQuery.data?.roles ?? []}
          vendorOptions={vendorOptionsQuery.data?.vendors ?? []}
          savedSearches={savedSearchesQuery.data?.saved_searches ?? []}
          activeSavedSearchId={activeSavedSearchId}
          onApplySavedSearch={applySavedSearch}
          onCreateSavedSearch={(name) => createSavedSearchMutation.mutate(name)}
          onUpdateSavedSearch={() => {
            if (activeSavedSearchId) updateSavedSearchMutation.mutate(activeSavedSearchId);
          }}
          onDeleteSavedSearch={() => {
            if (activeSavedSearchId) deleteSavedSearchMutation.mutate(activeSavedSearchId);
          }}
          savedSearchPending={
            savedSearchesQuery.isLoading
            || createSavedSearchMutation.isPending
            || updateSavedSearchMutation.isPending
            || deleteSavedSearchMutation.isPending
          }
          savedSearchError={
            savedSearchesQuery.error
            || createSavedSearchMutation.error
            || updateSavedSearchMutation.error
            || deleteSavedSearchMutation.error
          }
        />
      ) : (
        <JobListingsView />
      )}

        <FirmDetailModal
          pifId={selectedFirmId}
          onClose={() => setSelectedFirm(null)}
          onAuthError={() => undefined}
        />
      </div>
    </div>
  );
}

function CorpusStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-0 px-3 py-2 text-center">
      <div className="truncate text-[10px] font-semibold uppercase text-[#668178]">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-[#173d31]">{value.toLocaleString()}</div>
    </div>
  );
}

function SyncStatusPanel({
  status,
  loading,
}: {
  status: PifSyncStatusResponse | undefined;
  loading: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const last = status?.last_result ?? {};
  const lastSynced = status?.last_synced_at ?? last.synced_at ?? null;
  const fetched = last.fetched ?? 0;
  const created = last.created ?? 0;
  const updated = last.updated ?? 0;
  const skipped = last.skipped ?? 0;
  const aliases = last.aliases_touched ?? 0;
  const pages = last.pages ?? 0;
  const totalReported = last.total_reported ?? 0;
  const syncItems = last.items ?? [];

  return (
    <section className="overflow-hidden rounded-lg border border-[#cbdde9] bg-white shadow-sm">
      <button
        type="button"
        onClick={() => setExpanded((current) => !current)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-[#f4f8fb]"
      >
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-[#e9f2fb] text-[#2f6fca]">
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          </div>
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase text-[#58768b]">Mirror sync</div>
            <div className="mt-0.5 truncate text-sm font-medium text-[#203b4b]">
              {loading ? "Loading sync status..." : `Last synced ${formatDateTime(lastSynced)}`}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-3 text-xs text-[#5b7180]">
          {status && (
            <>
              <span className="hidden sm:inline"><strong className="font-semibold text-[#263f4e]">{status.total_firms.toLocaleString()}</strong> firms</span>
              <span className="rounded-full bg-[#edf4fa] px-2 py-1 font-medium text-[#2f6f90]">{fetched.toLocaleString()} pulled</span>
            </>
          )}
          <ChevronDown className={cn("h-4 w-4 transition", expanded && "rotate-180")} />
        </div>
      </button>
      {expanded && (
        <div className="border-t border-neutral-100 px-3 py-3">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
            <SyncStat label="Fetched" value={fetched} />
            <SyncStat label="Created" value={created} />
            <SyncStat label="Updated" value={updated} />
            <SyncStat label="Skipped" value={skipped} />
            <SyncStat label="Aliases" value={aliases} />
            <SyncStat label="Pages" value={pages} />
            <SyncStat label="Remote total" value={totalReported} />
          </div>
          <div className="mt-3 grid gap-2 text-xs text-neutral-500 md:grid-cols-2">
            <KeyValue label="Previous watermark" value={last.previous_watermark ? formatDateTime(last.previous_watermark) : "—"} />
            <KeyValue label="Current watermark" value={(last.watermark ?? status?.watermark) ? formatDateTime(last.watermark ?? status?.watermark) : "—"} />
            <KeyValue label="Candidate watermark" value={last.candidate_watermark ? formatDateTime(last.candidate_watermark) : "—"} />
            <KeyValue label="Alias rows" value={status?.alias_count?.toLocaleString() ?? "—"} />
          </div>
          <div className="mt-4">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-xs font-semibold text-neutral-900">Firms touched in this sync</div>
                <div className="text-[11px] text-neutral-500">
                  Showing {syncItems.length.toLocaleString()} of {fetched.toLocaleString()} fetched profiles.
                </div>
              </div>
              {last.items_inferred && (
                <span className="rounded-full bg-amber-50 px-2 py-1 text-[10px] font-semibold text-amber-700">
                  Reconstructed from sync timestamp
                </span>
              )}
            </div>
            {syncItems.length === 0 ? (
              <div className="rounded-md border border-dashed border-neutral-200 px-3 py-4 text-xs text-neutral-400">
                No firm-level details were recorded for this sync.
              </div>
            ) : (
              <div className="mobile-table-card overflow-hidden rounded-md border border-neutral-200">
                <table className="w-full table-fixed divide-y divide-neutral-100 text-xs">
                  <thead className="bg-neutral-50 text-left text-[10px] uppercase text-neutral-500">
                    <tr>
                      <th className="w-[12%] px-3 py-2 font-medium">Change</th>
                      <th className="w-[28%] px-3 py-2 font-medium">Firm</th>
                      <th className="w-[22%] px-3 py-2 font-medium">Website</th>
                      <th className="w-[10%] px-3 py-2 font-medium">People</th>
                      <th className="w-[10%] px-3 py-2 font-medium">Aliases</th>
                      <th className="w-[18%] px-3 py-2 font-medium">Source updated</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-100">
                    {syncItems.map((item) => {
                      const websiteUrl = safeWebsiteUrl(item.canonical_website ?? null);
                      return (
                        <tr key={item.firm_id} className="hover:bg-neutral-50">
                          <td data-label="Change" className="px-3 py-2">
                            <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", statusColor(item.status))}>
                              {formatLabel(item.status)}
                            </span>
                          </td>
                          <td data-label="Firm" className="min-w-0 px-3 py-2">
                            <Link href={`/leads?firm=${encodeURIComponent(item.firm_id)}`} className="block truncate font-medium text-blue-600 hover:underline">
                              {item.firm_name}
                            </Link>
                            <div className="truncate font-mono text-[10px] text-neutral-400">{item.firm_id}</div>
                          </td>
                          <td data-label="Website" className="min-w-0 px-3 py-2">
                            {websiteUrl ? (
                              <a href={websiteUrl} target="_blank" rel="noreferrer" className="block truncate text-blue-600 hover:underline">
                                {item.canonical_website}
                              </a>
                            ) : "—"}
                          </td>
                          <td data-label="People" className="px-3 py-2 text-neutral-600">{item.people_count?.toLocaleString() ?? "—"}</td>
                          <td data-label="Aliases" className="px-3 py-2 text-neutral-600">{item.aliases_touched?.toLocaleString() ?? "—"}</td>
                          <td data-label="Source updated" className="px-3 py-2 text-neutral-500">{formatDateTime(item.source_updated_at ?? null)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {last.items_truncated && (
              <div className="mt-2 text-[11px] text-amber-700">Only the first {syncItems.length.toLocaleString()} firm details are retained.</div>
            )}
            {last.items_inferred && syncItems.length > 0 && (
              <div className="mt-2 text-[11px] text-neutral-500">
                Firm membership is exact for this run; per-firm alias counts were not recorded by the older sync format.
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function SyncStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-[#d9e7f0] bg-[#f4f8fb] px-3 py-2">
      <div className="text-[10px] font-semibold uppercase text-[#718998]">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-[#203b4b]">{value.toLocaleString()}</div>
    </div>
  );
}

function PriorityFirmsView({
  data,
  loading,
  error,
  filters,
  updateFilter,
  clearFilters,
  options,
  vendorOptions,
  savedSearches,
  activeSearchId,
  onApplySearch,
  onCreateSearch,
  onUpdateSearch,
  onDeleteSearch,
  savedSearchPending,
  savedSearchError,
  page,
  totalPages,
  onPageChange,
  onOpenFirm,
}: {
  data?: PriorityFirmsListResponse;
  loading: boolean;
  error: unknown;
  filters: FiltersState;
  updateFilter: <K extends keyof FiltersState>(key: K, value: FiltersState[K]) => void;
  clearFilters: () => void;
  options?: TriggerFilterOptions;
  vendorOptions: PifVendorOption[];
  savedSearches: SavedFirmTriggerSearch[];
  activeSearchId: string;
  onApplySearch: (search: SavedFirmTriggerSearch) => void;
  onCreateSearch: (name: string) => void;
  onUpdateSearch: () => void;
  onDeleteSearch: () => void;
  savedSearchPending: boolean;
  savedSearchError: unknown;
  page: number;
  totalPages: number;
  onPageChange: (page: number | ((current: number) => number)) => void;
  onOpenFirm: (firmId: string) => void;
}) {
  const queryClient = useQueryClient();
  const items = useMemo(() => data?.items ?? [], [data?.items]);
  const [selectedId, setSelectedId] = useState("");
  const [researchTaskId, setResearchTaskId] = useState("");
  const selected = items.find((item) => item.firm.id === selectedId) ?? items[0] ?? null;
  const research = useMutation({
    mutationFn: (firmId: string) => startFullEnrichment(firmId),
    onSuccess: async (result) => {
      setResearchTaskId(result.task_id);
      await queryClient.invalidateQueries({ queryKey: ["pif", "priority-firms"] });
    },
  });
  const researchStatus = useQuery({
    queryKey: ["pif", "priority-enrichment-status", researchTaskId],
    queryFn: () => getFullEnrichmentStatus(researchTaskId),
    enabled: Boolean(researchTaskId),
    refetchInterval: (query) => TERMINAL_TASK_STATUSES.has(query.state.data?.status ?? "") ? false : 3_000,
  });
  useEffect(() => {
    if (researchStatus.data && TERMINAL_TASK_STATUSES.has(researchStatus.data.status)) {
      void queryClient.invalidateQueries({ queryKey: ["pif", "priority-firms"] });
    }
  }, [queryClient, researchStatus.data]);
  useEffect(() => {
    if (items.length > 0 && !items.some((item) => item.firm.id === selectedId)) {
      setSelectedId(items[0].firm.id);
      setResearchTaskId("");
      research.reset();
    }
  }, [items, research, selectedId]);
  const averageFreshness = items.length
    ? Math.round(items.reduce((total, item) => total + item.freshness.percent, 0) / items.length)
    : 0;
  const bestContact = selected?.firm.leadership.find((person) => person.email)
    ?? selected?.firm.leadership[0]
    ?? null;
  const selectPriorityFirm = (firmId: string) => {
    if (firmId !== selected?.firm.id) {
      setResearchTaskId("");
      research.reset();
    }
    setSelectedId(firmId);
  };

  return (
    <div className="space-y-3">
      <TriggerSearchBar
        savedSearches={savedSearches}
        activeSearchId={activeSearchId}
        qualifyingCount={data?.total ?? 0}
        onApply={onApplySearch}
        onCreate={onCreateSearch}
        onUpdate={onUpdateSearch}
        onDelete={onDeleteSearch}
        pending={savedSearchPending}
        error={savedSearchError}
      />

      <section className="space-y-3 rounded-lg border border-[#cbdde9] bg-[#f7fafc] p-3 shadow-sm">
        <div className="flex flex-col gap-2 lg:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#3f78a3]" />
            <input
              value={filters.search}
              onChange={(event) => updateFilter("search", event.target.value)}
              placeholder="Search firm or trigger evidence..."
              className="w-full rounded-md border border-[#c8d9e3] bg-white py-2 pl-9 pr-3 text-sm text-[#20343b] placeholder:text-[#81939a] focus:border-[#4f88b2] focus:outline-none focus:ring-1 focus:ring-[#4f88b2]"
            />
          </div>
          <button
            type="button"
            onClick={clearFilters}
            className="inline-flex items-center justify-center gap-1.5 rounded-md border border-[#c8d9e3] bg-white px-3 py-2 text-xs font-medium text-[#526a74] hover:bg-[#edf4f8]"
          >
            <Filter className="h-3.5 w-3.5" />
            Clear filters
          </button>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
          <SearchableMultiSelectField
            label="Trigger categories"
            values={filters.trigger_categories}
            options={options?.categories ?? []}
            emptyLabel="Any category"
            searchPlaceholder="Search categories..."
            formatValue={formatLabel}
            onChange={(values) => updateFilter("trigger_categories", values)}
          />
          <SearchableMultiSelectField
            label="Specific signals"
            values={filters.trigger_event_types}
            options={options?.event_types ?? []}
            emptyLabel="Any signal"
            searchPlaceholder="Search signals..."
            formatValue={formatLabel}
            onChange={(values) => updateFilter("trigger_event_types", values)}
          />
          <SelectField label="Detected" value={filters.trigger_within_days} onChange={(value) => updateFilter("trigger_within_days", value)}>
            <option value="7">Last 7 days</option>
            <option value="14">Last 14 days</option>
            <option value="30">Last 30 days</option>
            <option value="60">Last 60 days</option>
            <option value="90">Last 90 days</option>
          </SelectField>
          <SelectField label="Minimum strength" value={filters.trigger_min_score} onChange={(value) => updateFilter("trigger_min_score", value)}>
            <option value="0">Any strength</option>
            <option value="50">50+</option>
            <option value="65">65+</option>
            <option value="75">75+</option>
            <option value="85">85+</option>
          </SelectField>
          <SelectField label="Confidence" value={filters.trigger_min_confidence} onChange={(value) => updateFilter("trigger_min_confidence", value)}>
            <option value="0">Any confidence</option>
            <option value="0.6">60%+</option>
            <option value="0.75">75%+</option>
            <option value="0.9">90%+</option>
          </SelectField>
          <SelectField label="Match" value={filters.trigger_match_mode} onChange={(value) => updateFilter("trigger_match_mode", value as FiltersState["trigger_match_mode"])}>
            <option value="any">Any selected signal</option>
            <option value="all">All selected signals</option>
          </SelectField>
          <SelectField label="Order" value={filters.priority_sort} onChange={(value) => updateFilter("priority_sort", value as FiltersState["priority_sort"])}>
            <option value="priority">Best opportunity</option>
            <option value="newest">Newest trigger</option>
            <option value="fit">Best ICP fit</option>
          </SelectField>
          <SearchableMultiSelectField
            label="ICP tier"
            values={filters.icp_tier}
            options={ICP_TIER_OPTIONS}
            emptyLabel="Any tier"
            searchPlaceholder="Search tiers..."
            onChange={(values) => updateFilter("icp_tier", values as PifTier[])}
          />
          <SearchableMultiSelectField
            label="Entity type"
            values={filters.entity_type}
            options={ENTITY_TYPE_OPTIONS}
            emptyLabel="Any entity"
            searchPlaceholder="Search entities..."
            onChange={(values) => updateFilter("entity_type", values)}
          />
          <SearchableMultiSelectField
            label="Staff count"
            values={filters.staff_count_range}
            options={COUNT_RANGE_OPTIONS}
            emptyLabel="Any count"
            searchPlaceholder="Search ranges..."
            formatValue={formatCountRange}
            onChange={(values) => updateFilter("staff_count_range", values)}
          />
          <SearchableMultiSelectField
            label="Current vendor"
            values={filters.vendor}
            options={[
              { value: "__missing", label: "No vendors detected" },
              ...vendorOptions.map((option) => ({ value: option.vendor, label: option.label, count: option.count })),
            ]}
            emptyLabel="Any vendor"
            searchPlaceholder="Search vendors..."
            onChange={(values) => updateFilter("vendor", values)}
          />
        </div>
      </section>

      <div className="grid gap-3 sm:grid-cols-3">
        <MetricTile tone="amber" icon={<Activity className="h-4 w-4" />} label="Qualifying firms" value={data?.total ?? 0} />
        <MetricTile tone="blue" icon={<Sparkles className="h-4 w-4" />} label="Signals on page" value={items.reduce((total, item) => total + item.triggers.length, 0)} />
        <MetricTile tone="green" icon={<RefreshCw className="h-4 w-4" />} label="Research freshness" value={`${averageFreshness}%`} />
      </div>

      {loading ? (
        <div className="rounded-lg border border-neutral-200 bg-white px-5 py-12 text-center text-sm text-neutral-500">
          <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
          Ranking firms...
        </div>
      ) : error ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-5 py-8 text-center text-sm text-rose-700">
          {errorMessage(error) ?? "Priority firms failed to load"}
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-neutral-300 bg-white px-5 py-12 text-center">
          <Activity className="mx-auto h-5 w-5 text-neutral-400" />
          <div className="mt-2 text-sm font-medium text-neutral-800">No qualifying changes yet</div>
          <div className="mt-1 text-xs text-neutral-500">Change alerts begin after a firm has two successful research snapshots to compare.</div>
        </div>
      ) : (
        <div className="grid min-h-[560px] overflow-hidden rounded-lg border border-[#cfdde2] bg-white shadow-sm xl:grid-cols-[minmax(0,1.7fr)_minmax(340px,0.8fr)]">
          <div className="overflow-x-auto xl:border-r xl:border-[#d7e2e6]">
            <table className="w-full table-fixed divide-y divide-neutral-100 text-sm">
              <thead className="bg-[#edf3f5] text-left text-[11px] uppercase text-[#5a717a]">
                <tr>
                  <th className="w-[25%] px-3 py-2 font-medium">Firm</th>
                  <th className="w-[38%] px-3 py-2 font-medium">Why now</th>
                  <th className="w-[14%] px-3 py-2 font-medium">Priority</th>
                  <th className="w-[12%] px-3 py-2 font-medium">Freshness</th>
                  <th className="w-[11%] px-3 py-2 font-medium">Signal date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {items.map((item) => {
                  const leadTrigger = item.triggers[0];
                  const active = selected?.firm.id === item.firm.id;
                  return (
                    <tr
                      key={item.firm.id}
                      onClick={() => selectPriorityFirm(item.firm.id)}
                      className={cn(
                        "cursor-pointer align-top transition-colors hover:bg-[#f3f8fa]",
                        active && "bg-[#fff8e8] shadow-[inset_3px_0_0_#e1a62c]",
                      )}
                    >
                      <td className="px-3 py-3">
                        <button type="button" className="block max-w-full text-left" onClick={() => selectPriorityFirm(item.firm.id)}>
                          <span className="block truncate font-semibold text-neutral-900">{item.firm.firm_name}</span>
                          <span className="mt-1 block truncate text-[11px] text-neutral-500">
                            {item.firm.icp_tier ? `Tier ${item.firm.icp_tier}` : "Unscored"} · {item.firm.staff_count} staff
                          </span>
                        </button>
                      </td>
                      <td className="px-3 py-3">
                        <div className="truncate font-medium text-neutral-800">{leadTrigger?.title ?? "Recent change"}</div>
                        <div className="mt-1 line-clamp-2 text-xs text-neutral-500">{leadTrigger?.summary ?? formatLabel(leadTrigger?.category ?? "signal")}</div>
                      </td>
                      <td className="px-3 py-3">
                        <span className={cn(
                          "inline-flex min-w-10 justify-center rounded-md px-2 py-1 text-xs font-semibold",
                          item.priority_score >= 75 ? "bg-emerald-100 text-emerald-800" : item.priority_score >= 55 ? "bg-amber-100 text-amber-800" : "bg-neutral-100 text-neutral-700",
                        )}>{item.priority_score}</span>
                        <div className="mt-1 text-[10px] text-neutral-400">Trigger {item.trigger_score}</div>
                      </td>
                      <td className="px-3 py-3">
                        <div className="text-xs font-medium text-neutral-700">{item.freshness.percent}%</div>
                        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-neutral-100">
                          <div className="h-full bg-blue-600" style={{ width: `${item.freshness.percent}%` }} />
                        </div>
                      </td>
                      <td className="px-3 py-3 text-[11px] text-neutral-500">{formatDateTime(item.latest_trigger_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {selected && (
            <aside className="min-w-0 bg-[#f5f9fa] p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-base font-semibold text-neutral-900">{selected.firm.firm_name}</div>
                  <div className="mt-1 text-xs text-neutral-500">
                    Priority {selected.priority_score} · Fit {selected.fit_score} · Trigger {selected.trigger_score}
                  </div>
                </div>
                {selected.firm.website && (
                  <a href={safeWebsiteUrl(selected.firm.website) ?? undefined} target="_blank" rel="noreferrer" title="Open firm website" className="rounded-md border border-neutral-200 bg-white p-2 text-neutral-500 hover:text-neutral-900">
                    <ExternalLink className="h-4 w-4" />
                  </a>
                )}
              </div>

              <div className="mt-4 border-t border-[#d9e4e7] pt-3">
                <div className="text-[11px] font-semibold uppercase text-[#8a650f]">Evidence timeline</div>
                <div className="mt-2 space-y-3">
                  {selected.triggers.map((trigger) => (
                    <div key={trigger.id} className="border-l-2 border-[#e4b553] pl-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="text-xs font-semibold text-neutral-900">{trigger.title}</div>
                        <span className="shrink-0 text-[10px] font-medium text-neutral-400">{Math.round(trigger.confidence * 100)}%</span>
                      </div>
                      {trigger.summary && <div className="mt-1 text-xs leading-5 text-neutral-600">{trigger.summary}</div>}
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-neutral-400">
                        <span>{formatLabel(trigger.category)}</span>
                        <span>{formatDateTime(trigger.source_date ?? trigger.detected_at)}</span>
                        {trigger.evidence.map((evidence, index) => evidence.source_url ? (
                          <a key={`${trigger.id}-${index}`} href={evidence.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-blue-600 hover:underline">
                            Source <ExternalLink className="h-3 w-3" />
                          </a>
                        ) : null)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-4 border-t border-[#d9e4e7] pt-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[11px] font-semibold uppercase text-neutral-400">Research freshness</div>
                  <span className="text-xs font-semibold text-neutral-700">{selected.freshness.fresh_modules}/{selected.freshness.total_modules} current</span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  {(["firm_profile", "sitemap", "job_postings", "reviews"] as const).map((module) => {
                    const state = selected.freshness.modules.find((item) => item.module === module);
                    return (
                      <div key={module} className="rounded-md border border-[#d7e3e7] bg-white px-2 py-2 shadow-sm">
                        <div className="flex items-center gap-1.5 text-[11px] font-medium text-neutral-700">
                          <span className={cn("h-1.5 w-1.5 rounded-full", state?.fresh ? "bg-emerald-500" : state?.status === "failed" ? "bg-rose-500" : "bg-amber-400")} />
                          {formatLabel(module)}
                        </div>
                        <div className="mt-1 truncate text-[10px] text-neutral-400" title={state?.last_error ?? undefined}>
                          {state?.last_success_at ? formatDateTime(state.last_success_at) : formatLabel(state?.status ?? "not researched")}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="mt-4 border-t border-[#d9e4e7] pt-3">
                <div className="text-[11px] font-semibold uppercase text-[#28735b]">Contact path</div>
                <div className="mt-2 text-sm font-medium text-neutral-800">{bestContact?.name ?? "No leadership contact identified"}</div>
                {bestContact?.title && <div className="text-xs text-neutral-500">{bestContact.title}</div>}
                <div className="mt-2 flex flex-wrap gap-2 text-xs">
                  {(bestContact?.email ?? selected.firm.emails[0]) && (
                    <a href={`mailto:${bestContact?.email ?? selected.firm.emails[0]}`} className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-2.5 py-1.5 text-neutral-700 hover:bg-neutral-100">
                      <Mail className="h-3.5 w-3.5" />
                      {bestContact?.email ?? selected.firm.emails[0]}
                    </a>
                  )}
                  {(bestContact?.phone ?? selected.firm.phones[0]) && (
                    <a href={`tel:${bestContact?.phone ?? selected.firm.phones[0]}`} className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-2.5 py-1.5 text-neutral-700 hover:bg-neutral-100">
                      <PhoneCall className="h-3.5 w-3.5" />
                      {bestContact?.phone ?? selected.firm.phones[0]}
                    </a>
                  )}
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2 border-t border-[#d9e4e7] pt-3">
                <button
                  type="button"
                  onClick={() => research.mutate(selected.firm.id)}
                  disabled={research.isPending}
                  className="inline-flex items-center gap-1.5 rounded-md bg-[#176b70] px-3 py-2 text-xs font-medium text-white hover:bg-[#135b60] disabled:opacity-40"
                >
                  {research.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                  Research now
                </button>
                <button
                  type="button"
                  onClick={() => onOpenFirm(selected.firm.id)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-3 py-2 text-xs font-medium text-neutral-700 hover:bg-neutral-100"
                >
                  <Database className="h-3.5 w-3.5" />
                  Full profile
                </button>
              </div>
              {researchTaskId && (
                <TaskStatus
                  label="Full enrichment"
                  status={researchStatus.data?.status ?? research.data?.status}
                  message={researchStatus.data?.message ?? research.data?.message}
                  progress={researchStatus.data?.progress_percent}
                  currentStage={researchStatus.data?.current_stage ?? undefined}
                  compact
                />
              )}
              {research.error && <div className="mt-2 text-xs text-rose-600">{errorMessage(research.error)}</div>}
            </aside>
          )}
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-neutral-500">
        <span>Page {page} of {totalPages || 1} ({data?.total?.toLocaleString() ?? 0} firms)</span>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => onPageChange((current) => Math.max(1, current - 1))} disabled={page <= 1} className="inline-flex items-center gap-1 rounded-md border border-neutral-300 px-2.5 py-1 font-medium disabled:opacity-30">
            <ChevronLeft className="h-3 w-3" /> Prev
          </button>
          <button type="button" onClick={() => onPageChange((current) => Math.min(totalPages, current + 1))} disabled={page >= totalPages || totalPages === 0} className="inline-flex items-center gap-1 rounded-md border border-neutral-300 px-2.5 py-1 font-medium disabled:opacity-30">
            Next <ChevronRight className="h-3 w-3" />
          </button>
        </div>
      </div>
    </div>
  );
}

function TriggerSearchBar({
  savedSearches,
  activeSearchId,
  qualifyingCount,
  onApply,
  onCreate,
  onUpdate,
  onDelete,
  pending,
  error,
}: {
  savedSearches: SavedFirmTriggerSearch[];
  activeSearchId: string;
  qualifyingCount: number;
  onApply: (search: SavedFirmTriggerSearch) => void;
  onCreate: (name: string) => void;
  onUpdate: () => void;
  onDelete: () => void;
  pending: boolean;
  error: unknown;
}) {
  const [name, setName] = useState("");

  return (
    <section className="rounded-lg border border-[#ead8ad] bg-[#fffbf2] p-3 shadow-sm">
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-64 flex-1 text-[11px] font-semibold uppercase text-[#7b641f]">
          Trigger search
          <select
            value={activeSearchId}
            onChange={(event) => {
              const search = savedSearches.find((item) => item.id === event.target.value);
              if (search) onApply(search);
            }}
            disabled={pending}
            className="mt-1 w-full rounded-md border border-[#dfcea4] bg-white px-2 py-1.5 text-sm normal-case text-[#3d331c] focus:border-[#b98724] focus:outline-none focus:ring-1 focus:ring-[#b98724]"
          >
            <option value="">Select saved trigger search</option>
            {savedSearches.map((search) => (
              <option key={search.id} value={search.id}>{search.name}</option>
            ))}
          </select>
        </label>
        <label className="min-w-64 flex-1 text-[11px] font-semibold uppercase text-[#7b641f]">
          New search name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Intake hiring, Filevine firms..."
            className="mt-1 w-full rounded-md border border-[#dfcea4] bg-white px-2 py-1.5 text-sm normal-case text-[#3d331c] placeholder:text-[#a59672] focus:border-[#b98724] focus:outline-none focus:ring-1 focus:ring-[#b98724]"
          />
        </label>
        <div className="flex h-8 items-center gap-1.5 rounded-md border border-[#e6ce96] bg-[#fff5dc] px-3 text-xs text-[#795818]">
          <Briefcase className="h-3.5 w-3.5 text-[#b17b16]" />
          <strong className="font-semibold text-[#5e420d]">{qualifyingCount.toLocaleString()}</strong>
          qualifying
        </div>
        <button
          type="button"
          onClick={() => {
            const nextName = name.trim();
            if (!nextName) return;
            onCreate(nextName);
            setName("");
          }}
          disabled={!name.trim() || pending}
          className="inline-flex h-8 items-center gap-1.5 rounded-md bg-[#a66d08] px-3 text-xs font-medium text-white hover:bg-[#8f5d06] disabled:opacity-40"
        >
          <Bookmark className="h-3.5 w-3.5" />
          Save new
        </button>
        {activeSearchId ? (
          <>
            <button
              type="button"
              onClick={onUpdate}
              disabled={pending}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-neutral-200 px-3 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-40"
            >
              <Save className="h-3.5 w-3.5" />
              Update
            </button>
            <button
              type="button"
              onClick={onDelete}
              disabled={pending}
              title="Delete trigger search"
              aria-label="Delete trigger search"
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-neutral-200 text-neutral-500 hover:border-rose-200 hover:bg-rose-50 hover:text-rose-700 disabled:opacity-40"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </>
        ) : null}
      </div>
      {error ? (
        <div className="mt-2 text-xs text-rose-600">{errorMessage(error) ?? "Trigger search request failed"}</div>
      ) : null}
    </section>
  );
}

function FilterBar({
  filters,
  updateFilter,
  clearFilters,
  vendorOptions,
}: {
  filters: FiltersState;
  updateFilter: <K extends keyof FiltersState>(key: K, value: FiltersState[K]) => void;
  clearFilters: () => void;
  vendorOptions: PifVendorOption[];
}) {
  return (
    <div className="space-y-3 rounded-lg border border-[#cbdde9] bg-[#f7fafc] p-3 shadow-sm">
      <div className="flex flex-col gap-2 lg:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#3f78a3]" />
          <input
            value={filters.search}
            onChange={(event) => updateFilter("search", event.target.value)}
            placeholder="Search firm, email, phone, or website..."
            className="w-full rounded-md border border-[#c8d9e3] bg-white py-2 pl-9 pr-3 text-sm text-[#20343b] placeholder:text-[#81939a] focus:border-[#4f88b2] focus:outline-none focus:ring-1 focus:ring-[#4f88b2]"
          />
        </div>
        <div className="flex items-center gap-2 rounded-md border border-[#c6ded9] bg-[#f1f8f6] px-3 py-2">
          <span className="text-xs font-medium text-[#39705f]">Active only</span>
          <Switch
            checked={filters.active_only}
            onCheckedChange={(checked) => updateFilter("active_only", checked)}
            className="h-5 w-9 data-[state=checked]:bg-[#248164] data-[state=unchecked]:bg-[#cddbd7]"
          />
        </div>
        <button
          type="button"
          onClick={clearFilters}
          className="inline-flex items-center justify-center gap-1.5 rounded-md border border-[#c8d9e3] bg-white px-3 py-2 text-xs font-medium text-[#526a74] hover:bg-[#edf4f8]"
        >
          <Filter className="h-3.5 w-3.5" />
          Clear filters
        </button>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
        <SelectField label="Order" value={filters.sort_by} onChange={(value) => updateFilter("sort_by", value as SortBy)}>
          <option value="updated_at">Most recently updated</option>
          <option value="first_contacted_precise_at">First contacted</option>
          <option value="firm_name">Firm name</option>
          <option value="conversation_count">Conversations</option>
        </SelectField>
        <SearchableMultiSelectField
          label="ICP tier"
          values={filters.icp_tier}
          options={ICP_TIER_OPTIONS}
          emptyLabel="Any tier"
          searchPlaceholder="Search tiers..."
          onChange={(values) => updateFilter("icp_tier", values as PifTier[])}
        />
        <SearchableMultiSelectField
          label="Entity type"
          values={filters.entity_type}
          options={ENTITY_TYPE_OPTIONS}
          emptyLabel="Any entity"
          searchPlaceholder="Search entities..."
          onChange={(values) => updateFilter("entity_type", values)}
        />
        <InputField label="Recently researched" value={filters.recently_researched} onChange={(value) => updateFilter("recently_researched", value)} placeholder="days" inputMode="numeric" />
        <SearchableMultiSelectField
          label="Contact emails"
          values={filters.contact_email_range}
          options={COUNT_RANGE_OPTIONS}
          emptyLabel="Any count"
          searchPlaceholder="Search ranges..."
          formatValue={formatCountRange}
          onChange={(values) => updateFilter("contact_email_range", values)}
        />
        <SearchableMultiSelectField
          label="Staff count"
          values={filters.staff_count_range}
          options={COUNT_RANGE_OPTIONS}
          emptyLabel="Any count"
          searchPlaceholder="Search ranges..."
          formatValue={formatCountRange}
          onChange={(values) => updateFilter("staff_count_range", values)}
        />
        <SelectField label="Autoresponse" value={filters.autorespond_window} onChange={(value) => updateFilter("autorespond_window", value)}>
          <option value="any">Any</option>
          <option value="24h">Sent in last 24 hours</option>
          <option value="7d">Sent in last 7 days</option>
          <option value="30d">Sent in last 30 days</option>
          <option value="90d">Sent in last 90 days</option>
          <option value="ever">Ever sent</option>
          <option value="never">Never sent</option>
        </SelectField>
        <SearchableMultiSelectField
          label="Autoresponse type"
          values={filters.autorespond_type}
          options={AUTORESPOND_TYPE_OPTIONS}
          emptyLabel="Any type"
          searchPlaceholder="Search types..."
          formatValue={formatLabel}
          onChange={(values) => updateFilter("autorespond_type", values)}
        />
        <SelectField label="Website" value={filters.website_presence} onChange={(value) => updateFilter("website_presence", value as WebsitePresence)}>
          {WEBSITE_PRESENCE.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
        </SelectField>
        <SearchableMultiSelectField
          label="Research"
          values={filters.research_presence}
          options={STATUS_FILTER_OPTIONS}
          emptyLabel="Any status"
          searchPlaceholder="Search statuses..."
          formatValue={formatLabel}
          onChange={(values) => updateFilter("research_presence", values)}
        />
        <SearchableMultiSelectField
          label="Staff research"
          values={filters.staff_presence}
          options={STATUS_FILTER_OPTIONS}
          emptyLabel="Any status"
          searchPlaceholder="Search statuses..."
          formatValue={formatLabel}
          onChange={(values) => updateFilter("staff_presence", values)}
        />
        <SearchableMultiSelectField
          label="Job postings"
          values={filters.job_postings_presence}
          options={JOB_POSTING_PRESENCE_OPTIONS}
          emptyLabel="Any status"
          searchPlaceholder="Search statuses..."
          onChange={(values) => updateFilter("job_postings_presence", values)}
        />
        <SearchableMultiSelectField
          label="Job trigger"
          values={filters.job_posting_role}
          options={JOB_POSTING_ROLE_OPTIONS}
          emptyLabel="Any role"
          searchPlaceholder="Search roles..."
          onChange={(values) => updateFilter("job_posting_role", values)}
        />
        <SearchableMultiSelectField
          label="Job signal"
          values={filters.job_posting_tag}
          options={JOB_TRIGGER_TAG_OPTIONS}
          emptyLabel="Any signal"
          searchPlaceholder="Search signals..."
          formatValue={formatLabel}
          onChange={(values) => updateFilter("job_posting_tag", values)}
        />
        <InputField
          label="Job text"
          value={filters.job_posting_query}
          onChange={(value) => updateFilter("job_posting_query", value)}
          placeholder="CRM, conversion, 24/7..."
        />
        <SelectField label="Job posted" value={filters.job_posted_within_days} onChange={(value) => updateFilter("job_posted_within_days", value)}>
          <option value="">Any date</option>
          <option value="7">Last 7 days</option>
          <option value="14">Last 14 days</option>
          <option value="30">Last 30 days</option>
          <option value="90">Last 90 days</option>
        </SelectField>
        <SelectField label="Behavior" value={filters.behavior_presence} onChange={(value) => updateFilter("behavior_presence", value as SimplePresence)}>
          {PRESENCE.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
        </SelectField>
        <SelectField label="ICP" value={filters.icp_presence} onChange={(value) => updateFilter("icp_presence", value as SimplePresence)}>
          {PRESENCE.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
        </SelectField>
        <SearchableMultiSelectField
          label="Vendor"
          values={filters.vendor}
          options={[
            { value: "__missing", label: "No vendors detected" },
            ...vendorOptions.map((option) => ({ value: option.vendor, label: option.label, count: option.count })),
          ]}
          emptyLabel="Any vendor"
          searchPlaceholder="Search vendors..."
          onChange={(values) => updateFilter("vendor", values)}
        />
        <SelectField label="Record source" value={filters.record_origin} onChange={(value) => updateFilter("record_origin", value as RecordOrigin)}>
          <option value="any">Any source</option>
          <option value="manual">Manually added</option>
          <option value="synced">Synced</option>
        </SelectField>
        <SelectField label="First contact period" value={filters.first_contact_period} onChange={(value) => updateFilter("first_contact_period", value as FirstContactPeriod)}>
          <option value="any">Any period</option>
          <option value="last_1_month">Last 1 month</option>
          <option value="last_6_months">Last 6 months</option>
          <option value="custom">Custom</option>
        </SelectField>
        {filters.first_contact_period === "custom" && (
          <>
            <InputField
              label="First contact from"
              value={filters.first_contacted_from}
              onChange={(value) => updateFilter("first_contacted_from", value)}
              type="date"
            />
            <InputField
              label="First contact to"
              value={filters.first_contacted_to}
              onChange={(value) => updateFilter("first_contacted_to", value)}
              type="date"
            />
          </>
        )}
      </div>
    </div>
  );
}

function SelectField({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="block text-[11px] font-semibold uppercase text-[#61767e]">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full rounded-md border border-[#cfdbdf] bg-white px-2 py-1.5 text-sm normal-case text-[#20343b] focus:border-[#43838a] focus:outline-none focus:ring-1 focus:ring-[#43838a]"
      >
        {children}
      </select>
    </label>
  );
}

function SearchableMultiSelectField({
  label,
  values,
  options,
  emptyLabel,
  searchPlaceholder,
  formatValue = (value) => value,
  onChange,
}: {
  label: string;
  values: string[];
  options: Array<{ value: string; label?: string; count?: number }>;
  emptyLabel: string;
  searchPlaceholder: string;
  formatValue?: (value: string) => string;
  onChange: (values: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const selected = useMemo(() => new Set(values), [values]);
  const optionLabels = useMemo(
    () => new Map(options.map((option) => [option.value, option.label ?? formatValue(option.value)])),
    [formatValue, options],
  );
  const labelFor = (value: string) => optionLabels.get(value) ?? formatValue(value);
  const filteredOptions = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return options
      .filter((option) => !needle || (option.label ?? formatValue(option.value)).toLocaleLowerCase().includes(needle))
      .sort((left, right) => Number(selected.has(right.value)) - Number(selected.has(left.value)));
  }, [formatValue, options, query, selected]);
  const visibleOptions = filteredOptions.slice(0, 200);
  const summary = values.length === 0
    ? emptyLabel
    : values.length === 1
      ? labelFor(values[0])
      : `${values.length} selected`;

  const close = () => {
    setOpen(false);
    setQuery("");
  };

  return (
    <div className="block text-[11px] font-semibold uppercase text-[#61767e]">
      <div>{label}</div>
      <div
        className="relative mt-1"
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) close();
        }}
      >
        <button
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label={`${label} filter`}
          onClick={() => {
            if (open) close();
            else setOpen(true);
          }}
          className="flex w-full items-center justify-between gap-2 rounded-md border border-[#cfdbdf] bg-white px-2 py-1.5 text-left text-sm font-normal normal-case text-[#20343b] focus:border-[#43838a] focus:outline-none focus:ring-1 focus:ring-[#43838a]"
          title={values.length ? values.map(labelFor).join(", ") : undefined}
        >
          <span className={cn("truncate", values.length === 0 && "text-neutral-500")}>{summary}</span>
          <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 text-neutral-400 transition", open && "rotate-180")} />
        </button>
        {open && (
          <div className="absolute left-0 z-40 mt-1 w-full min-w-72 overflow-hidden rounded-md border border-[#cbdadd] bg-white shadow-lg">
            <div className="flex items-center gap-2 border-b border-neutral-100 p-2">
              <Search className="h-3.5 w-3.5 shrink-0 text-neutral-400" />
              <input
                autoFocus
                type="search"
                aria-label={`Search ${label.toLocaleLowerCase()}`}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") close();
                }}
                placeholder={searchPlaceholder}
                className="min-w-0 flex-1 text-sm font-normal normal-case tracking-normal text-neutral-800 placeholder:text-neutral-400 focus:outline-none"
              />
              {values.length > 0 && (
                <button
                  type="button"
                  onClick={() => onChange([])}
                  title={`Clear selected ${label.toLocaleLowerCase()}`}
                  className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <div role="listbox" aria-multiselectable="true" className="max-h-72 overflow-y-auto py-1">
              {visibleOptions.map((option) => {
                const checked = selected.has(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="option"
                    aria-selected={checked}
                    onClick={() => {
                      onChange(checked
                        ? values.filter((value) => value !== option.value)
                        : [...values, option.value]);
                    }}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left normal-case tracking-normal hover:bg-neutral-50"
                  >
                    <span className={cn(
                      "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                      checked ? "border-[#176b70] bg-[#176b70] text-white" : "border-neutral-300 bg-white",
                    )}>
                      {checked && <Check className="h-3 w-3" />}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm font-normal text-neutral-800">
                      {option.label ?? formatValue(option.value)}
                    </span>
                    {option.count !== undefined && (
                      <span className="shrink-0 text-[11px] text-neutral-400">{option.count.toLocaleString()}</span>
                    )}
                  </button>
                );
              })}
              {filteredOptions.length === 0 && (
                <div className="px-3 py-4 text-center text-xs font-normal normal-case tracking-normal text-neutral-500">
                  No matches
                </div>
              )}
            </div>
            {filteredOptions.length > visibleOptions.length && (
              <div className="border-t border-neutral-100 px-3 py-2 text-[11px] font-normal normal-case tracking-normal text-neutral-500">
                {visibleOptions.length.toLocaleString()} of {filteredOptions.length.toLocaleString()} matches
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function InputField({
  label,
  value,
  onChange,
  placeholder,
  inputMode,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  inputMode?: "numeric";
  type?: React.HTMLInputTypeAttribute;
}) {
  return (
    <label className="block text-[11px] font-semibold uppercase text-[#61767e]">
      {label}
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        inputMode={inputMode}
        className="mt-1 w-full rounded-md border border-[#cfdbdf] bg-white px-2 py-1.5 text-sm normal-case text-[#20343b] placeholder:text-[#8a9aa0] focus:border-[#43838a] focus:outline-none focus:ring-1 focus:ring-[#43838a]"
      />
    </label>
  );
}

function ContactLookupField({
  kind,
  label,
  value,
  onChange,
}: {
  kind: "name" | "firm";
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const debouncedQuery = useDebouncedValue(value.trim(), 200);
  const optionsQuery = useQuery({
    queryKey: ["pif", "contact-lookup", kind, debouncedQuery],
    queryFn: async (): Promise<ContactLookupOption[]> => {
      if (kind === "name") {
        const response = await listPifPeople({
          name: debouncedQuery || undefined,
          source: "all",
          leader: "any",
          page: 1,
          page_size: 25,
        });
        const seen = new Set<string>();
        return response.items.flatMap((person) => {
          const name = person.name?.trim();
          if (!name || seen.has(name.toLocaleLowerCase())) return [];
          seen.add(name.toLocaleLowerCase());
          return [{
            value: name,
            label: name,
            secondary: [person.title, person.firm_name].filter(Boolean).join(" · ") || undefined,
          }];
        });
      }

      const response = await listMirroredPifInfo({
        search: debouncedQuery || undefined,
        sort_by: "firm_name",
        page: 1,
        page_size: 25,
        active_only: true,
      });
      return response.items.flatMap((firm) => {
        const firmName = firm.firm_name?.trim();
        if (!firmName) return [];
        return [{
          value: firmName,
          label: firmName,
          secondary: firm.canonical_website || firm.website || undefined,
        }];
      });
    },
    enabled: open,
    staleTime: 30_000,
  });
  const options = optionsQuery.data ?? [];

  return (
    <label className="relative block text-[11px] font-semibold uppercase text-[#61767e]">
      {label}
      <div className="relative mt-1">
        <input
          type="text"
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setOpen(false);
          }}
          autoComplete="off"
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          aria-controls={`${kind}-contact-options`}
          placeholder={kind === "name" ? "Search names..." : "Search firms..."}
          className="w-full rounded-md border border-[#cfdbdf] bg-white py-1.5 pl-2 pr-8 text-sm normal-case text-[#20343b] placeholder:text-[#8a9aa0] focus:border-[#43838a] focus:outline-none focus:ring-1 focus:ring-[#43838a]"
        />
        <span className="pointer-events-none absolute inset-y-0 right-2 flex items-center text-neutral-400">
          {optionsQuery.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
        </span>
      </div>
      {open && (
        <div
          id={`${kind}-contact-options`}
          role="listbox"
          className="absolute z-30 mt-1 max-h-64 w-full min-w-64 overflow-y-auto rounded-md border border-neutral-200 bg-white py-1 normal-case tracking-normal shadow-lg"
        >
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              role="option"
              aria-selected={option.value === value}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                onChange(option.value);
                setOpen(false);
              }}
              className="block w-full px-3 py-2 text-left hover:bg-neutral-50"
            >
              <span className="block truncate text-sm font-medium text-neutral-800">{option.label}</span>
              {option.secondary && <span className="block truncate text-[11px] text-neutral-500">{option.secondary}</span>}
            </button>
          ))}
          {!optionsQuery.isFetching && options.length === 0 && (
            <div className="px-3 py-3 text-xs text-neutral-500">
              No matching {kind === "name" ? "names" : "firms"}.
            </div>
          )}
        </div>
      )}
    </label>
  );
}

function LeadsViewTabs({
  value,
  onChange,
}: {
  value: LeadsView;
  onChange: (value: LeadsView) => void;
}) {
  const baseClassName = "inline-flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-2 text-xs font-semibold transition-colors sm:flex-none";
  const activeClassName = "bg-[#176b70] text-white shadow-sm";

  return (
    <div className="grid w-full grid-cols-2 rounded-lg border border-[#cfdce0] bg-[#e8eef0] p-1 shadow-inner sm:inline-flex sm:w-auto">
      <button
        type="button"
        onClick={() => onChange("priority")}
        className={cn(
          baseClassName,
          value === "priority" ? activeClassName : "text-[#8a5c08] hover:bg-white/80",
        )}
      >
        <Activity className="h-3.5 w-3.5" />
        Priority
      </button>
      <button
        type="button"
        onClick={() => onChange("firms")}
        className={cn(
          baseClassName,
          value === "firms" ? activeClassName : "text-[#2f6f9d] hover:bg-white/80",
        )}
      >
        <Database className="h-3.5 w-3.5" />
        Firms
      </button>
      <button
        type="button"
        onClick={() => onChange("contacts")}
        className={cn(
          baseClassName,
          value === "contacts" ? activeClassName : "text-[#247153] hover:bg-white/80",
        )}
      >
        <Users className="h-3.5 w-3.5" />
        Contacts
      </button>
      <button
        type="button"
        onClick={() => onChange("job_listings")}
        className={cn(
          baseClassName,
          value === "job_listings" ? activeClassName : "text-[#a9535b] hover:bg-white/80",
        )}
      >
        <Briefcase className="h-3.5 w-3.5" />
        Job listings
      </button>
    </div>
  );
}

const JOB_LISTING_CATEGORIES = [
  "intake_conversion",
  "marketing_growth",
  "case_operations",
  "attorney_legal",
  "client_communication",
  "firm_operations",
  "technology_data",
  "finance_billing",
  "executive_leadership",
  "other",
] as const;

function JobListingsView() {
  const careerSearch = useQuery({ queryKey: ["pif", "career-search"], queryFn: getCareerSearchStatus, refetchInterval: 30_000, retry: false });
  const [filters, setFilters] = useState<PifJobPostingsListParams>({ page: 1, page_size: 25 });
  const debouncedSearch = useDebouncedValue(filters.search ?? "", 250);
  const queryParams = useMemo(() => ({ ...filters, search: debouncedSearch || undefined }), [debouncedSearch, filters]);
  const query = useQuery({
    queryKey: ["pif", "job-postings", queryParams],
    queryFn: () => listMirroredPifJobPostings(queryParams),
  });
  const dailyStatsQuery = useQuery({
    queryKey: ["pif", "job-postings", "daily-stats", 14],
    queryFn: () => getPifJobResearchDailyStats(14),
    refetchInterval: 30_000,
  });
  const items = query.data?.items ?? [];
  const page = query.data?.page ?? filters.page ?? 1;
  const totalPages = query.data?.total_pages ?? 0;
  const update = <K extends keyof PifJobPostingsListParams>(key: K, value: PifJobPostingsListParams[K]) => {
    setFilters((current) => ({ ...current, [key]: value, page: 1 }));
  };
  const setPage = (nextPage: number) => setFilters((current) => ({ ...current, page: Math.max(1, nextPage) }));

  return (
    <section className="space-y-3">
      {careerSearch.data && <div className="border-y border-neutral-200 px-3 py-3 text-xs text-neutral-600">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <strong className="text-neutral-900">Daily PI technology search</strong>
          <span>{careerSearch.data.schedule_enabled ? `${careerSearch.data.config.local_time} ${careerSearch.data.config.timezone}` : "Disabled"}</span>
          {careerSearch.data.next_due_at && <span>Next due {formatDateTime(careerSearch.data.next_due_at)}</span>}
          {careerSearch.data.runs[0] && <span>{formatLabel(careerSearch.data.runs[0].status)} · {careerSearch.data.runs[0].result.new_jobs} new · {careerSearch.data.runs[0].result.verified} verified</span>}
        </div>
        {!!careerSearch.data.runs[0]?.result.errors.length && <details className="mt-2 text-rose-700">
          <summary className="cursor-pointer">{careerSearch.data.runs[0].result.errors.length} processing errors</summary>
          {careerSearch.data.runs[0].result.errors.map((error, index) => <p key={index} className="mt-1 break-words">{error.error}</p>)}
        </details>}
        {!!careerSearch.data.runs[0]?.result.candidate_rejections?.length && <details className="mt-2 text-amber-800">
          <summary className="cursor-pointer">{careerSearch.data.runs[0].result.candidate_rejections.length} candidates not accepted</summary>
          {careerSearch.data.runs[0].result.candidate_rejections.map((item, index) => <p key={index} className="mt-1 break-words">{item.reason}</p>)}
        </details>}
      </div>}
      {careerSearch.isError && <p className="text-xs text-amber-700">Daily career search status unavailable</p>}
      <JobResearchDailyDashboard
        data={dailyStatsQuery.data}
        loading={dailyStatsQuery.isLoading}
        error={dailyStatsQuery.error}
      />
      <div className="rounded-lg border border-[#cbdde9] bg-[#f7fafc] p-3 shadow-sm">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-9">
          <InputField
            label="Search"
            value={filters.search ?? ""}
            onChange={(value) => update("search", value || undefined)}
            placeholder="Firm, title, description..."
          />
          <SelectField label="Category" value={filters.role_category ?? ""} onChange={(value) => update("role_category", value || undefined)}>
            <option value="">Any category</option>
            {JOB_LISTING_CATEGORIES.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
          </SelectField>
          <SelectField label="Signal" value={filters.trigger_tag ?? ""} onChange={(value) => update("trigger_tag", value || undefined)}>
            <option value="">Any signal</option>
            {JOB_TRIGGER_TAGS.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
          </SelectField>
          <InputField
            label="Technology"
            value={filters.technology ?? ""}
            onChange={(value) => update("technology", value || undefined)}
            placeholder="Filevine, Lead Docket..."
          />
          <SelectField label="GTM relevance" value={filters.gtm_relevance ?? ""} onChange={(value) => update("gtm_relevance", value as PifJobPostingsListParams["gtm_relevance"])}>
            <option value="">Any relevance</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </SelectField>
          <SelectField
            label="Remote scope"
            value={filters.remote_scope ?? ""}
            onChange={(value) => update("remote_scope", value as PifJobPostingsListParams["remote_scope"])}
          >
            <option value="">Any scope</option>
            <option value="remote">Remote</option>
            <option value="global">Global remote</option>
            <option value="not_global">Not global remote</option>
          </SelectField>
          <SelectField
            label="Contract type"
            value={filters.contract_status ?? ""}
            onChange={(value) => update("contract_status", value as PifJobPostingsListParams["contract_status"])}
          >
            <option value="">Any type</option>
            <option value="contract">Contract</option>
            <option value="non_contract">Non-contract</option>
            <option value="unknown">Unknown</option>
          </SelectField>
          <SelectField label="Posted" value={filters.posted_within_days ? String(filters.posted_within_days) : ""} onChange={(value) => update("posted_within_days", value ? Number(value) : undefined)}>
            <option value="">Any date</option>
            <option value="7">Last 7 days</option>
            <option value="14">Last 14 days</option>
            <option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option>
          </SelectField>
          <SelectField
            label="Order"
            value={filters.order ?? "posted_desc"}
            onChange={(value) => update("order", value as PifJobPostingsListParams["order"])}
          >
            <option value="posted_desc">Latest posted</option>
            <option value="found_desc">Latest found</option>
          </SelectField>
        </div>
        <div className="mt-3 flex items-center justify-between text-xs text-neutral-500">
          <span>{query.data?.total.toLocaleString() ?? "—"} job listings</span>
          <button
            type="button"
            onClick={() => setFilters({ page: 1, page_size: 25 })}
            className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
          >
            <Filter className="h-3.5 w-3.5" />
            Clear filters
          </button>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-[#cfdde2] bg-white shadow-sm">
        {query.isLoading && <div className="px-5 py-8 text-center text-xs text-neutral-400">Loading job listings...</div>}
        {query.isError && !query.isLoading && (
          <div className="px-5 py-8 text-center text-xs text-rose-600">
            {query.error instanceof Error ? query.error.message : "Job listing query failed"}
          </div>
        )}
        {!query.isLoading && !query.isError && items.length === 0 && (
          <div className="px-5 py-8 text-center text-xs text-neutral-400">No job listings match the filters.</div>
        )}
        {items.length > 0 && (
          <div className="mobile-table-card overflow-hidden">
            <table className="w-full table-fixed divide-y divide-neutral-100 text-sm">
              <thead className="bg-[#edf3f5] text-left text-[11px] uppercase text-[#5a717a]">
                <tr>
                  <th className="w-[18%] px-3 py-2 font-medium">Role</th>
                  <th className="w-[15%] px-3 py-2 font-medium">Firm</th>
                  <th className="w-[12%] px-3 py-2 font-medium">Posted</th>
                  <th className="w-[14%] px-3 py-2 font-medium">Category</th>
                  <th className="w-[18%] px-3 py-2 font-medium">Signals</th>
                  <th className="w-[8%] px-3 py-2 font-medium">Technology</th>
                  <th className="w-[6%] px-3 py-2 font-medium">Source</th>
                  <th className="w-[9%] px-3 py-2 font-medium">Application</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {items.map((posting, index) => <JobListingRow key={`${posting.firm_id}-${posting.source_url}-${posting.title}-${index}`} posting={posting} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between text-xs text-neutral-500">
        <span>Page {page} of {totalPages || 1} ({query.data?.total.toLocaleString() ?? 0} listings)</span>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setPage(page - 1)} disabled={page <= 1} className="inline-flex items-center gap-1 rounded-md border border-neutral-300 px-2.5 py-1 text-xs font-medium disabled:opacity-30">
            <ChevronLeft className="h-3 w-3" />
            Prev
          </button>
          <button type="button" onClick={() => setPage(Math.min(totalPages || 1, page + 1))} disabled={page >= (totalPages || 1)} className="inline-flex items-center gap-1 rounded-md border border-neutral-300 px-2.5 py-1 text-xs font-medium disabled:opacity-30">
            Next
            <ChevronRight className="h-3 w-3" />
          </button>
        </div>
      </div>
    </section>
  );
}

function JobResearchDailyDashboard({
  data,
  loading,
  error,
}: {
  data: Awaited<ReturnType<typeof getPifJobResearchDailyStats>> | undefined;
  loading: boolean;
  error: Error | null;
}) {
  const today = data?.today;
  const recent = data?.daily.slice(0, 7) ?? [];
  const maxJobs = Math.max(1, ...recent.map((day) => day.job_postings_found));

  return (
    <section aria-label="Daily job research" className="rounded-lg border border-[#d8cfeb] bg-[#fbf9fd] p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-[#372c49]">Today&apos;s job research</h2>
          <p className="mt-0.5 text-xs text-neutral-500">
            Firms processed and job postings found on each UTC research day.
          </p>
        </div>
        {data && (
          <div className="rounded-full bg-[#eee8f6] px-3 py-1 text-xs font-medium text-[#68557f]">
            {data.queue.in_progress.toLocaleString()} running · {data.queue.queued.toLocaleString()} queued
          </div>
        )}
      </div>

      {loading && <div className="py-6 text-center text-xs text-neutral-400">Loading daily research totals...</div>}
      {error && <div className="py-6 text-center text-xs text-rose-600">{error.message}</div>}
      {today && (
        <>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile tone="blue" icon={<CheckCircle2 className="h-4 w-4" />} label="Firms processed today" value={today.firms_processed} />
            <MetricTile tone="green" icon={<Users className="h-4 w-4" />} label="Firms with openings" value={today.firms_with_openings} />
            <MetricTile tone="amber" icon={<Briefcase className="h-4 w-4" />} label="Job postings found" value={today.job_postings_found} />
            <MetricTile tone="rose" icon={<AlertTriangle className="h-4 w-4" />} label="Failed today" value={today.firms_failed} />
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[620px] text-xs">
              <thead className="border-b border-[#ddd3eb] text-left text-[11px] uppercase text-[#6d617c]">
                <tr>
                  <th className="py-2 pr-3 font-medium">Research day</th>
                  <th className="px-3 py-2 text-right font-medium">Processed</th>
                  <th className="px-3 py-2 text-right font-medium">With openings</th>
                  <th className="px-3 py-2 text-right font-medium">Postings</th>
                  <th className="w-[34%] py-2 pl-4 font-medium">Postings found</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {recent.map((day) => (
                  <JobResearchDailyRow key={day.date} day={day} maxJobs={maxJobs} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function JobResearchDailyRow({ day, maxJobs }: { day: PifJobResearchDailyStat; maxJobs: number }) {
  const width = day.job_postings_found ? Math.max(4, (day.job_postings_found / maxJobs) * 100) : 0;
  return (
    <tr>
      <td className="py-2.5 pr-3 font-medium text-neutral-700">{formatDailyStatDate(day.date)}</td>
      <td className="px-3 py-2.5 text-right text-neutral-600">{day.firms_processed.toLocaleString()}</td>
      <td className="px-3 py-2.5 text-right text-neutral-600">{day.firms_with_openings.toLocaleString()}</td>
      <td className="px-3 py-2.5 text-right font-medium text-neutral-800">{day.job_postings_found.toLocaleString()}</td>
      <td className="py-2.5 pl-4">
        <div className="h-2 w-full overflow-hidden rounded-sm bg-[#ece6f3]" aria-label={`${day.job_postings_found} postings found`}>
          <div className="h-full bg-[#7c6db0]" style={{ width: `${width}%` }} />
        </div>
      </td>
    </tr>
  );
}

function formatDailyStatDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}

type OpenJobAgentResult = {
  candidate: Candidate;
  categories: JobAgentConfig["resume_categories"];
  created: boolean;
};

function JobListingRow({ posting }: { posting: PifJobPostingResult }) {
  const [agentOpen, setAgentOpen] = useState(false);
  const openAgent = useMutation({
    mutationFn: () => jobAgentRequest<OpenJobAgentResult>("/listings/open", {
      firm_id: posting.firm_id,
      job_id: posting.job_id || null,
      source_url: posting.source_url,
      title: posting.title,
      location: posting.location || null,
    }),
  });
  const launch = () => {
    setAgentOpen(true);
    openAgent.mutate();
  };
  return (
    <>
    <tr className="transition-colors hover:bg-[#f3f8fa]">
      <td data-label="Role" className="min-w-0 px-3 py-3">
        <div className="line-clamp-2 font-medium text-neutral-900">{display(posting.title)}</div>
        <div className="mt-0.5 truncate text-[11px] text-neutral-500">{[posting.location, posting.employment_type].filter(Boolean).join(" · ") || "—"}</div>
      </td>
      <td data-label="Firm" className="min-w-0 px-3 py-3">
        <Link href={`/firms/${encodeURIComponent(posting.firm_id)}`} className="block truncate text-blue-600 hover:underline">{display(posting.firm_name)}</Link>
        <div className="truncate text-[11px] text-neutral-400">{formatLabel(posting.entity_type ?? "unknown")}</div>
      </td>
      <td data-label="Posted" className="px-3 py-3 text-xs text-neutral-600">
        <div>{posting.posted_date ? formatDateOnly(posting.posted_date) : "Publication unknown"}</div>
        <div className="mt-0.5 text-[11px] text-neutral-400">Found {formatDateOnly(posting.found_at)}</div>
        {posting.ats_created_at && !posting.posted_date && <div className="text-[11px] text-neutral-500">ATS created {formatDateOnly(posting.ats_created_at)}</div>}
        {posting.last_checked_at && <div className="text-[11px] text-neutral-400">Checked {formatDateOnly(posting.last_checked_at)}</div>}
      </td>
      <td data-label="Category" className="px-3 py-3"><div className="flex flex-wrap gap-1"><JobTag value={formatLabel(posting.role_category ?? "other")} /><JobTag value={posting.contract_status === "contract" ? "Contract" : posting.contract_status === "non_contract" ? "Non-contract" : "Contract unknown"} emphasis={posting.contract_status === "contract"} />{posting.global_remote ? <JobTag value="Global remote" emphasis /> : posting.work_arrangement === "remote" ? <JobTag value="Remote" emphasis /> : null}{posting.colombia_eligibility && <JobTag value={`Colombia: ${formatLabel(posting.colombia_eligibility)}`} />}{posting.gtm_relevance && <JobTag value={`${formatLabel(posting.gtm_relevance)} GTM`} emphasis={posting.gtm_relevance === "high"} />}</div>{posting.remote_eligibility && <p className="mt-1 text-[11px] text-neutral-500">{posting.remote_eligibility}</p>}</td>
      <td data-label="Signals" className="min-w-0 px-3 py-3"><div className="flex flex-wrap gap-1">{posting.trigger_tags.length ? posting.trigger_tags.map((tag) => <JobTag key={tag} value={formatLabel(tag)} />) : <span className="text-xs text-neutral-400">—</span>}</div></td>
      <td data-label="Technology" className="min-w-0 px-3 py-3"><div className="flex flex-wrap gap-1">{posting.technology_mentions.length ? posting.technology_mentions.map((technology) => <JobTag key={technology} value={technology} emphasis />) : <span className="text-xs text-neutral-400">—</span>}</div></td>
      <td data-label="Source" className="px-3 py-3">{posting.source_url ? <a href={posting.source_url} target="_blank" rel="noreferrer" title={posting.source_name} aria-label={`Open source for ${posting.title}`} className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-neutral-200 text-blue-600 hover:bg-blue-50"><ExternalLink className="h-3.5 w-3.5" /></a> : <span className="text-xs text-neutral-400">—</span>}</td>
      <td data-label="Application" className="px-3 py-3">
        <button type="button" disabled={!posting.source_url || openAgent.isPending} onClick={launch} className="inline-flex items-center gap-1.5 rounded-md border border-neutral-300 bg-white px-2.5 py-1.5 text-[11px] font-medium text-neutral-700 hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-50">
          {openAgent.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          {openAgent.isPending ? "Opening…" : "Job Agent"}
        </button>
      </td>
    </tr>
    <Dialog open={agentOpen} onOpenChange={setAgentOpen}>
      <DialogContent className="max-h-[92dvh] w-[96vw] max-w-5xl overflow-y-auto">
        <DialogTitle className="pr-7 leading-snug">{display(posting.title)}</DialogTitle>
        <DialogDescription>{display(posting.firm_name)} · Opened from Leads / Job listings</DialogDescription>
        {openAgent.isPending && <div className="flex items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 p-4 text-sm text-sky-900"><Loader2 className="h-4 w-4 animate-spin" />Opening the canonical Job Agent record…</div>}
        {openAgent.isError && <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900"><p>{openAgent.error instanceof Error ? openAgent.error.message : "Could not open this listing in Job Agent."}</p><button type="button" onClick={() => openAgent.mutate()} className="mt-3 rounded-md border border-rose-300 bg-white px-3 py-1.5 text-xs font-medium">Try again</button></div>}
        {openAgent.data && <>
          <p className="text-xs leading-relaxed text-neutral-500">This is the same saved application shown in the Job Agent tab. Opening it does not prepare or send an email.</p>
          <JobApplicationControls job={openAgent.data.candidate} categories={openAgent.data.categories} />
          <Link href="/job-agent" className="inline-flex text-xs font-medium underline underline-offset-4">Open the full Job Agent workspace</Link>
        </>}
      </DialogContent>
    </Dialog>
    </>
  );
}

function ContactsView({
  filters,
  setFilters,
  items,
  loading,
  error,
  page,
  total,
  totalPages,
  titleOptions,
  roleOptions,
  vendorOptions,
  savedSearches,
  activeSavedSearchId,
  onApplySavedSearch,
  onCreateSavedSearch,
  onUpdateSavedSearch,
  onDeleteSavedSearch,
  savedSearchPending,
  savedSearchError,
}: {
  filters: PifPeopleListParams;
  setFilters: React.Dispatch<React.SetStateAction<PifPeopleListParams>>;
  items: PifPersonResult[];
  loading: boolean;
  error: unknown;
  page: number;
  total: number;
  totalPages: number;
  titleOptions: PifPeopleFilterOption[];
  roleOptions: PifPeopleFilterOption[];
  vendorOptions: PifVendorOption[];
  savedSearches: SavedLeadSearch[];
  activeSavedSearchId: string;
  onApplySavedSearch: (search: SavedLeadSearch) => void;
  onCreateSavedSearch: (name: string) => void;
  onUpdateSavedSearch: () => void;
  onDeleteSavedSearch: () => void;
  savedSearchPending: boolean;
  savedSearchError: unknown;
}) {
  const [newSearchName, setNewSearchName] = useState("");
  const update = <K extends keyof PifPeopleListParams>(key: K, value: PifPeopleListParams[K]) => {
    setFilters((current) => ({ ...current, [key]: value, page: 1 }));
  };
  const updateMulti = (
    key: "titles" | "role_categories",
    legacyKey: "title" | "role_category",
    values: string[],
  ) => {
    setFilters((current) => ({
      ...current,
      [legacyKey]: undefined,
      [key]: values.length ? values : undefined,
      page: 1,
    }));
  };
  const setPage = (nextPage: number) => {
    setFilters((current) => ({ ...current, page: Math.max(1, nextPage) }));
  };

  return (
    <section className="space-y-3">
      <div className="space-y-3 rounded-lg border border-[#c7ded8] bg-[#f6faf8] p-3 shadow-sm">
        <div className="flex flex-wrap items-end gap-2 border-b border-neutral-100 pb-3">
          <label className="min-w-64 flex-1 text-[11px] font-semibold uppercase text-[#4f7468]">
            Saved search
            <select
              value={activeSavedSearchId}
              onChange={(event) => {
                const search = savedSearches.find((item) => item.id === event.target.value);
                if (search) onApplySavedSearch(search);
              }}
              disabled={savedSearchPending}
              className="mt-1 w-full rounded-md border border-[#c6dad4] bg-white px-2 py-1.5 text-sm normal-case text-[#203b33] focus:border-[#43836e] focus:outline-none focus:ring-1 focus:ring-[#43836e]"
            >
              <option value="">Select saved search</option>
              {savedSearches.map((search) => (
                <option key={search.id} value={search.id}>{search.name}</option>
              ))}
            </select>
          </label>
          <label className="min-w-64 flex-1 text-[11px] font-semibold uppercase text-[#4f7468]">
            New search name
            <input
              value={newSearchName}
              onChange={(event) => setNewSearchName(event.target.value)}
              placeholder="Name these criteria"
              className="mt-1 w-full rounded-md border border-[#c6dad4] bg-white px-2 py-1.5 text-sm normal-case text-[#203b33] placeholder:text-[#899d96] focus:border-[#43836e] focus:outline-none focus:ring-1 focus:ring-[#43836e]"
            />
          </label>
          <button
            type="button"
            onClick={() => {
              const name = newSearchName.trim();
              if (!name) return;
              onCreateSavedSearch(name);
              setNewSearchName("");
            }}
            disabled={!newSearchName.trim() || savedSearchPending}
            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-[#176b70] px-3 text-xs font-medium text-white hover:bg-[#135b60] disabled:opacity-40"
          >
            <Bookmark className="h-3.5 w-3.5" />
            Save new
          </button>
          {activeSavedSearchId ? (
            <>
              <button
                type="button"
                onClick={onUpdateSavedSearch}
                disabled={savedSearchPending}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-neutral-200 px-3 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-40"
              >
                <Save className="h-3.5 w-3.5" />
                Update
              </button>
              <button
                type="button"
                onClick={onDeleteSavedSearch}
                disabled={savedSearchPending}
                title="Delete saved search"
                aria-label="Delete saved search"
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-neutral-200 text-neutral-500 hover:border-rose-200 hover:bg-rose-50 hover:text-rose-700 disabled:opacity-40"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </>
          ) : null}
        </div>
        {savedSearchError ? (
          <div className="text-xs text-rose-600">
            {savedSearchError instanceof Error ? savedSearchError.message : "Saved search request failed"}
          </div>
        ) : null}
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
          <ContactLookupField kind="name" label="Name" value={filters.name ?? ""} onChange={(value) => update("name", value || undefined)} />
          <ContactLookupField kind="firm" label="Firm" value={filters.firm ?? ""} onChange={(value) => update("firm", value || undefined)} />
          <SelectField label="Vendor" value={filters.vendor ?? ""} onChange={(value) => update("vendor", value || undefined)}>
            <option value="">Any vendor</option>
            {vendorOptions.map((option) => (
              <option key={option.vendor} value={option.vendor}>
                {option.label} ({option.count.toLocaleString()})
              </option>
            ))}
          </SelectField>
          <SearchableMultiSelectField
            label="Title"
            values={filters.titles ?? (filters.title ? [filters.title] : [])}
            options={titleOptions}
            emptyLabel="Any title"
            searchPlaceholder="Search titles..."
            onChange={(values) => updateMulti("titles", "title", values)}
          />
          <SearchableMultiSelectField
            label="Role"
            values={filters.role_categories ?? (filters.role_category ? [filters.role_category] : [])}
            options={roleOptions}
            emptyLabel="Any role"
            searchPlaceholder="Search roles..."
            formatValue={formatLabel}
            onChange={(values) => updateMulti("role_categories", "role_category", values)}
          />
          <SelectField label="Source" value={filters.source ?? "all"} onChange={(value) => update("source", value as PeopleSource)}>
            <option value="all">All sources</option>
            <option value="leadership">Leadership</option>
            <option value="staff">Staff</option>
            <option value="contacts">Contacts</option>
          </SelectField>
          <SelectField label="Leader" value={filters.leader ?? "any"} onChange={(value) => update("leader", value as LeaderFilter)}>
            <option value="any">Any</option>
            <option value="leader">Leader</option>
            <option value="non_leader">Not leader</option>
          </SelectField>
          <SelectField label="Email" value={filters.email_presence ?? "any"} onChange={(value) => update("email_presence", value as EmailPresence)}>
            <option value="any">Any</option>
            <option value="has">Has email</option>
            <option value="missing">Missing email</option>
          </SelectField>
        </div>
        <div className="flex items-center justify-between text-xs text-neutral-500">
          <span>{total.toLocaleString()} contacts</span>
          <button
            type="button"
            onClick={() => setFilters({ source: "all", leader: "any", email_presence: "any", page: 1, page_size: filters.page_size ?? 25 })}
            className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
          >
            <Filter className="h-3.5 w-3.5" />
            Clear filters
          </button>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-[#cfdde2] bg-white shadow-sm">
        {loading && <div className="px-5 py-8 text-center text-xs text-neutral-400">Loading contacts...</div>}
        {Boolean(error) && !loading && (
          <div className="px-5 py-8 text-center text-xs text-rose-600">
            {error instanceof Error ? error.message : "Contact list failed"}
          </div>
        )}
        {!loading && !error && items.length === 0 && (
          <div className="px-5 py-8 text-center text-xs text-neutral-400">No contacts match the filters.</div>
        )}
        {items.length > 0 && (
          <div className="mobile-table-card overflow-hidden">
            <table className="w-full table-fixed divide-y divide-neutral-100 text-sm">
              <thead className="bg-[#edf3f5] text-left text-[11px] uppercase text-[#5a717a]">
                <tr>
                  <th className="w-[16%] px-3 py-2 font-medium">Contact</th>
                  <th className="w-[17%] px-3 py-2 font-medium">Firm</th>
                  <th className="w-[17%] px-3 py-2 font-medium">Title</th>
                  <th className="w-[11%] px-3 py-2 font-medium">Role</th>
                  <th className="w-[10%] px-3 py-2 font-medium">Leader</th>
                  <th className="w-[14%] px-3 py-2 font-medium">Reach</th>
                  <th className="w-[8%] px-3 py-2 font-medium">LinkedIn</th>
                  <th className="w-[7%] px-3 py-2 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {items.map((person, index) => (
                  <tr key={`${person.firm_id ?? "firm"}-${person.email ?? person.name}-${index}`} className="transition-colors hover:bg-[#f3f8fa]">
                    <td data-label="Contact" className="min-w-0 px-3 py-3">
                      <div className="truncate font-medium text-neutral-900">{display(person.name)}</div>
                      <div className="text-[11px] text-neutral-500">{formatLabel(person.source ?? "contact")}</div>
                    </td>
                    <td data-label="Firm" className="min-w-0 px-3 py-3">
                      {person.firm_id ? (
                        <Link href={`/firms/${encodeURIComponent(person.firm_id)}`} className="block truncate text-blue-600 hover:underline">
                          {display(person.firm_name)}
                        </Link>
                      ) : (
                        <span className="truncate text-neutral-600">{display(person.firm_name)}</span>
                      )}
                      {person.firm_id && <div className="truncate text-[11px] text-neutral-400">{person.firm_id}</div>}
                    </td>
                    <td data-label="Title" className="min-w-0 px-3 py-3 text-xs text-neutral-600">
                      <span className="line-clamp-2">{display(person.title)}</span>
                    </td>
                    <td data-label="Role" className="min-w-0 px-3 py-3 text-xs text-neutral-600">
                      {display(person.role_category)}
                    </td>
                    <td data-label="Leader" className="px-3 py-3">
                      <span className={cn(
                        "rounded-full px-2 py-0.5 text-[10px] font-semibold",
                        person.is_decision_maker ? "bg-emerald-50 text-emerald-700" : "bg-neutral-100 text-neutral-500",
                      )}>
                        {person.is_decision_maker ? "Leader" : "No"}
                      </span>
                    </td>
                    <td data-label="Reach" className="min-w-0 px-3 py-3 text-xs text-neutral-600">
                      {person.email ? (
                        <a href={`mailto:${person.email}`} className="block truncate text-blue-600 hover:underline">{person.email}</a>
                      ) : (
                        <span className="block truncate">{display(person.phone ?? person.linkedin)}</span>
                      )}
                    </td>
                    <td data-label="LinkedIn" className="px-3 py-3">
                      <LinkedInContactAction person={person} />
                    </td>
                    <td data-label="Updated" className="px-3 py-3 text-xs text-neutral-500">
                      {formatDateTime(person.updated_at ?? null)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between text-xs text-neutral-500">
        <span>
          Page {page} of {totalPages || 1} ({total.toLocaleString()} contacts)
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPage(page - 1)}
            disabled={page <= 1}
            className="inline-flex items-center gap-1 rounded-md border border-neutral-300 px-2.5 py-1 text-xs font-medium disabled:opacity-30"
          >
            <ChevronLeft className="h-3 w-3" />
            Prev
          </button>
          <button
            type="button"
            onClick={() => setPage(Math.min(totalPages || 1, page + 1))}
            disabled={page >= (totalPages || 1)}
            className="inline-flex items-center gap-1 rounded-md border border-neutral-300 px-2.5 py-1 text-xs font-medium disabled:opacity-30"
          >
            Next
            <ChevronRight className="h-3 w-3" />
          </button>
        </div>
      </div>
    </section>
  );
}

function LinkedInContactAction({ person }: { person: PifPersonResult }) {
  return (
    <PersonLinkedInAction
      name={person.name}
      firmName={person.firm_name}
      linkedin={person.linkedin}
    />
  );
}

function PersonLinkedInAction({
  name,
  firmName,
  linkedin,
}: {
  name: string;
  firmName?: string | null;
  linkedin?: string | null;
}) {
  const linkedInUrl = safeLinkedInUrl(linkedin);
  const href = linkedInUrl || linkedInSearchUrl({ name, firm_name: firmName });
  const label = linkedInUrl ? "Open LinkedIn profile" : "Search Google for LinkedIn profile";

  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      title={label}
      aria-label={label}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-md border text-neutral-600 hover:bg-neutral-50",
        linkedInUrl ? "border-blue-200 text-blue-600" : "border-neutral-200",
      )}
    >
      {linkedInUrl ? <Linkedin className="h-3.5 w-3.5" /> : <Search className="h-3.5 w-3.5" />}
    </a>
  );
}

function FirmTableRows({
  firm,
  onOpen,
  onViewContacts,
  onAuthError,
}: {
  firm: PifInfoResponse;
  onOpen: () => void;
  onViewContacts: () => void;
  onAuthError: () => void;
}) {
  const queryClient = useQueryClient();
  const [enrichmentTaskId, setEnrichmentTaskId] = useState<string | null>(() => persistedEnrichmentTaskId(firm));
  const [jobPostingTaskId, setJobPostingTaskId] = useState<string | null>(null);
  const websiteUrl = safeWebsiteUrl(firm.canonical_website ?? firm.website);
  const contactCount = firm.contacts?.length ?? 0;
  const conversationCount = firm.conversation_ids?.length ?? 0;
  const hasBehavior = Boolean(firm.behavioral_data);

  const enrichment = useMutation({
    mutationFn: () => startFullEnrichment(firm.id),
    onSuccess: (response) => setEnrichmentTaskId(response.task_id),
    onError: (error) => {
      if (isAuthError(error)) onAuthError();
    },
  });

  const jobPostingResearch = useMutation({
    mutationFn: () => startJobPostingsResearch(firm.id),
    onSuccess: (response) => setJobPostingTaskId(response.task_id),
    onError: (error) => {
      if (isAuthError(error)) onAuthError();
    },
  });

  const enrichmentStatus = useQuery({
    queryKey: ["emailtag", "enrichment-status", enrichmentTaskId],
    queryFn: () => getFullEnrichmentStatus(enrichmentTaskId ?? ""),
    enabled: Boolean(enrichmentTaskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL_TASK_STATUSES.has(status) ? false : 3_000;
    },
  });

  useEffect(() => {
    const persisted = persistedEnrichmentTaskId(firm);
    if (persisted && persisted !== enrichmentTaskId) setEnrichmentTaskId(persisted);
  }, [firm, enrichmentTaskId]);

  const jobPostingStatus = useQuery({
    queryKey: ["emailtag", "job-posting-research-status", jobPostingTaskId],
    queryFn: () => getProxiedResearchStatus(jobPostingTaskId ?? ""),
    enabled: Boolean(jobPostingTaskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL_TASK_STATUSES.has(status) ? false : 3_000;
    },
  });

  useEffect(() => {
    const status = enrichmentStatus.data?.status;
    if (status && TERMINAL_TASK_STATUSES.has(status)) {
      void queryClient.invalidateQueries({ queryKey: ["emailtag", "firm", firm.id] });
      void queryClient.invalidateQueries({ queryKey: ["emailtag", "firms"] });
    }
  }, [enrichmentStatus.data?.status, firm.id, queryClient]);

  useEffect(() => {
    const status = jobPostingStatus.data?.status;
    if (status && TERMINAL_TASK_STATUSES.has(status)) {
      void queryClient.invalidateQueries({ queryKey: ["emailtag", "firm", firm.id] });
      void queryClient.invalidateQueries({ queryKey: ["emailtag", "firms"] });
    }
  }, [jobPostingStatus.data?.status, firm.id, queryClient]);

  useEffect(() => {
    if (isAuthError(enrichmentStatus.error)) onAuthError();
  }, [enrichmentStatus.error, onAuthError]);

  useEffect(() => {
    if (isAuthError(jobPostingStatus.error)) onAuthError();
  }, [jobPostingStatus.error, onAuthError]);

  const enrichmentRunning = enrichment.isPending || isWorkflowRunning(
    enrichmentStatus.data?.status ?? firm.research_data?.local_enrichment?.status,
  );
  const jobPostingRunning = jobPostingResearch.isPending
    || isWorkflowRunning(jobPostingStatus.data?.status)
    || (!jobPostingTaskId && isWorkflowRunning(firm.research_data?.job_postings_research_status));

  return (
      <tr className="transition-colors hover:bg-[#f3f8fa]">
        <td className="px-2 py-3">
          <button
            type="button"
            onClick={onOpen}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-neutral-200 text-neutral-500 hover:bg-white"
            aria-label={`Open ${firm.firm_name} details`}
            title="Open firm details"
          >
            <PanelRightOpen className="h-4 w-4" />
          </button>
        </td>
        <td data-label="Firm" className="min-w-0 px-2 py-3">
          <div className="flex min-w-0 items-center gap-1.5">
            <button
              type="button"
              onClick={onOpen}
              className="min-w-0 truncate text-left font-medium text-neutral-900 hover:text-blue-700 hover:underline"
            >
              {firm.firm_name}
            </button>
            <span className={cn(
              "shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase",
              firm.manually_added ? "bg-amber-50 text-amber-700" : "bg-neutral-100 text-neutral-500",
            )}>
              {firm.manually_added ? "Manual" : "Synced"}
            </span>
          </div>
          <div className="text-[11px] text-neutral-500">{firm.id}</div>
        </td>
        <td data-label="Entity" className="hidden min-w-0 px-2 py-3 text-xs text-neutral-600 2xl:table-cell">
          <span className="block truncate">{ENTITY_TYPE_LABELS[firm.entity_type] ?? formatLabel(firm.entity_type)}</span>
        </td>
        <td data-label="Website" className="min-w-0 px-2 py-3 text-xs text-neutral-600">
          {websiteUrl ? (
            <a href={websiteUrl} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 text-blue-600 hover:underline">
              <span className="truncate">{firm.canonical_website ?? firm.website}</span>
              <ExternalLink className="h-3 w-3 shrink-0" />
            </a>
          ) : (
            "—"
          )}
          <div className="mt-1">
            <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", websiteStatusColor(firm.website_status))}>
              {firm.website_status ?? "unknown"}
            </span>
          </div>
        </td>
        <td data-label="Staff" className="px-2 py-3">
          <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", statusColor(firm.staff_research_status))}>
            {firm.staff_research_status ?? "missing"}
          </span>
        </td>
        <td data-label="ICP" className="px-2 py-3">
          <div className="flex items-center gap-1.5">
            <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-bold", tierColor(firm.icp_tier))}>
              {firm.icp_tier ?? "—"}
            </span>
            <span className="font-mono text-[11px] text-neutral-500">{firm.icp_score ?? "—"}</span>
          </div>
        </td>
        <td data-label="Research" className="px-2 py-3">
          <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", statusColor(firm.research_status))}>
            {firm.research_status ?? "unknown"}
          </span>
        </td>
        <td data-label="First contact" className="px-2 py-3 text-xs text-neutral-500">
          {firm.first_contacted_precise_at ? formatDateTime(firm.first_contacted_precise_at) : "—"}
        </td>
        <td data-label="Signals" className="hidden px-2 py-3 xl:table-cell">
          <div className="flex flex-wrap gap-1.5">
            <SignalPill icon={<Mail className="h-3 w-3" />} value={firm.emails?.length ?? 0} label="emails" />
            <SignalPill icon={<Users className="h-3 w-3" />} value={contactCount} label="contacts" />
            <SignalPill icon={<Activity className="h-3 w-3" />} value={conversationCount} label="conversations" />
            {hasBehavior && <SignalPill icon={<BarChart3 className="h-3 w-3" />} value="yes" label="behavior" />}
          </div>
        </td>
        <td data-label="Updated" className="px-2 py-3 text-xs text-neutral-500">
          {formatDateTime(firm.updated_at)}
        </td>
        <td data-label="Actions" className="px-2 py-3">
          <div className="flex flex-col items-start gap-1">
            <ActionButton
              onClick={onViewContacts}
              icon={<Users className="h-3.5 w-3.5" />}
            >
              Contacts
            </ActionButton>
            <ActionButton
              onClick={() => enrichment.mutate()}
              pending={enrichmentRunning}
              icon={<Sparkles className="h-3.5 w-3.5" />}
            >
              <span className="xl:hidden">Enrich</span>
              <span className="hidden xl:inline">Run full enrichment</span>
            </ActionButton>
            <ActionButton
              onClick={() => jobPostingResearch.mutate()}
              pending={jobPostingRunning}
              icon={<Briefcase className="h-3.5 w-3.5" />}
            >
              <span className="xl:hidden">Jobs</span>
              <span className="hidden xl:inline">Research job postings</span>
            </ActionButton>
          </div>
          <TaskStatus
            label="Enrichment"
            status={enrichmentStatus.data?.status ?? firm.research_data?.local_enrichment?.status ?? undefined}
            message={enrichmentStatus.data?.message ?? firm.research_data?.local_enrichment?.message ?? errorMessage(enrichment.error)}
            progress={enrichmentStatus.data?.progress_percent ?? firm.research_data?.local_enrichment?.progress_percent ?? undefined}
            currentStage={enrichmentStatus.data?.current_stage ?? firm.research_data?.local_enrichment?.current_stage ?? undefined}
            compact
          />
          <TaskStatus
            label="Job postings"
            status={jobPostingStatus.data?.status ?? firm.research_data?.job_postings_research_status ?? undefined}
            message={jobPostingStatus.data?.message}
            compact
          />
        </td>
      </tr>
  );
}

function BatchResearchPanel({
  title,
  description,
  buttonLabel,
  limit,
  setLimit,
  onQueue,
  pending,
  result,
  error,
  run,
  polling,
}: {
  title: string;
  description: string;
  buttonLabel: string;
  limit: string;
  setLimit: (value: string) => void;
  onQueue: () => void;
  pending: boolean;
  result?: { requested: number; selected: PifInfoResponse[]; queued: unknown[] };
  error: unknown;
  run: BatchResearchRun | null;
  polling: boolean;
}) {
  const [expanded, setExpanded] = useState(true);
  const queuedCount = result?.queued.length ?? 0;
  const rows = run?.rows ?? [];
  const completedRows = rows.filter((row) => row.status === "completed" || row.status === "success");
  const queuedRows = rows.filter((row) => row.task_id && !TERMINAL_TASK_STATUSES.has(row.status));
  const notQueuedRows = rows.filter((row) => !row.task_id);
  const remainingCount = run ? Math.max(0, run.requested - completedRows.length) : 0;

  return (
    <div className="rounded-lg border border-[#c8ddd9] bg-[#f8fbfa] p-3 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="text-sm font-semibold text-neutral-900">{title}</div>
          <div className="mt-1 text-xs text-neutral-500">{description}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-xs font-medium text-neutral-500">
            Firms
            <input
              value={limit}
              onChange={(event) => setLimit(event.target.value.replace(/[^\d]/g, "").slice(0, 3))}
              onBlur={() => {
                const normalized = Math.max(1, Math.min(100, Number(limit) || 1));
                setLimit(String(normalized));
              }}
              inputMode="numeric"
              className="h-8 w-20 rounded-md border border-[#c8d9d5] bg-white px-2 text-sm text-neutral-900 outline-none focus:border-[#43838a]"
            />
          </label>
          <button
            type="button"
            onClick={onQueue}
            disabled={pending}
            className="inline-flex items-center gap-1.5 rounded-md bg-[#176b70] px-3 py-2 text-xs font-medium text-white hover:bg-[#135b60] disabled:opacity-40"
          >
            {pending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {buttonLabel}
          </button>
        </div>
      </div>
      {run && (
        <div className="mt-3 rounded-md border border-[#cfe0dd] bg-[#f2f8f6]">
          <button
            type="button"
            onClick={() => setExpanded((current) => !current)}
            className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
          >
            <span className="flex flex-wrap items-center gap-2 text-xs text-neutral-600">
              <span className="font-semibold text-neutral-900">Batch status</span>
              <BatchCount label="Queued" value={queuedRows.length} />
              <BatchCount label="Completed" value={completedRows.length} />
              <BatchCount label="Remaining" value={remainingCount} />
              {polling && <Loader2 className="h-3.5 w-3.5 animate-spin text-neutral-400" />}
            </span>
            <ChevronDown className={cn("h-4 w-4 text-neutral-400 transition", expanded && "rotate-180")} />
          </button>
          {expanded && (
            <div className="grid gap-3 border-t border-neutral-200 p-3 lg:grid-cols-3">
              <BatchStatusList title="Queued / running" rows={queuedRows} empty="No queued firms." />
              <BatchStatusList title="Completed" rows={completedRows} empty="No completed firms yet." />
              <BatchStatusList title="Not queued yet" rows={notQueuedRows} empty="All selected firms have task IDs." />
            </div>
          )}
        </div>
      )}
      {result && !run && (
        <div className="mt-3 rounded-md bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          Queued {queuedCount} of {result.requested} requested firm{result.requested === 1 ? "" : "s"}.
        </div>
      )}
      {Boolean(error) && (
        <div className="mt-3 flex items-start gap-2 rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-700">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {error instanceof Error ? error.message : "Could not queue research."}
        </div>
      )}
    </div>
  );
}

function BatchCount({ label, value }: { label: string; value: number }) {
  return (
    <span className="rounded-full border border-neutral-200 bg-white px-2 py-0.5">
      {label}: <span className="font-mono text-neutral-900">{value}</span>
    </span>
  );
}

function BatchStatusList({
  title,
  rows,
  empty,
}: {
  title: string;
  rows: BatchResearchRow[];
  empty: string;
}) {
  return (
    <section>
      <div className="mb-2 text-[11px] font-semibold uppercase text-neutral-400">{title}</div>
      {rows.length === 0 ? (
        <div className="rounded-md border border-dashed border-neutral-200 bg-white px-3 py-3 text-xs text-neutral-400">
          {empty}
        </div>
      ) : (
        <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
          {rows.map((row) => (
            <div key={row.pif_id} className="rounded-md border border-neutral-200 bg-white px-3 py-2">
              <div className="truncate text-xs font-medium text-neutral-900">{row.firm_name}</div>
              <div className="mt-1 flex items-center gap-2 text-[11px] text-neutral-500">
                <span className={cn("rounded-full px-2 py-0.5 font-semibold", statusColor(row.status))}>
                  {formatLabel(row.status)}
                </span>
                {row.task_id && <span className="truncate font-mono">{row.task_id}</span>}
              </div>
              {row.message && <div className="mt-1 line-clamp-2 text-[11px] text-neutral-500">{row.message}</div>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function FirmDetailModal({
  pifId,
  onClose,
  onAuthError,
}: {
  pifId: string;
  onClose: () => void;
  onAuthError: () => void;
}) {
  const firmQuery = useQuery({
    queryKey: ["emailtag", "firm-modal", pifId],
    queryFn: () => getMirroredFirm(pifId),
    enabled: Boolean(pifId),
  });

  useEffect(() => {
    if (isAuthError(firmQuery.error)) onAuthError();
  }, [firmQuery.error, onAuthError]);

  return (
    <Dialog open={Boolean(pifId)} onOpenChange={(open) => {
      if (!open) onClose();
    }}>
      <DialogContent className="h-[94dvh] w-[min(96vw,1500px)] max-w-none gap-0 overflow-hidden border-neutral-200 bg-neutral-50 p-0 shadow-2xl sm:rounded-lg [&>button]:z-20 [&>button]:flex [&>button]:h-8 [&>button]:w-8 [&>button]:items-center [&>button]:justify-center [&>button]:rounded-md [&>button]:border [&>button]:border-neutral-200 [&>button]:bg-white [&>button]:opacity-100 [&>button]:shadow-sm [&>button]:focus:ring-neutral-300">
        <DialogTitle className="sr-only">{firmQuery.data?.firm_name ?? "Firm details"}</DialogTitle>
        <DialogDescription className="sr-only">
          Firm research, people, signals, communications, and operational controls.
        </DialogDescription>
        <div className="h-[94dvh] min-h-0 min-w-0 w-full">
          {firmQuery.isLoading && (
            <div className="flex h-full items-center justify-center gap-2 text-sm text-neutral-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading firm details...
            </div>
          )}
          {firmQuery.isError && !isAuthError(firmQuery.error) && (
            <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
              <AlertCircle className="h-6 w-6 text-rose-500" />
              <div>
                <div className="text-sm font-semibold text-neutral-900">Firm details could not be loaded</div>
                <div className="mt-1 text-xs text-neutral-500">
                  {firmQuery.error instanceof Error ? firmQuery.error.message : "The request failed."}
                </div>
              </div>
              <ActionButton onClick={() => void firmQuery.refetch()} icon={<RefreshCw className="h-3.5 w-3.5" />}>
                Retry
              </ActionButton>
            </div>
          )}
          {firmQuery.data && <FirmDetail initialFirm={firmQuery.data} onAuthError={onAuthError} />}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function FirmDetail({ initialFirm, onAuthError }: { initialFirm: PifInfoResponse; onAuthError: () => void }) {
  const queryClient = useQueryClient();
  const [researchTaskId, setResearchTaskId] = useState<string | null>(() => persistedEnrichmentTaskId(initialFirm));

  const firmQuery = useQuery({
    queryKey: ["emailtag", "firm", initialFirm.id],
    queryFn: () => getMirroredFirm(initialFirm.id),
    initialData: initialFirm,
  });

  const firm = firmQuery.data ?? initialFirm;
  useEffect(() => {
    const persisted = persistedEnrichmentTaskId(firm);
    if (persisted && persisted !== researchTaskId) setResearchTaskId(persisted);
  }, [firm, researchTaskId]);

  useEffect(() => {
    if (isAuthError(firmQuery.error)) onAuthError();
  }, [firmQuery.error, onAuthError]);

  const exportFirm = useMutation({
    mutationFn: (format: ExportFormat) => downloadEmailtagExport({ format, pifId: firm.id }),
    onSuccess: ({ blob, filename }) => downloadBlob(blob, filename),
    onError: (error) => {
      if (isAuthError(error)) onAuthError();
    },
  });

  const research = useMutation({
    mutationFn: (kind: "leadership" | "staff") =>
      kind === "leadership" ? startResearch(firm.id) : startStaffResearch(firm.id),
    onSuccess: (response) => setResearchTaskId(response.task_id),
    onError: (error) => {
      if (isAuthError(error)) onAuthError();
    },
  });

  const researchStatus = useQuery({
    queryKey: ["emailtag", "research-status", researchTaskId],
    queryFn: () => getResearchStatus(researchTaskId ?? ""),
    enabled: Boolean(researchTaskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL_TASK_STATUSES.has(status) ? false : 3_000;
    },
  });

  useEffect(() => {
    const status = researchStatus.data?.status;
    if (status && TERMINAL_TASK_STATUSES.has(status)) {
      void queryClient.invalidateQueries({ queryKey: ["emailtag", "firm", firm.id] });
      void queryClient.invalidateQueries({ queryKey: ["emailtag", "firms"] });
    }
  }, [researchStatus.data?.status, firm.id, queryClient]);

  const vendorDetection = useMutation({
    mutationFn: () => detectVendors(firm.id),
    onError: (error) => {
      if (isAuthError(error)) onAuthError();
    },
    onSuccess: (response) => setResearchTaskId(response.task_id),
  });

  const fullEnrichmentRunning = research.isPending || vendorDetection.isPending || isWorkflowRunning(
    researchStatus.data?.status ?? firm.research_data?.local_enrichment?.status,
  );

  const behavior = useMutation({
    mutationFn: () => analyzeBehavior(firm.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["emailtag", "firm", firm.id] });
      void queryClient.invalidateQueries({ queryKey: ["emailtag", "firms"] });
    },
    onError: (error) => {
      if (isAuthError(error)) onAuthError();
    },
  });

  const score = useMutation({
    mutationFn: () => scoreFirm(firm.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["emailtag", "firm", firm.id] });
      void queryClient.invalidateQueries({ queryKey: ["emailtag", "firms"] });
    },
    onError: (error) => {
      if (isAuthError(error)) onAuthError();
    },
  });

  const websiteUrl = safeWebsiteUrl(firm.canonical_website ?? firm.website);
  const enrichmentSteps = buildEnrichmentSteps(
    firm,
    researchStatus.data?.stages ?? firm.research_data?.local_enrichment?.stages,
  );
  const entityLabel = ENTITY_TYPE_LABELS[firm.entity_type] ?? formatLabel(firm.entity_type);
  const addressLabel = firm.addresses?.map(formatAddress).find(Boolean) ?? "";
  const emailCount = firm.emails?.length ?? 0;
  const peopleCount = (firm.leadership?.length ?? 0) + (firm.staff?.length ?? 0);
  const conversationCount = firm.conversation_ids?.length ?? 0;
  const enrichmentStatus = researchStatus.data?.status
    ?? firm.research_data?.local_enrichment?.status
    ?? firm.research_status
    ?? "unknown";
  const tabClassName = "mt-0 min-h-0 flex-1 overflow-y-auto p-4 focus-visible:ring-0 focus-visible:ring-offset-0 sm:p-6";
  const tabTriggerClassName = "h-11 gap-2 rounded-none border-b-2 border-transparent px-3 text-xs text-neutral-500 shadow-none data-[state=active]:border-neutral-900 data-[state=active]:bg-transparent data-[state=active]:text-neutral-900 data-[state=active]:shadow-none sm:px-4";

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col bg-neutral-50">
      <header className="shrink-0 border-b border-neutral-200 bg-white px-4 py-4 pr-14 sm:px-6 sm:pr-16">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-neutral-900 text-white">
              <Building2 className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-lg font-semibold text-neutral-950 sm:text-xl">{firm.firm_name}</h1>
                <span className={cn(
                  "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
                  firm.manually_added ? "bg-amber-50 text-amber-700" : "bg-neutral-100 text-neutral-500",
                )}>
                  {firm.manually_added ? "Manually added" : "Synced"}
                </span>
                <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold", websiteStatusColor(firm.website_status))}>
                  {firm.website_status ?? "unknown"}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neutral-500">
                <span>{entityLabel}</span>
                {(firm.canonical_website ?? firm.website) && (
                  <span className="inline-flex min-w-0 items-center gap-1">
                    <Globe className="h-3 w-3 shrink-0" />
                    <span className="truncate">{firm.canonical_website ?? firm.website}</span>
                  </span>
                )}
                {addressLabel && (
                  <span className="inline-flex min-w-0 items-center gap-1">
                    <MapPin className="h-3 w-3 shrink-0" />
                    <span className="truncate">{addressLabel}</span>
                  </span>
                )}
              </div>
              <div className="mt-1 text-[11px] text-neutral-400">
                Updated {formatDateTime(firm.updated_at)} · Created {formatDateTime(firm.created_at)}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {websiteUrl && (
              <a
                href={websiteUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-2.5 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                Website
              </a>
            )}
            <ActionButton onClick={() => exportFirm.mutate("json")} pending={exportFirm.isPending} icon={<FileJson className="h-3.5 w-3.5" />}>
              JSON
            </ActionButton>
            <ActionButton onClick={() => exportFirm.mutate("csv")} pending={exportFirm.isPending} icon={<Download className="h-3.5 w-3.5" />}>
              CSV
            </ActionButton>
            <ActionButton onClick={() => research.mutate("leadership")} pending={fullEnrichmentRunning} icon={<Sparkles className="h-3.5 w-3.5" />}>
              Run full enrichment
            </ActionButton>
            <ActionButton onClick={() => behavior.mutate()} pending={behavior.isPending} icon={<Activity className="h-3.5 w-3.5" />}>
              Analyze behavior
            </ActionButton>
            <ActionButton onClick={() => score.mutate()} pending={score.isPending} icon={<BarChart3 className="h-3.5 w-3.5" />}>
              Score ICP
            </ActionButton>
          </div>
        </div>
      </header>

      <div className="grid shrink-0 grid-cols-2 divide-x divide-y divide-neutral-200 border-b border-neutral-200 bg-white sm:grid-cols-3 lg:grid-cols-6 lg:divide-y-0">
        <FirmHeaderMetric
          icon={<Sparkles className="h-3.5 w-3.5" />}
          label="Enrichment"
          value={formatLabel(enrichmentStatus)}
          detail={researchStatus.data?.current_stage ? formatLabel(researchStatus.data.current_stage) : "Full workflow"}
        />
        <FirmHeaderMetric
          icon={<Star className="h-3.5 w-3.5" />}
          label="ICP"
          value={firm.icp_tier ? `Tier ${firm.icp_tier}` : "Not scored"}
          detail={firm.icp_score == null ? "No score" : `${firm.icp_score}/100`}
        />
        <FirmHeaderMetric
          icon={<Database className="h-3.5 w-3.5" />}
          label="Research"
          value={formatLabel(firm.research_status ?? "unknown")}
          detail={firm.last_researched_at ? formatDateTime(firm.last_researched_at) : "Never researched"}
        />
        <FirmHeaderMetric
          icon={<Users className="h-3.5 w-3.5" />}
          label="People"
          value={peopleCount.toLocaleString()}
          detail={`${firm.leadership?.length ?? 0} leaders · ${firm.staff?.length ?? 0} staff`}
        />
        <FirmHeaderMetric
          icon={<Mail className="h-3.5 w-3.5" />}
          label="Contact emails"
          value={emailCount.toLocaleString()}
          detail={firm.phones?.length ? `${firm.phones.length} phone numbers` : "No phone numbers"}
        />
        <FirmHeaderMetric
          icon={<Activity className="h-3.5 w-3.5" />}
          label="Conversations"
          value={conversationCount.toLocaleString()}
          detail={firm.behavioral_data ? `${firm.behavioral_data.total_email_count ?? 0} emails analyzed` : "Behavior not analyzed"}
        />
      </div>

      <Tabs defaultValue="overview" className="flex min-h-0 flex-1 flex-col">
        <div className="shrink-0 overflow-x-auto border-b border-neutral-200 bg-white px-3 sm:px-6">
          <TabsList className="h-11 w-max min-w-full justify-start rounded-none bg-transparent p-0">
            <TabsTrigger value="overview" className={tabTriggerClassName}>
              <Building2 className="h-3.5 w-3.5" />
              Overview
            </TabsTrigger>
            <TabsTrigger value="people" className={tabTriggerClassName}>
              <Users className="h-3.5 w-3.5" />
              People
            </TabsTrigger>
            <TabsTrigger value="signals" className={tabTriggerClassName}>
              <Activity className="h-3.5 w-3.5" />
              Signals
            </TabsTrigger>
            <TabsTrigger value="activity" className={tabTriggerClassName}>
              <Mail className="h-3.5 w-3.5" />
              Activity
            </TabsTrigger>
            <TabsTrigger value="data" className={tabTriggerClassName}>
              <Database className="h-3.5 w-3.5" />
              Data
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="overview" className={tabClassName}>
          <div className="mx-auto max-w-[1320px] space-y-4">
            <TaskStatus
              label="Full enrichment"
              status={researchStatus.data?.status ?? firm.research_data?.local_enrichment?.status ?? undefined}
              message={researchStatus.data?.message ?? firm.research_data?.local_enrichment?.message ?? errorMessage(research.error) ?? errorMessage(vendorDetection.error)}
              progress={researchStatus.data?.progress_percent ?? firm.research_data?.local_enrichment?.progress_percent ?? undefined}
              currentStage={researchStatus.data?.current_stage ?? firm.research_data?.local_enrichment?.current_stage ?? undefined}
            />

            <InfoBlock title="Full enrichment workflow">
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                {enrichmentSteps.map((step) => (
                  <WorkflowStep key={step.label} {...step} />
                ))}
              </div>
            </InfoBlock>

            <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
              <InfoBlock title="Firm profile">
                <KeyValue label="Entity type" value={entityLabel} />
                <KeyValue label="First contacted" value={formatDateTime(firm.first_contacted_precise_at)} />
                <KeyValue label="Research status" value={firm.research_status ?? "Unknown"} />
                <KeyValue label="Last researched" value={formatDateTime(firm.last_researched_at)} />
                <KeyValue label="Staff research" value={firm.staff_research_status ?? "Unknown"} />
              </InfoBlock>

              <InfoBlock title="Website resolution">
                <div className="grid gap-x-5 sm:grid-cols-2">
                  <KeyValue label="Canonical" value={firm.canonical_website ?? "Missing"} />
                  <KeyValue label="Raw website" value={firm.website ?? "Missing"} />
                  <KeyValue label="Status" value={firm.website_status ?? "Missing"} />
                  <KeyValue label="Source" value={firm.website_source ?? "Unknown"} />
                  <KeyValue label="Confidence" value={firm.website_confidence == null ? "Unknown" : `${Math.round(firm.website_confidence * 100)}%`} />
                  <KeyValue label="Updated" value={formatDateTime(firm.updated_at)} />
                </div>
              </InfoBlock>
            </div>

            <AIAdoptionPanel posture={firm.research_data?.ai_adoption} history={firm.research_data?.ai_adoption_history} />
            <SitemapMonitorPanel pifId={firm.id} monitor={firm.research_data?.sitemap_monitor} />
          </div>
        </TabsContent>

        <TabsContent value="people" className={tabClassName}>
          <div className="mx-auto max-w-[1320px] space-y-4">
            <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
              <CollapsibleInfoBlock title="Contact data" defaultOpen={false}>
                <KeyValue label="Emails" value={firm.emails?.join(", ") || "—"} />
                <KeyValue label="Phones" value={firm.phones?.join(", ") || "—"} />
                <KeyValue label="Fax" value={firm.fax ?? "—"} />
                <KeyValue
                  label="Addresses"
                  value={firm.addresses?.map(formatAddress).filter(Boolean).join(" · ") || "—"}
                />
                <KeyValue label="Extraction notes" value={firm.extraction_notes ?? "—"} />
              </CollapsibleInfoBlock>

              <CollapsibleInfoBlock title="Front conversation IDs" count={conversationCount} defaultOpen={false}>
                {firm.conversation_ids?.length ? (
                  <div className="flex flex-wrap gap-1.5">
                    {firm.conversation_ids.map((id) => (
                      <a
                        key={id}
                        href={frontConversationUrl(id)}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 rounded-md bg-neutral-100 px-2 py-1 font-mono text-[11px] text-neutral-600 hover:bg-neutral-200 hover:text-neutral-900"
                        title="Open conversation in Front"
                      >
                        {id}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-neutral-400">No conversation IDs.</div>
                )}
              </CollapsibleInfoBlock>
            </div>

            <div className="grid gap-4 xl:grid-cols-3">
              <PeopleList title="Leadership" empty="No leadership records." items={firm.leadership ?? []} firmName={firm.firm_name} />
              <PeopleList title="Staff" empty="No staff records." items={firm.staff ?? []} firmName={firm.firm_name} />
              <ExtractedContacts contacts={firm.contacts ?? []} firmName={firm.firm_name} />
            </div>
          </div>
        </TabsContent>

        <TabsContent value="signals" className={tabClassName}>
          <div className="mx-auto max-w-[1320px] space-y-4">
            <InfoBlock
              title="Vendor stack"
              action={
                <ActionButton
                  onClick={() => vendorDetection.mutate()}
                  pending={fullEnrichmentRunning}
                  icon={<RefreshCw className={cn("h-3.5 w-3.5", fullEnrichmentRunning && "animate-spin")} />}
                >
                  Refresh vendors
                </ActionButton>
              }
            >
              {firm.vendor_stack?.length ? (
                <div className="flex flex-wrap gap-2">
                  {firm.vendor_stack.map((vendor, index) => (
                    <span key={`${vendor.vendor}-${index}`} className="inline-flex items-center gap-1 rounded-full border border-neutral-200 bg-white px-2.5 py-1 text-xs text-neutral-700">
                      <span className="font-medium">{vendor.vendor}</span>
                      <span className="text-neutral-400">{vendor.source}</span>
                      {vendor.confidence && <span className="text-neutral-400">{vendor.confidence}</span>}
                      {vendor.known === false && <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[9px] font-bold text-amber-700">NEW</span>}
                    </span>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-neutral-400">No vendors detected.</div>
              )}
            </InfoBlock>

            <JobPostingsPanel
              research={firm.research_data?.job_postings}
              status={firm.research_data?.job_postings_research_status}
              lastResearchedAt={firm.research_data?.last_job_postings_researched_at}
            />

            <FirmReviewsPanel
              pifId={firm.id}
              firmName={firm.firm_name}
              address={firm.addresses?.[0] ?? null}
            />
          </div>
        </TabsContent>

        <TabsContent value="activity" className={tabClassName}>
          <div className="mx-auto max-w-[1320px] space-y-4">
            <FirmCommunicationsPanel pifId={firm.id} />
            <FirmCallsPanel pifId={firm.id} />
          </div>
        </TabsContent>

        <TabsContent value="data" className={tabClassName}>
          <div className="mx-auto max-w-[1320px] space-y-4">
            <div className="grid gap-4 xl:grid-cols-2">
              <JsonViewer title="Research data" value={firm.research_data} />
              <JsonViewer title="Behavioral data" value={firm.behavioral_data} />
            </div>
            <FirmDangerZone pifId={firm.id} firmName={firm.firm_name} />
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function AIAdoptionPanel({ posture, history = [] }: { posture?: AIAdoptionPosture; history?: AIAdoptionPosture[] }) {
  const evidence = (value: AIAdoptionPosture) => (
    <div className="divide-y divide-neutral-200">
      {value.statements.map((statement, index) => (
        <article key={`${statement.source_url}-${index}`} className="space-y-2 py-3 text-sm">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="font-medium text-neutral-900">{statement.speaker_name || "Firm statement"}</p>
              {statement.speaker_title && <p className="text-xs text-neutral-500">{statement.speaker_title}</p>}
            </div>
            <a href={statement.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-sky-700 hover:underline">
              {statement.source_type.replaceAll("_", " ")} <ExternalLink className="h-3 w-3" />
            </a>
          </div>
          <p className="text-xs text-neutral-500">{statement.scope.replaceAll("_", " ")} · {statement.published_at || "Publication date unknown"}</p>
          {statement.quote && <blockquote className="border-l-2 border-teal-500 pl-3 text-neutral-800">{statement.quote}</blockquote>}
          <p className="leading-relaxed text-neutral-600">{statement.summary}</p>
          {(statement.tools.length > 0 || statement.use_cases.length > 0) && (
            <p className="text-xs text-neutral-500">{[...statement.tools, ...statement.use_cases].join(" · ")}</p>
          )}
        </article>
      ))}
    </div>
  );
  return (
    <section className="border-y border-neutral-200 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-neutral-900"><Sparkles className="h-4 w-4 text-teal-600" />AI adoption & leadership stance</h2>
        {posture?.checked_at && <span className="text-xs text-neutral-500">Checked {formatDateTime(posture.checked_at)}</span>}
      </div>
      {!posture ? <p className="mt-3 text-sm text-neutral-500">Not researched yet</p> : <>
        <div className="my-3 flex flex-wrap gap-2 text-xs">
          <span className="rounded border border-teal-200 bg-teal-50 px-2 py-1 text-teal-900">Adoption: {posture.adoption_stage}</span>
          <span className="rounded border border-sky-200 bg-sky-50 px-2 py-1 text-sky-900">Leadership: {posture.leadership_stance}</span>
          {posture.statements.length > 0 && <span className="py-1 text-neutral-500">Confidence {Math.round(posture.confidence * 100)}%</span>}
        </div>
        <p className="text-sm leading-relaxed text-neutral-700">{posture.summary}</p>
        {evidence(posture)}
        {posture.searched_sources.length > 0 && <details className="mt-2 text-xs text-neutral-500">
          <summary className="cursor-pointer">Sources checked ({posture.searched_sources.length})</summary>
          <ul className="mt-2 space-y-1">{posture.searched_sources.map((url) => <li key={url}><a href={url} target="_blank" rel="noopener noreferrer" className="break-all text-sky-700 hover:underline">{url}</a></li>)}</ul>
        </details>}
      </>}
      {history.length > 0 && <details className="mt-3 text-sm">
        <summary className="cursor-pointer font-medium text-neutral-600">Previous observations ({history.length})</summary>
        {[...history].reverse().map((item, index) => <div key={`${item.checked_at}-${index}`} className="mt-3 border-t border-neutral-200 pt-3">
          <p className="text-xs text-neutral-500">{formatDateTime(item.checked_at)} · {item.adoption_stage} · {item.leadership_stance}</p>
          <p className="mt-1 text-neutral-700">{item.summary}</p>
          {evidence(item)}
        </div>)}
      </details>}
    </section>
  );
}

function SitemapMonitorPanel({ pifId, monitor }: { pifId: string; monitor: SitemapMonitorSummary | undefined }) {
  const history = useQuery({
    queryKey: ["firm-sitemap-history", pifId],
    queryFn: () => getFirmSitemapHistory(pifId),
  });
  const latestSnapshot = history.data?.items[0];
  const effectiveMonitor: SitemapMonitorSummary | undefined = monitor ?? (latestSnapshot ? {
    status: latestSnapshot.status,
    checked_at: latestSnapshot.fetched_at,
    website: latestSnapshot.website,
    sitemap_urls: latestSnapshot.sitemap_urls,
    url_count: latestSnapshot.url_count,
    changed: latestSnapshot.added_count || latestSnapshot.removed_count
      ? true
      : history.data && history.data.items.length > 1 ? false : null,
    added_count: latestSnapshot.added_count,
    removed_count: latestSnapshot.removed_count,
    added_urls: latestSnapshot.added_urls,
    removed_urls: latestSnapshot.removed_urls,
    truncated: latestSnapshot.truncated,
    snapshot_id: latestSnapshot.id,
    error: latestSnapshot.error,
  } : undefined);

  if (!effectiveMonitor && history.isPending) {
    return (
      <InfoBlock title="Sitemap changes">
        <div className="text-xs text-neutral-400">Loading sitemap history...</div>
      </InfoBlock>
    );
  }
  if (!effectiveMonitor) {
    return (
      <InfoBlock title="Sitemap changes">
        <div className="text-xs text-neutral-400">
          {history.isError
            ? "Sitemap history could not be loaded."
            : "No sitemap snapshot yet. It will be checked during full enrichment."}
        </div>
      </InfoBlock>
    );
  }

  const changeLabel = effectiveMonitor.changed == null
    ? "Baseline snapshot"
    : effectiveMonitor.changed
      ? `${effectiveMonitor.added_count ?? 0} added, ${effectiveMonitor.removed_count ?? 0} removed`
      : "No URL changes";

  return (
    <InfoBlock title="Sitemap changes">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-neutral-500">
        <span className="inline-flex items-center gap-1.5 font-medium text-neutral-700">
          <Globe className="h-3.5 w-3.5" />
          {(effectiveMonitor.url_count ?? 0).toLocaleString()} indexed URLs
        </span>
        <span>{formatLabel(effectiveMonitor.status)}</span>
        <span>{changeLabel}</span>
        {effectiveMonitor.checked_at && <span>Checked {formatDateTime(effectiveMonitor.checked_at)}</span>}
        {effectiveMonitor.truncated && <span className="font-medium text-amber-700">Snapshot capped</span>}
      </div>

      {effectiveMonitor.sitemap_urls?.length ? (
        <div className="mt-2 flex flex-wrap gap-2 border-t border-neutral-100 pt-2">
          {effectiveMonitor.sitemap_urls.map((url) => (
            <a
              key={url}
              href={url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-w-0 items-center gap-1 text-xs font-medium text-blue-600 hover:underline"
            >
              <span className="max-w-80 truncate">{url}</span>
              <ExternalLink className="h-3 w-3 shrink-0" />
            </a>
          ))}
        </div>
      ) : null}

      {effectiveMonitor.error && (
        <div className="mt-2 border-t border-neutral-100 pt-2 text-xs text-neutral-500">{effectiveMonitor.error}</div>
      )}

      {Boolean(effectiveMonitor.added_urls?.length || effectiveMonitor.removed_urls?.length) && (
        <div className="mt-3 grid gap-3 border-t border-neutral-100 pt-3 lg:grid-cols-2">
          <SitemapChangeList label="Added URLs" urls={effectiveMonitor.added_urls ?? []} tone="added" />
          <SitemapChangeList label="Removed URLs" urls={effectiveMonitor.removed_urls ?? []} tone="removed" />
        </div>
      )}

      {history.data?.items.length ? (
        <div className="mt-3 border-t border-neutral-100 pt-3">
          <div className="text-[10px] font-semibold uppercase text-neutral-400">Snapshot history</div>
          <div className="mt-1 divide-y divide-neutral-100">
            {history.data.items.map((snapshot) => (
              <div key={snapshot.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2 text-xs">
                <span className="text-neutral-500">{formatDateTime(snapshot.fetched_at)}</span>
                <span className="font-medium text-neutral-700">{snapshot.url_count.toLocaleString()} URLs</span>
                <span className="text-neutral-500">
                  {snapshot.added_count || snapshot.removed_count
                    ? `${snapshot.added_count} added, ${snapshot.removed_count} removed`
                    : snapshot.status === "completed" ? "Baseline" : formatLabel(snapshot.status)}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </InfoBlock>
  );
}

function SitemapChangeList({ label, urls, tone }: { label: string; urls: string[]; tone: "added" | "removed" }) {
  return (
    <div>
      <div className={cn(
        "text-[10px] font-semibold uppercase",
        tone === "added" ? "text-emerald-700" : "text-red-700",
      )}>
        {label} ({urls.length})
      </div>
      <div className="mt-1 max-h-40 space-y-1 overflow-y-auto">
        {urls.map((url) => (
          <a key={url} href={url} target="_blank" rel="noreferrer" className="block truncate text-xs text-neutral-600 hover:text-blue-600 hover:underline" title={url}>
            {url}
          </a>
        ))}
      </div>
    </div>
  );
}

function JobPostingsPanel({
  research,
  status,
  lastResearchedAt,
}: {
  research: JobPostingsResearch | undefined;
  status: string | null | undefined;
  lastResearchedAt: string | null | undefined;
}) {
  const postings = research?.postings ?? [];
  const windowLabel = research?.window_start && research?.window_end
    ? `${formatDateOnly(research.window_start)} to ${formatDateOnly(research.window_end)}`
    : "Last 30 days";

  return (
    <InfoBlock title="Job Postings">
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neutral-500">
        <span className="inline-flex items-center gap-1.5 font-medium text-neutral-700">
          <Briefcase className="h-3.5 w-3.5" />
          {postings.length} recent {postings.length === 1 ? "opening" : "openings"}
        </span>
        <span>{windowLabel}</span>
        <span>{formatLabel(status || "not researched")}</span>
        {lastResearchedAt && <span>Checked {formatDateTime(lastResearchedAt)}</span>}
      </div>

      {postings.length === 0 ? (
        <div className="border-t border-neutral-100 pt-3 text-xs text-neutral-400">
          {status === "completed" ? "No dated job postings found in this window." : "Job-posting research has not completed."}
        </div>
      ) : (
        <div className="divide-y divide-neutral-100 border-t border-neutral-100">
          {postings.map((posting, index) => (
            <article key={`${posting.source_url}-${posting.title}-${index}`} className="py-3">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-neutral-900">{posting.title}</div>
                  <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-neutral-500">
                    <span>Posted {formatDateOnly(posting.posted_date)}</span>
                    {posting.location && <span>{posting.location}</span>}
                    {posting.employment_type && <span>{posting.employment_type}</span>}
                  </div>
                  {(posting.role_category || posting.gtm_relevance) && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {posting.role_category && <JobTag value={formatLabel(posting.role_category)} />}
                      {posting.gtm_relevance && <JobTag value={`${formatLabel(posting.gtm_relevance)} GTM`} emphasis={posting.gtm_relevance === "high"} />}
                    </div>
                  )}
                </div>
                <a
                  href={posting.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-blue-600 hover:underline"
                >
                  {posting.source_name || "Source"}
                  <ExternalLink className="h-3 w-3" />
                </a>
              </div>
              {posting.description_summary && (
                <p className="mt-2 text-xs leading-5 text-neutral-700">{posting.description_summary}</p>
              )}
              {Boolean(posting.trigger_tags?.length || posting.technology_mentions?.length) && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {posting.trigger_tags?.map((tag) => <JobTag key={tag} value={formatLabel(tag)} />)}
                  {posting.technology_mentions?.map((technology) => <JobTag key={technology} value={technology} emphasis />)}
                </div>
              )}
              {(posting.responsibilities.length > 0 || posting.qualifications.length > 0) && (
                <div className="mt-2 grid gap-3 md:grid-cols-2">
                  {posting.responsibilities.length > 0 && (
                    <JobPostingDetails label="Responsibilities" items={posting.responsibilities} />
                  )}
                  {posting.qualifications.length > 0 && (
                    <JobPostingDetails label="Qualifications" items={posting.qualifications} />
                  )}
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </InfoBlock>
  );
}

function JobTag({ value, emphasis = false }: { value: string; emphasis?: boolean }) {
  return (
    <span className={cn(
      "inline-flex rounded border px-1.5 py-0.5 text-[10px] font-medium",
      emphasis ? "border-blue-200 bg-blue-50 text-blue-700" : "border-neutral-200 bg-neutral-50 text-neutral-600",
    )}>
      {value}
    </span>
  );
}

function JobPostingDetails({ label, items }: { label: string; items: string[] }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase text-neutral-400">{label}</div>
      <ul className="mt-1 space-y-1 text-xs text-neutral-600">
        {items.map((item, index) => <li key={`${item}-${index}`}>• {item}</li>)}
      </ul>
    </div>
  );
}

function FirmReviewsPanel({
  pifId,
  firmName,
  address,
}: {
  pifId: string;
  firmName: string;
  address: string | PifAddress | null;
}) {
  const queryClient = useQueryClient();
  const [researchTaskId, setResearchTaskId] = useState<string | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["firm-reviews", pifId],
    queryFn: () => getFirmReviews(pifId),
  });
  const reviewResearch = useMutation({
    mutationFn: () => startFirmReviewResearch(pifId),
    onSuccess: (result) => setResearchTaskId(result.task_id),
  });
  const reviewResearchStatus = useQuery({
    queryKey: ["firm-review-research-status", researchTaskId],
    queryFn: () => getFirmReviewResearchStatus(researchTaskId ?? ""),
    enabled: Boolean(researchTaskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL_TASK_STATUSES.has(status) ? false : 3_000;
    },
  });
  const reviewStatus = reviewResearchStatus.data?.status ?? data?.research_status ?? null;

  useEffect(() => {
    if (!reviewStatus || !TERMINAL_TASK_STATUSES.has(reviewStatus)) return;
    void queryClient.invalidateQueries({ queryKey: ["firm-reviews", pifId] });
  }, [pifId, queryClient, reviewStatus]);

  const state = extractState(address);
  const firmType = "personal injury law firm";
  const googleQuery = [firmName, firmType, state, "reviews"].filter(Boolean).join(" ");
  const yelpQuery = ["site:yelp.com", firmName, firmType, state].filter(Boolean).join(" ");

  return (
    <section className="rounded-md border border-neutral-200 p-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-neutral-900">
          <Star className="h-4 w-4 text-neutral-400" />
          Reviews
        </h2>
        <span className="text-[11px] text-neutral-400">
          {isLoading
            ? "loading..."
            : data?.updated_at
              ? `saved ${new Date(data.updated_at).toLocaleString(undefined, {
                  month: "short",
                  day: "numeric",
                  hour: "numeric",
                  minute: "2-digit",
                })}`
              : "not saved"}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-y border-neutral-100 py-2">
        <div className="text-xs text-neutral-500">
          {reviewStatus && !TERMINAL_TASK_STATUSES.has(reviewStatus)
            ? "Researching public review sources..."
            : data?.reviews?.review_count
              ? `${data.reviews.review_count.toLocaleString()} source-backed reviews from ${data.reviews.source_count?.toLocaleString() ?? 0} sources`
              : "No source-backed review research yet."}
          {reviewStatus === "failed" && data?.research_error ? ` ${data.research_error}` : ""}
        </div>
        <button
          type="button"
          onClick={() => reviewResearch.mutate()}
          disabled={reviewResearch.isPending || Boolean(reviewStatus && !TERMINAL_TASK_STATUSES.has(reviewStatus))}
          className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-2.5 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-40"
        >
          {reviewResearch.isPending || (reviewStatus && !TERMINAL_TASK_STATUSES.has(reviewStatus))
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <RefreshCw className="h-3.5 w-3.5" />}
          Research public reviews
        </button>
      </div>
      {reviewResearch.error && (
        <div className="mt-2 text-xs text-rose-600">
          {reviewResearch.error instanceof Error ? reviewResearch.error.message : "Could not queue public review research"}
        </div>
      )}

      <SourceBackedReviews research={data?.reviews} />

      <ExtractedQuotesSection google={data?.google ?? ""} yelp={data?.yelp ?? ""} />

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <ReviewSourcePane
          pifId={pifId}
          source="google"
          label="Google Reviews"
          searchQuery={googleQuery}
          serverValue={data?.google ?? ""}
          isLoading={isLoading}
          placeholder={"Google - 4.8 stars (312 reviews)\n\nJane D. - Aug 2024\n\"They were great on my auto-accident case...\""}
        />
        <ReviewSourcePane
          pifId={pifId}
          source="yelp"
          label="Yelp Reviews"
          searchQuery={yelpQuery}
          serverValue={data?.yelp ?? ""}
          isLoading={isLoading}
          placeholder={"Yelp - 4.5 stars (87 reviews)\n\nMark T. - 2/2025\n\"Responsive and honest. Explained every step...\""}
        />
      </div>
    </section>
  );
}

function SourceBackedReviews({ research }: { research: FirmReviews["reviews"] | undefined }) {
  const sources = research?.sources ?? [];
  if (sources.length === 0) return null;
  return (
    <div className="mt-3 space-y-3">
      {research?.coverage_note && <div className="text-xs text-neutral-500">{research.coverage_note}</div>}
      {sources.map((source, sourceIndex) => (
        <div key={`${source.source}-${source.listing_url}-${sourceIndex}`} className="rounded-md border border-neutral-200 bg-neutral-50 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs font-semibold text-neutral-800">{formatLabel(source.source)} · {source.reviews.length} reviews</div>
            <a href={source.listing_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:underline">
              Listing
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>
          {source.coverage_note && <div className="mt-1 text-[11px] text-neutral-500">{source.coverage_note}</div>}
          <div className="mt-2 space-y-2">
            {source.reviews.map((review, index) => (
              <article key={`${review.reviewer_name ?? "reviewer"}-${review.review_date ?? "date"}-${index}`} className="rounded border border-neutral-200 bg-white px-3 py-2 text-xs text-neutral-700">
                <div className="flex flex-wrap items-center gap-x-2 text-[11px] text-neutral-500">
                  {review.reviewer_name && <span className="font-medium text-neutral-700">{review.reviewer_name}</span>}
                  {typeof review.rating === "number" && <span>{review.rating}/5</span>}
                  {review.review_date && <span>{formatDateOnly(review.review_date)}</span>}
                  {review.review_url && <a href={review.review_url} target="_blank" rel="noreferrer" className="ml-auto text-blue-600 hover:underline">Review</a>}
                </div>
                <p className="mt-1 whitespace-pre-wrap leading-5">{review.text}</p>
              </article>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function ExtractedQuotesSection({ google, yelp }: { google: string; yelp: string }) {
  const sources: { key: "google" | "yelp"; label: string; data: ExtractedReviews | null }[] = [
    { key: "google", label: "Google", data: parseExtractedReviews(google) },
    { key: "yelp", label: "Yelp", data: parseExtractedReviews(yelp) },
  ];
  if (!sources.some((source) => source.data !== null)) return null;

  return (
    <div className="mt-3 space-y-3">
      {sources.map(({ key, label, data }) =>
        data ? <ExtractedQuotesForSource key={key} label={label} data={data} /> : null,
      )}
    </div>
  );
}

function ExtractedQuotesForSource({ label, data }: { label: string; data: ExtractedReviews }) {
  const present = Object.entries(data.pain_points ?? {}).filter(([, quotes]) => Array.isArray(quotes) && quotes.length > 0);
  const absent = Object.entries(data.absent_pain_points ?? {});

  if (present.length === 0 && absent.length === 0) return null;

  return (
    <div className="rounded-md border border-neutral-200 bg-neutral-50 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] uppercase tracking-wide text-neutral-500">
        <span className="font-semibold">{label} pain-point quotes</span>
        {data.extracted_at && (
          <span className="text-neutral-400">
            {data.extractor_version ?? "extracted"} · {new Date(data.extracted_at).toLocaleString()}
          </span>
        )}
      </div>
      {present.map(([key, quotes]) => (
        <div key={key} className="mt-3">
          <div className="text-xs font-semibold text-neutral-700">
            {painLabel(key)} <span className="font-normal text-neutral-400">· {quotes.length}</span>
          </div>
          <ul className="mt-1 space-y-2">
            {quotes.map((quote, index) => (
              <li key={index} className="rounded border border-neutral-200 bg-white p-2 text-[13px] text-neutral-800">
                <p className="italic text-neutral-700">&ldquo;{quote.quote}&rdquo;</p>
                <div className="mt-1 flex flex-wrap items-center gap-x-2 text-[11px] text-neutral-500">
                  {quote.reviewer_name && <span>{quote.reviewer_name}</span>}
                  {quote.review_date && <span>· {quote.review_date}</span>}
                  {typeof quote.star_rating === "number" && (
                    <span>· {quote.star_rating}/5</span>
                  )}
                  <span className="ml-auto text-neutral-400">confidence {quote.confidence.toFixed(2)}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {absent.map(([key, rationale]) => (
        <div key={key} className="mt-3 rounded border border-dashed border-neutral-300 bg-white p-2 text-[12px] text-neutral-500">
          <span className="font-semibold text-neutral-600">{painLabel(key)} not evident</span> - {rationale}
        </div>
      ))}
    </div>
  );
}

function ReviewSourcePane({
  pifId,
  source,
  label,
  searchQuery,
  serverValue,
  isLoading,
  placeholder,
}: {
  pifId: string;
  source: "google" | "yelp";
  label: string;
  searchQuery: string;
  serverValue: string;
  isLoading: boolean;
  placeholder: string;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [synced, setSynced] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (isLoading) return;
    if (synced === null) {
      setDraft(serverValue);
      setSynced(serverValue);
      return;
    }
    if (serverValue !== synced && draft === synced) {
      setDraft(serverValue);
      setSynced(serverValue);
    }
  }, [serverValue, isLoading, synced, draft]);

  const dirty = synced !== null && draft !== synced;

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const response = await putFirmReviews(pifId, source === "google" ? { google: draft } : { yelp: draft });
      const next = source === "google" ? response.google : response.yelp;
      setDraft(next);
      setSynced(next);
      queryClient.setQueryData(["firm-reviews", pifId], response);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-md border border-neutral-200 bg-neutral-50 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-neutral-600">{label}</div>
          <div className="mt-0.5 truncate font-mono text-[10px] text-neutral-400" title={searchQuery}>
            q: {searchQuery}
          </div>
        </div>
        <button
          type="button"
          onClick={() => window.open(`https://www.google.com/search?q=${encodeURIComponent(searchQuery)}`, "_blank", "noopener,noreferrer")}
          className="inline-flex shrink-0 items-center gap-1 rounded border border-neutral-300 bg-white px-2 py-1 text-[10px] font-medium text-neutral-700 hover:bg-neutral-100"
        >
          <Search className="h-3 w-3" />
          Search
        </button>
      </div>
      <textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={placeholder}
        rows={8}
        disabled={isLoading}
        className="mt-2 w-full resize-y rounded-md border border-neutral-300 bg-white px-3 py-2 font-mono text-xs text-neutral-800 focus:border-neutral-400 focus:outline-none"
      />
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[10px] text-neutral-400">
          {draft.length.toLocaleString()} chars
          {dirty && <span className="ml-2 text-amber-600">unsaved</span>}
        </span>
        <div className="flex items-center gap-2">
          {saveError && <span className="text-[10px] text-rose-600">{saveError}</span>}
          <button
            type="button"
            onClick={save}
            disabled={saving || !dirty}
            className={cn(
              "rounded-md px-2.5 py-1 text-[11px] font-medium transition",
              dirty && !saving ? "bg-neutral-900 text-white hover:bg-neutral-700" : "bg-neutral-100 text-neutral-400",
            )}
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

function FirmCommunicationsPanel({ pifId }: { pifId: string }) {
  const comms = useQuery({
    queryKey: ["firm-comms", pifId],
    queryFn: () => listFirmCommunications(pifId, { limit: 100 }),
    refetchInterval: 30_000,
  });
  const items = comms.data?.items ?? [];

  return (
    <section className="rounded-md border border-neutral-200 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-neutral-900">
          <PhoneCall className="h-4 w-4 text-neutral-400" />
          Communications ({comms.data?.total ?? 0})
        </h2>
        <span className="text-[11px] text-neutral-400">calls · voicemail · sms · email</span>
      </div>
      {comms.isLoading && <div className="mt-3 text-xs text-neutral-400">loading...</div>}
      {!comms.isLoading && items.length === 0 && (
        <div className="mt-3 text-xs text-neutral-400">No outbound communications to this firm yet.</div>
      )}
      {items.length > 0 && (
        <div className="mt-3">
          <CommsTable items={items} hideFirm />
        </div>
      )}
    </section>
  );
}

function FirmCallsPanel({ pifId }: { pifId: string }) {
  const calls = useQuery({
    queryKey: ["firm-calls", pifId],
    queryFn: () => getFirmCalls(pifId, 100),
    refetchInterval: 30_000,
  });

  return (
    <section className="rounded-md border border-neutral-200 p-3">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-neutral-900">
        <PhoneCall className="h-4 w-4 text-neutral-400" />
        Calls ({calls.data?.total ?? 0})
      </h2>
      {calls.isLoading && <div className="mt-3 text-xs text-neutral-400">loading...</div>}
      {!calls.isLoading && (calls.data?.items?.length ?? 0) === 0 && (
        <div className="mt-3 text-xs text-neutral-400">No calls yet to this firm.</div>
      )}
      {(calls.data?.items?.length ?? 0) > 0 && (
        <div className="mobile-table-card mt-3 md:overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wide text-neutral-400">
              <tr className="text-left">
                <th className="px-2 py-1.5 font-medium">When</th>
                <th className="px-2 py-1.5 font-medium">Contact</th>
                <th className="px-2 py-1.5 font-medium">Phone</th>
                <th className="px-2 py-1.5 font-medium">Outcome</th>
                <th className="px-2 py-1.5 font-medium">Disposition</th>
                <th className="px-2 py-1.5 text-right font-medium">Dur</th>
                <th className="px-2 py-1.5 font-medium">Judge</th>
                <th className="px-2 py-1.5 font-medium">VM</th>
                <th className="px-2 py-1.5 font-medium">IVR</th>
                <th className="px-2 py-1.5 font-medium">Voice</th>
                <th className="px-2 py-1.5 font-medium">Prompt</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {calls.data?.items?.map((call) => (
                <tr key={call.call_id} className="text-neutral-700 hover:bg-neutral-50">
                  <td data-label="When" className="whitespace-nowrap px-2 py-1.5">
                    <Link href={`/calls/${call.call_id}`} className="text-blue-600 hover:underline" title={call.started_at ?? ""}>
                      {call.started_at
                        ? new Date(call.started_at).toLocaleString(undefined, {
                            month: "short",
                            day: "numeric",
                            hour: "numeric",
                            minute: "2-digit",
                          })
                        : "—"}
                    </Link>
                  </td>
                  <td data-label="Contact" className="max-w-[14rem] truncate px-2 py-1.5">{call.patient_name || "—"}</td>
                  <td data-label="Phone" className="px-2 py-1.5 font-mono text-[11px] text-neutral-500">{call.phone || "—"}</td>
                  <td data-label="Outcome" className="px-2 py-1.5">
                    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", outcomeColor(call.outcome))}>
                      {call.outcome}
                    </span>
                  </td>
                  <td data-label="Disposition" className="px-2 py-1.5 text-[11px] text-neutral-600">
                    {call.call_disposition}
                    {call.ended_by && <span className="ml-1 text-[10px] text-neutral-400">({call.ended_by})</span>}
                  </td>
                  <td data-label="Duration" className="px-2 py-1.5 text-right tabular-nums">{call.duration_seconds}s</td>
                  <td data-label="Judge" className="px-2 py-1.5">{call.judge_score != null ? call.judge_score : "—"}</td>
                  <td data-label="VM" className="px-2 py-1.5">{call.voicemail_left ? "yes" : ""}</td>
                  <td data-label="IVR" className="px-2 py-1.5 text-[10px] text-neutral-500">{call.ivr_detected ? call.ivr_outcome ?? "yes" : ""}</td>
                  <td data-label="Voice" className="px-2 py-1.5 text-[10px] text-neutral-500">{call.voice_provider ?? "—"}</td>
                  <td data-label="Prompt" className="px-2 py-1.5 text-[10px] text-neutral-500">{call.prompt_version ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function FirmDangerZone({ pifId, firmName }: { pifId: string; firmName: string }) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onDelete() {
    setSubmitting(true);
    setError(null);
    try {
      const result: DeleteFirmResult = await deleteFirm(pifId);
      const total =
        result.patients +
        result.cadence_entries +
        result.firm_reviews +
        result.firm_contacts +
        result.patient_call_state;
      console.log(`[delete-firm] ${pifId} removed ${total} local rows`, result);
      router.replace("/emailtag-firms");
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "delete failed");
      setSubmitting(false);
    }
  }

  return (
    <section className="rounded-md border border-rose-200 bg-rose-50 p-3">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-rose-800">
        <AlertTriangle className="h-4 w-4" />
        Local cleanup
      </h2>
      <p className="mt-2 text-xs text-rose-900/80">
        Hard-deletes this firm&apos;s local Possible OS data: lead row, cadence entry,
        operator-pasted reviews, contacts, email sequences, and call-state. Historical
        outbound logs are preserved, and the firm remains in EmailTag/PIFStats.
      </p>
      {!confirming ? (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="mt-3 inline-flex items-center gap-2 rounded-md border border-rose-300 bg-white px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-100"
        >
          <Trash2 className="h-3.5 w-3.5" />
          Delete local firm data
        </button>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-rose-900">Delete local data for &ldquo;{firmName}&rdquo;?</span>
          <button
            type="button"
            onClick={onDelete}
            disabled={submitting}
            className="rounded-md bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-700 disabled:opacity-50"
          >
            {submitting ? "Deleting..." : "Yes, delete"}
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            disabled={submitting}
            className="rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      )}
      {error && <div className="mt-2 text-xs text-rose-700">Error: {error}</div>}
    </section>
  );
}

function ActionButton({
  children,
  onClick,
  pending,
  icon,
}: {
  children: React.ReactNode;
  onClick: () => void;
  pending?: boolean;
  icon: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={pending}
      className="inline-flex max-w-full min-w-0 items-center justify-center gap-1.5 whitespace-normal rounded-md border border-neutral-200 bg-white px-2.5 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-40"
    >
      {pending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : icon}
      {children}
    </button>
  );
}

function TaskStatus({
  label,
  status,
  message,
  compact,
  progress,
  currentStage,
}: {
  label: string;
  status?: string;
  message?: string;
  compact?: boolean;
  progress?: number;
  currentStage?: string;
}) {
  if (!status && !message) return null;
  const running = Boolean(status && !TERMINAL_TASK_STATUSES.has(status));
  const failed = status === "failed" || status === "error";
  const boundedProgress = Math.max(0, Math.min(100, progress ?? (status === "completed" ? 100 : 0)));
  return (
    <div className={cn(
      "rounded-md border text-xs",
      failed ? "border-rose-200 bg-rose-50 text-rose-700" : "border-neutral-200 bg-neutral-50 text-neutral-600",
      compact ? "mt-1 px-2 py-1.5" : "px-3 py-2.5",
    )}>
      <div className="flex items-start gap-2">
        {running ? (
          <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin" />
        ) : failed ? (
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        ) : (
          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
        )}
        <span className="min-w-0">
          <span className="font-medium">{label}:</span> {status ? formatLabel(status) : ""}
          {currentStage ? ` · ${formatLabel(currentStage)}` : ""}
          {message ? <span className={cn(compact && "block truncate")}> · {message}</span> : null}
        </span>
        {typeof progress === "number" && <span className="ml-auto shrink-0 font-mono">{boundedProgress}%</span>}
      </div>
      {typeof progress === "number" && (
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-neutral-200" aria-label={`${label} ${boundedProgress}%`}>
          <div
            className={cn("h-full transition-all", failed ? "bg-rose-500" : "bg-emerald-600")}
            style={{ width: `${boundedProgress}%` }}
          />
        </div>
      )}
    </div>
  );
}

type MetricTone = "teal" | "blue" | "green" | "amber" | "rose";

const METRIC_TONE_STYLES: Record<MetricTone, { border: string; icon: string; bar: string }> = {
  teal: { border: "border-[#b9dcda]", icon: "bg-[#e5f4f2] text-[#176b70]", bar: "bg-[#289296]" },
  blue: { border: "border-[#c7d9ef]", icon: "bg-[#eaf1fb] text-[#2f6fca]", bar: "bg-[#4c82d1]" },
  green: { border: "border-[#bfe2d1]", icon: "bg-[#e7f6ee] text-[#21734f]", bar: "bg-[#32a66f]" },
  amber: { border: "border-[#ead7ad]", icon: "bg-[#fbf2dc] text-[#9a680b]", bar: "bg-[#dfa72f]" },
  rose: { border: "border-[#edc8cc]", icon: "bg-[#fbedef] text-[#ae4b55]", bar: "bg-[#cf6570]" },
};

function MetricTile({
  icon,
  label,
  value,
  tone = "teal",
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  tone?: MetricTone;
}) {
  const styles = METRIC_TONE_STYLES[tone];
  return (
    <div className={cn("relative overflow-hidden rounded-md border bg-white px-4 py-3 shadow-sm", styles.border)}>
      <div className={cn("absolute inset-y-0 left-0 w-1", styles.bar)} aria-hidden="true" />
      <div className="flex items-center gap-3">
        <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-md", styles.icon)}>
          {icon}
        </div>
        <div className="min-w-0">
          <div className="truncate text-[10px] font-semibold uppercase text-[#60737a]">{label}</div>
          <div className="mt-0.5 truncate text-xl font-semibold text-[#172d34]">{value}</div>
        </div>
      </div>
    </div>
  );
}

function FirmHeaderMetric({
  icon,
  label,
  value,
  detail,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="min-w-0 bg-white px-4 py-3">
      <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase text-neutral-400">
        {icon}
        <span className="truncate">{label}</span>
      </div>
      <div className="mt-1 truncate text-sm font-semibold text-neutral-900" title={value}>{value}</div>
      <div className="mt-0.5 truncate text-[11px] text-neutral-500" title={detail}>{detail}</div>
    </div>
  );
}

function SignalPill({
  icon,
  value,
  label,
}: {
  icon: React.ReactNode;
  value: string | number;
  label: string;
}) {
  return (
    <span className="inline-flex max-w-full min-w-0 items-center gap-1 rounded-md border border-neutral-200 bg-neutral-50 px-2 py-1 text-[11px] text-neutral-600">
      {icon}
      <span className="font-medium text-neutral-800">{value}</span>
      <span className="truncate">{label}</span>
    </span>
  );
}

function buildEnrichmentSteps(
  firm: PifInfoResponse,
  liveStages?: Array<{ key: string; label: string; status: string; message?: string | null }>,
): WorkflowStepInfo[] {
  if (liveStages?.length) {
    return liveStages.map((stage) => ({
      label: stage.label,
      detail: stage.message || formatLabel(stage.status),
      state: statusToStepState(stage.status),
    }));
  }
  const leadershipHistory = firm.research_data?.leadership_email_history;
  const behaviorRecord = getRecord(firm.behavioral_data);
  const contactProfiles = getRecord(behaviorRecord?.contact_profiles);

  return [
    {
      label: "Website",
      detail: firm.canonical_website
        ? firm.canonical_website
        : firm.website_status === "pending"
          ? "Needs review"
          : "Resolve canonical website",
      state: firm.website_status === "resolved" && Boolean(firm.canonical_website) ? "completed" : "waiting",
    },
    {
      label: "Firm research",
      detail: firm.research_status || "Not researched",
      state: statusToStepState(firm.research_status),
    },
    {
      label: "Leadership email history",
      detail: Array.isArray(leadershipHistory)
        ? `${leadershipHistory.length} leaders analyzed`
        : firm.leadership?.length
          ? "Waiting for email history"
          : "Needs leadership first",
      state: Array.isArray(leadershipHistory)
        ? "completed"
        : firm.research_status === "completed" && !firm.leadership?.length
          ? "skipped"
          : "waiting",
    },
    {
      label: "Staff research",
      detail: firm.staff_research_status || "Not researched",
      state: statusToStepState(firm.staff_research_status),
    },
    {
      label: "Behavior",
      detail: firm.behavioral_data
        ? `${firm.behavioral_data.total_email_count ?? 0} emails analyzed`
        : "Analyze email behavior",
      state: firm.behavioral_data ? "completed" : "waiting",
    },
    {
      label: "Signatures",
      detail: contactProfiles ? `${Object.keys(contactProfiles).length} contact profiles` : "Extract signature profiles",
      state: contactProfiles ? "completed" : firm.behavioral_data ? "waiting" : "waiting",
    },
    {
      label: "ICP score",
      detail: firm.icp_score == null ? "Not scored" : `${firm.icp_tier ?? "-"} / ${firm.icp_score}`,
      state: firm.icp_score == null ? "waiting" : "completed",
    },
  ];
}

function statusToStepState(status: string | null): WorkflowStepState {
  if (status === "completed" || status === "skipped") return "completed";
  if (status === "failed" || status === "error") return "failed";
  if (status === "queued" || status === "in_progress" || status === "running" || status === "started") return "running";
  return "waiting";
}

function WorkflowStep({ label, detail, state }: WorkflowStepInfo) {
  const Icon =
    state === "completed" ? CheckCircle2 : state === "failed" ? AlertCircle : state === "running" ? Loader2 : ChevronRight;
  const iconClass =
    state === "completed"
      ? "text-emerald-600"
      : state === "failed"
        ? "text-rose-600"
        : state === "running"
          ? "animate-spin text-amber-600"
          : "text-neutral-400";

  return (
    <div className="rounded-md border border-neutral-200 bg-neutral-50 px-3 py-3">
      <div className="flex items-center gap-2">
        <Icon className={cn("h-4 w-4", iconClass)} />
        <span className="text-sm font-medium text-neutral-900">{label}</span>
      </div>
      <div className="mt-1 truncate text-xs text-neutral-500" title={detail}>
        {detail}
      </div>
    </div>
  );
}

function InfoBlock({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-md border border-neutral-200 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-neutral-900">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function CollapsibleInfoBlock({
  title,
  children,
  count,
  defaultOpen = true,
}: {
  title: string;
  children: React.ReactNode;
  count?: number;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section className="rounded-md border border-neutral-200">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className={cn(
          "flex w-full items-center justify-between gap-2 px-3 py-3 text-left hover:bg-neutral-50",
          open && "border-b border-neutral-100",
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-semibold text-neutral-900">{title}</span>
          {typeof count === "number" && (
            <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] font-medium text-neutral-500">
              {count}
            </span>
          )}
        </span>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-neutral-400 transition", open && "rotate-180")} />
      </button>
      {open && <div className="p-3">{children}</div>}
    </section>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 border-t border-neutral-100 py-2 first:border-t-0 sm:grid-cols-[9rem_1fr]">
      <div className="text-xs font-medium text-neutral-400">{label}</div>
      <div className="break-words text-xs text-neutral-700">{value}</div>
    </div>
  );
}

type FirmPersonProfile = {
  name: string;
  title: string;
  email: string | null;
  phone: string | null;
  linkedin: string | null;
  bio: string | null;
  education?: string[];
  experience?: string[];
  skills?: string[];
  certifications?: string[];
  publications?: string[];
  cases_handled?: string[];
  bar_admissions?: string[];
  source_url?: string | null;
};

function PersonProfileDetails({ person }: { person: FirmPersonProfile }) {
  const sections = [
    ["Education", person.education],
    ["Experience", person.experience],
    ["Bar admissions", person.bar_admissions],
    ["Skills", person.skills],
    ["Certifications", person.certifications],
    ["Publications", person.publications],
    ["Cases handled", person.cases_handled],
  ] as const;
  const populated = sections.map(([label, values]) => ({
    label,
    values: Array.isArray(values) ? values.filter((value) => typeof value === "string" && value.trim()) : [],
  })).filter((section) => section.values.length);
  let sourceUrl: string | null = null;
  try {
    const url = new URL(person.source_url ?? "");
    if (url.protocol === "https:" || url.protocol === "http:") sourceUrl = url.href;
  } catch { /* Missing or malformed source URLs are not links. */ }
  if (!populated.length && !sourceUrl) return null;

  return (
    <details className="group mt-3 border-t border-neutral-200 pt-2 text-xs">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded text-sky-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-600 [&::-webkit-details-marker]:hidden">
        <ChevronRight className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-90" />
        Professional details
      </summary>
      <div className="mt-3 space-y-3 break-words text-neutral-700">
        {populated.map(({ label, values }) => (
          <section key={label}>
            <h4 className="mb-1 font-semibold text-neutral-900">{label}</h4>
            <ul className="list-disc space-y-1 pl-4">
              {values.map((value, index) => <li key={index}>{value}</li>)}
            </ul>
          </section>
        ))}
        {sourceUrl && (
          <a href={sourceUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sky-700 hover:underline">
            Profile source <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
    </details>
  );
}

function PeopleList({
  title,
  items,
  empty,
  firmName,
}: {
  title: string;
  items: FirmPersonProfile[];
  empty: string;
  firmName: string;
}) {
  return (
    <InfoBlock title={title}>
      {items.length === 0 && <div className="text-xs text-neutral-400">{empty}</div>}
      <div className="space-y-2">
        {items.map((person, index) => (
          <div key={`${person.name}-${index}`} className="min-w-0 rounded-md bg-neutral-50 p-2">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="break-words text-sm font-medium text-neutral-900">{person.name}</div>
                <div className="break-words text-xs text-neutral-500">{display(person.title)}</div>
              </div>
              <PersonLinkedInAction name={person.name} firmName={firmName} linkedin={person.linkedin} />
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 break-all text-[11px] text-neutral-500">
              {person.email && <span>{person.email}</span>}
              {person.phone && <span>{person.phone}</span>}
            </div>
            {person.bio && <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-relaxed text-neutral-600">{person.bio}</p>}
            <PersonProfileDetails person={person} />
          </div>
        ))}
      </div>
    </InfoBlock>
  );
}

function ExtractedContacts({ contacts, firmName }: { contacts: PifInfoResponse["contacts"]; firmName: string }) {
  return (
    <InfoBlock title="Extracted Contacts">
      {contacts.length === 0 && <div className="text-xs text-neutral-400">No extracted contacts.</div>}
      <div className="space-y-2">
        {contacts.map((contact, index) => (
          <div key={`${contact.name}-${index}`} className="rounded-md bg-neutral-50 p-2 text-xs">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate font-medium text-neutral-900">{display(contact.name)}</div>
                <div className="text-neutral-500">{display(contact.title)}</div>
              </div>
              <PersonLinkedInAction name={contact.name} firmName={firmName} linkedin={contact.linkedin} />
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-neutral-500">
              {contact.email && <span>{contact.email}</span>}
              {contact.phone && <span>{contact.phone}</span>}
              {contact.extension && <span>ext. {contact.extension}</span>}
            </div>
          </div>
        ))}
      </div>
    </InfoBlock>
  );
}

function JsonViewer({ title, value }: { title: string; value: unknown }) {
  return (
    <details className="rounded-md border border-neutral-200 bg-neutral-950 text-neutral-100">
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium">{title}</summary>
      <pre className="max-h-80 overflow-auto border-t border-neutral-800 p-3 text-xs">
        {value == null ? "null" : JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}
