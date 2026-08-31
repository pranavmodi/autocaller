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
  Mail,
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
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import {
  deleteFirm,
  getFirmCalls,
  getFirmReviews,
  getFirmReviewResearchStatus,
  listFirmCommunications,
  putFirmReviews,
  startFirmReviewResearch,
  type DeleteFirmResult,
  type FirmReviews,
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
  getMirroredFirm,
  getPifPeopleFilterOptions,
  getPifSyncStatus,
  getResearchStatus,
  getProxiedResearchStatus,
  listMirroredPifInfo,
  listMirroredPifJobPostings,
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
  type ExportFormat,
  type PifInfoListParams,
  type PifInfoListResponse,
  type PifInfoResponse,
  type PifJobPostingResult,
  type PifJobPostingsListParams,
  type JobPostingsResearch,
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
} from "@/lib/emailtag";

const PAGE_SIZE = 25;
const BATCH_PAGE_SIZE = 100;
const PRESENCE = ["any", "has", "missing"] as const;
const STATUS_PRESENCE = ["any", "completed", "missing", "queued_or_running", "failed"] as const;
const WEBSITE_PRESENCE = ["any", "has", "missing", "resolved", "unresolved"] as const;
const TERMINAL_TASK_STATUSES = new Set(["completed", "failed", "error", "success"]);

type SortBy = NonNullable<PifInfoListParams["sort_by"]>;
type WebsitePresence = NonNullable<PifInfoListParams["website_presence"]>;
type StatusPresence = NonNullable<PifInfoListParams["research_presence"]>;
type SimplePresence = NonNullable<PifInfoListParams["behavior_presence"]>;
type PeopleSource = NonNullable<PifPeopleListParams["source"]>;
type LeaderFilter = NonNullable<PifPeopleListParams["leader"]>;
type LeadsView = "firms" | "contacts" | "job_listings";
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
  icp_tier: "" | PifTier;
  entity_type: string;
  recently_researched: string;
  contact_email_range: string;
  staff_count_range: string;
  autorespond_window: string;
  autorespond_type: string;
  website_presence: WebsitePresence;
  research_presence: StatusPresence;
  staff_presence: StatusPresence;
  job_postings_presence: "any" | "has" | "none" | "not_researched" | "queued_or_running" | "failed";
  job_posting_role: "" | "intake" | "marketing" | "case_operations" | "firm_operations" | "technology";
  job_posting_tag: string;
  job_posting_query: string;
  job_posted_within_days: string;
  behavior_presence: SimplePresence;
  icp_presence: SimplePresence;
  vendor_presence: SimplePresence;
  vendor: string;
  record_origin: RecordOrigin;
  first_contact_period: FirstContactPeriod;
  first_contacted_from: string;
  first_contacted_to: string;
  active_only: boolean;
}

const DEFAULT_FILTERS: FiltersState = {
  search: "",
  sort_by: "updated_at",
  icp_tier: "",
  entity_type: "",
  recently_researched: "",
  contact_email_range: "",
  staff_count_range: "",
  autorespond_window: "any",
  autorespond_type: "",
  website_presence: "any",
  research_presence: "any",
  staff_presence: "any",
  job_postings_presence: "any",
  job_posting_role: "",
  job_posting_tag: "",
  job_posting_query: "",
  job_posted_within_days: "",
  behavior_presence: "any",
  icp_presence: "any",
  vendor_presence: "any",
  vendor: "",
  record_origin: "any",
  first_contact_period: "any",
  first_contacted_from: "",
  first_contacted_to: "",
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

function linkedInSearchUrl(person: PifPersonResult) {
  const query = [
    person.name,
    person.firm_name,
    "LinkedIn",
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
  const contactEmailRange = countRange(filters.contact_email_range);
  const staffCountRange = countRange(filters.staff_count_range);
  return {
    search: filters.search.trim() || undefined,
    page,
    page_size: PAGE_SIZE,
    sort_by: filters.sort_by,
    icp_tier: filters.icp_tier || undefined,
    entity_type: filters.entity_type.trim() || undefined,
    recently_researched:
      filters.recently_researched.trim() && Number.isFinite(recently) ? recently : undefined,
    contact_email_min: contactEmailRange.min,
    contact_email_max: contactEmailRange.max,
    staff_count_min: staffCountRange.min,
    staff_count_max: staffCountRange.max,
    autorespond_window: filters.autorespond_window,
    autorespond_type: filters.autorespond_type || undefined,
    website_presence: filters.website_presence,
    research_presence: filters.research_presence,
    staff_presence: filters.staff_presence,
    job_postings_presence: filters.job_postings_presence,
    job_posting_role: filters.job_posting_role || undefined,
    job_posting_tag: filters.job_posting_tag || undefined,
    job_posting_query: filters.job_posting_query.trim() || undefined,
    job_posted_within_days:
      filters.job_posted_within_days && Number.isFinite(Number(filters.job_posted_within_days))
        ? Number(filters.job_posted_within_days)
        : undefined,
    behavior_presence: filters.behavior_presence,
    icp_presence: filters.icp_presence,
    vendor_presence: filters.vendor === "__missing" ? "missing" : filters.vendor.trim() ? "has" : filters.vendor_presence,
    vendor: filters.vendor && filters.vendor !== "__missing" ? filters.vendor.trim() : undefined,
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

function firmFiltersFromSavedTrigger(search: SavedFirmTriggerSearch): FiltersState {
  return {
    ...DEFAULT_FILTERS,
    ...search.criteria,
    icp_tier: (search.criteria.icp_tier ?? "") as FiltersState["icp_tier"],
    job_posting_role: (search.criteria.job_posting_role ?? "") as FiltersState["job_posting_role"],
  };
}

function countRange(value: string): { min?: number; max?: number } {
  if (!value) return {};
  if (value.endsWith("+")) return { min: Number(value.slice(0, -1)) };
  const [min, max] = value.split("-").map(Number);
  return Number.isFinite(min) && Number.isFinite(max) ? { min, max } : {};
}

const COUNT_RANGES = ["0-0", "1-5", "6-10", "11-25", "26-50", "51-100", "101+"] as const;
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
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [view, setView] = useState<LeadsView>(() => {
    const requestedView = searchParams.get("view");
    return requestedView === "contacts" || requestedView === "job_listings" ? requestedView : "firms";
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

  useEffect(() => {
    if (selectedFirmId) setExpandedId(selectedFirmId);
  }, [selectedFirmId]);

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
    setExpandedId(pifId);
  };

  const firmsQuery = useQuery({
    queryKey: ["emailtag", "firms", listParams],
    queryFn: () => listMirroredPifInfo(listParams),
    refetchInterval: 60_000,
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
    setView("firms");
  }

  const data = firmsQuery.data;
  const firms = data?.items ?? [];
  const selectedFirmOnPage = Boolean(selectedFirmId && firms.some((firm) => firm.id === selectedFirmId));
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
    return firmsQuery.refetch();
  };
  const refreshing = view === "contacts" ? peopleQuery.isFetching : view === "firms" ? firmsQuery.isFetching : false;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-xl font-semibold">Leads</h1>
          <p className="text-sm text-neutral-500">
            {view === "contacts"
              ? `${peopleData?.total?.toLocaleString() ?? "—"} contacts from the local EmailTag mirror.`
              : view === "job_listings"
                ? "Job listings from the local EmailTag mirror."
                : `${data?.total?.toLocaleString() ?? "—"} firms from the local EmailTag mirror.`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void refreshLeads()}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-40"
          >
            {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Refresh
          </button>
          <button
            type="button"
            onClick={() => exportAll.mutate("json")}
            disabled={exportAll.isPending}
            className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-40"
          >
            <FileJson className="h-3.5 w-3.5" />
            Export all JSON
          </button>
          <button
            type="button"
            onClick={() => exportAll.mutate("csv")}
            disabled={exportAll.isPending}
            className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-40"
          >
            <Download className="h-3.5 w-3.5" />
            Export all CSV
          </button>
        </div>
      </div>

      {view === "firms" && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricTile icon={<Database className="h-4 w-4" />} label="Matching firms" value={data?.total ?? 0} />
          <MetricTile icon={<SlidersHorizontal className="h-4 w-4" />} label="Showing" value={visibleRange(data)} />
          <MetricTile icon={<Globe className="h-4 w-4" />} label="Missing websites on page" value={pageSummary.missingWebsite} />
          <MetricTile icon={<BarChart3 className="h-4 w-4" />} label="Scored on page" value={pageSummary.scored} />
        </div>
      )}

      <SyncStatusPanel status={syncStatusQuery.data} loading={syncStatusQuery.isLoading} />

      <LeadsViewTabs value={view} onChange={setView} />

      {view === "firms" ? (
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

          {selectedFirmId && !selectedFirmOnPage && (
            <SelectedFirmPanel
              pifId={selectedFirmId}
              onClear={() => setSelectedFirm(null)}
              onAuthError={() => undefined}
            />
          )}

          <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white">
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
                  <thead className="bg-neutral-50 text-left text-[11px] uppercase text-neutral-500">
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
                        expanded={expandedId === firm.id || selectedFirmId === firm.id}
                        onToggle={() => {
                          const open = expandedId === firm.id || selectedFirmId === firm.id;
                          setSelectedFirm(open ? null : firm.id);
                        }}
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
    <section className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
      <button
        type="button"
        onClick={() => setExpanded((current) => !current)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-neutral-50"
      >
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase text-neutral-400">Mirror sync</div>
          <div className="mt-0.5 truncate text-sm text-neutral-800">
            {loading ? "Loading sync status..." : `Last synced ${formatDateTime(lastSynced)}`}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-3 text-xs text-neutral-500">
          {status && (
            <>
              <span>{status.total_firms.toLocaleString()} firms</span>
              <span>{fetched.toLocaleString()} pulled</span>
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
    <div className="rounded-md border border-neutral-100 bg-neutral-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase text-neutral-400">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-neutral-900">{value.toLocaleString()}</div>
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
    <section className="rounded-lg border border-neutral-200 bg-white p-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-64 flex-1 text-[11px] font-medium uppercase tracking-wide text-neutral-400">
          Trigger search
          <select
            value={activeSearchId}
            onChange={(event) => {
              const search = savedSearches.find((item) => item.id === event.target.value);
              if (search) onApply(search);
            }}
            disabled={pending}
            className="mt-1 w-full rounded-md border border-neutral-200 bg-white px-2 py-1.5 text-sm normal-case tracking-normal text-neutral-800 focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
          >
            <option value="">Select saved trigger search</option>
            {savedSearches.map((search) => (
              <option key={search.id} value={search.id}>{search.name}</option>
            ))}
          </select>
        </label>
        <label className="min-w-64 flex-1 text-[11px] font-medium uppercase tracking-wide text-neutral-400">
          New search name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Intake hiring, Filevine firms..."
            className="mt-1 w-full rounded-md border border-neutral-200 px-2 py-1.5 text-sm normal-case tracking-normal text-neutral-800 placeholder:text-neutral-400 focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
          />
        </label>
        <div className="flex h-8 items-center gap-1.5 rounded-md border border-neutral-200 bg-neutral-50 px-3 text-xs text-neutral-600">
          <Briefcase className="h-3.5 w-3.5" />
          <strong className="font-semibold text-neutral-900">{qualifyingCount.toLocaleString()}</strong>
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
          className="inline-flex h-8 items-center gap-1.5 rounded-md bg-neutral-900 px-3 text-xs font-medium text-white hover:bg-neutral-800 disabled:opacity-40"
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
    <div className="space-y-3 rounded-xl border border-neutral-200 bg-white p-3">
      <div className="flex flex-col gap-2 lg:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" />
          <input
            value={filters.search}
            onChange={(event) => updateFilter("search", event.target.value)}
            placeholder="Search firm, email, phone, or website..."
            className="w-full rounded-md border border-neutral-200 py-2 pl-9 pr-3 text-sm focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
          />
        </div>
        <div className="flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-2">
          <span className="text-xs font-medium text-neutral-500">Active only</span>
          <Switch
            checked={filters.active_only}
            onCheckedChange={(checked) => updateFilter("active_only", checked)}
            className="h-5 w-9 data-[state=checked]:bg-neutral-900 data-[state=unchecked]:bg-neutral-200"
          />
        </div>
        <button
          type="button"
          onClick={clearFilters}
          className="inline-flex items-center justify-center gap-1.5 rounded-md border border-neutral-200 px-3 py-2 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
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
        <SelectField label="ICP tier" value={filters.icp_tier} onChange={(value) => updateFilter("icp_tier", value as "" | PifTier)}>
          <option value="">Any</option>
          <option value="A">A</option>
          <option value="B">B</option>
          <option value="C">C</option>
          <option value="D">D</option>
        </SelectField>
        <SelectField label="Entity type" value={filters.entity_type} onChange={(value) => updateFilter("entity_type", value)}>
          <option value="">Any entity</option>
          {ENTITY_TYPES.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
        </SelectField>
        <InputField label="Recently researched" value={filters.recently_researched} onChange={(value) => updateFilter("recently_researched", value)} placeholder="days" inputMode="numeric" />
        <SelectField label="Contact emails" value={filters.contact_email_range} onChange={(value) => updateFilter("contact_email_range", value)}>
          <option value="">Any count</option>
          {COUNT_RANGES.map((value) => <option key={value} value={value}>{value === "0-0" ? "0" : value}</option>)}
        </SelectField>
        <SelectField label="Staff count" value={filters.staff_count_range} onChange={(value) => updateFilter("staff_count_range", value)}>
          <option value="">Any count</option>
          {COUNT_RANGES.map((value) => <option key={value} value={value}>{value === "0-0" ? "0" : value}</option>)}
        </SelectField>
        <SelectField label="Autoresponse" value={filters.autorespond_window} onChange={(value) => updateFilter("autorespond_window", value)}>
          <option value="any">Any</option>
          <option value="24h">Sent in last 24 hours</option>
          <option value="7d">Sent in last 7 days</option>
          <option value="30d">Sent in last 30 days</option>
          <option value="90d">Sent in last 90 days</option>
          <option value="ever">Ever sent</option>
          <option value="never">Never sent</option>
        </SelectField>
        <SelectField label="Autoresponse type" value={filters.autorespond_type} onChange={(value) => updateFilter("autorespond_type", value)}>
          <option value="">Any type</option>
          {AUTORESPOND_TYPES.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
        </SelectField>
        <SelectField label="Website" value={filters.website_presence} onChange={(value) => updateFilter("website_presence", value as WebsitePresence)}>
          {WEBSITE_PRESENCE.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
        </SelectField>
        <SelectField label="Research" value={filters.research_presence} onChange={(value) => updateFilter("research_presence", value as StatusPresence)}>
          {STATUS_PRESENCE.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
        </SelectField>
        <SelectField label="Staff" value={filters.staff_presence} onChange={(value) => updateFilter("staff_presence", value as StatusPresence)}>
          {STATUS_PRESENCE.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
        </SelectField>
        <SelectField label="Job postings" value={filters.job_postings_presence} onChange={(value) => updateFilter("job_postings_presence", value as FiltersState["job_postings_presence"])}>
          <option value="any">Any</option>
          <option value="has">Has recent openings</option>
          <option value="none">No recent openings</option>
          <option value="not_researched">Not researched</option>
          <option value="queued_or_running">Queued or running</option>
          <option value="failed">Failed</option>
        </SelectField>
        <SelectField label="Job trigger" value={filters.job_posting_role} onChange={(value) => updateFilter("job_posting_role", value as FiltersState["job_posting_role"])}>
          <option value="">Any role</option>
          <option value="intake">Intake and reception</option>
          <option value="marketing">Marketing and growth</option>
          <option value="case_operations">Case operations</option>
          <option value="firm_operations">Firm operations</option>
          <option value="technology">Technology and systems</option>
        </SelectField>
        <SelectField label="Job signal" value={filters.job_posting_tag} onChange={(value) => updateFilter("job_posting_tag", value)}>
          <option value="">Any signal</option>
          {JOB_TRIGGER_TAGS.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
        </SelectField>
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
        <SelectField label="Vendor" value={filters.vendor} onChange={(value) => updateFilter("vendor", value)}>
          <option value="">Any vendor</option>
          <option value="__missing">No vendors detected</option>
          {vendorOptions.map((option) => (
            <option key={option.vendor} value={option.vendor}>
              {option.label} ({option.count})
            </option>
          ))}
        </SelectField>
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
    <label className="block text-[11px] font-medium uppercase tracking-wide text-neutral-400">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full rounded-md border border-neutral-200 bg-white px-2 py-1.5 text-sm normal-case tracking-normal text-neutral-800 focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
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
  options: PifPeopleFilterOption[];
  emptyLabel: string;
  searchPlaceholder: string;
  formatValue?: (value: string) => string;
  onChange: (values: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const selected = useMemo(() => new Set(values), [values]);
  const filteredOptions = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return options
      .filter((option) => !needle || formatValue(option.value).toLocaleLowerCase().includes(needle))
      .sort((left, right) => Number(selected.has(right.value)) - Number(selected.has(left.value)));
  }, [formatValue, options, query, selected]);
  const visibleOptions = filteredOptions.slice(0, 200);
  const summary = values.length === 0
    ? emptyLabel
    : values.length === 1
      ? formatValue(values[0])
      : `${values.length} selected`;

  const close = () => {
    setOpen(false);
    setQuery("");
  };

  return (
    <div className="block text-[11px] font-medium uppercase tracking-wide text-neutral-400">
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
          className="flex w-full items-center justify-between gap-2 rounded-md border border-neutral-200 bg-white px-2 py-1.5 text-left text-sm font-normal normal-case tracking-normal text-neutral-800 focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
          title={values.length ? values.map(formatValue).join(", ") : undefined}
        >
          <span className={cn("truncate", values.length === 0 && "text-neutral-500")}>{summary}</span>
          <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 text-neutral-400 transition", open && "rotate-180")} />
        </button>
        {open && (
          <div className="absolute left-0 z-40 mt-1 w-full min-w-72 overflow-hidden rounded-md border border-neutral-200 bg-white shadow-lg">
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
                      checked ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-300 bg-white",
                    )}>
                      {checked && <Check className="h-3 w-3" />}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm font-normal text-neutral-800">
                      {formatValue(option.value)}
                    </span>
                    <span className="shrink-0 text-[11px] text-neutral-400">{option.count.toLocaleString()}</span>
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
    <label className="block text-[11px] font-medium uppercase tracking-wide text-neutral-400">
      {label}
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        inputMode={inputMode}
        className="mt-1 w-full rounded-md border border-neutral-200 px-2 py-1.5 text-sm normal-case tracking-normal text-neutral-800 placeholder:text-neutral-400 focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
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
    <label className="relative block text-[11px] font-medium uppercase tracking-wide text-neutral-400">
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
          className="w-full rounded-md border border-neutral-200 py-1.5 pl-2 pr-8 text-sm normal-case tracking-normal text-neutral-800 placeholder:text-neutral-400 focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
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
  return (
    <div className="inline-flex w-full rounded-lg border border-neutral-200 bg-white p-1 sm:w-auto">
      <button
        type="button"
        onClick={() => onChange("firms")}
        className={cn(
          "inline-flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-2 text-xs font-semibold sm:flex-none",
          value === "firms" ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-50",
        )}
      >
        <Database className="h-3.5 w-3.5" />
        Firms
      </button>
      <button
        type="button"
        onClick={() => onChange("contacts")}
        className={cn(
          "inline-flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-2 text-xs font-semibold sm:flex-none",
          value === "contacts" ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-50",
        )}
      >
        <Users className="h-3.5 w-3.5" />
        Contacts
      </button>
      <button
        type="button"
        onClick={() => onChange("job_listings")}
        className={cn(
          "inline-flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-2 text-xs font-semibold sm:flex-none",
          value === "job_listings" ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-50",
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
  const [filters, setFilters] = useState<PifJobPostingsListParams>({ page: 1, page_size: 25 });
  const debouncedSearch = useDebouncedValue(filters.search ?? "", 250);
  const queryParams = useMemo(() => ({ ...filters, search: debouncedSearch || undefined }), [debouncedSearch, filters]);
  const query = useQuery({
    queryKey: ["pif", "job-postings", queryParams],
    queryFn: () => listMirroredPifJobPostings(queryParams),
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
      <div className="rounded-xl border border-neutral-200 bg-white p-3">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
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
          <SelectField label="Posted" value={filters.posted_within_days ? String(filters.posted_within_days) : ""} onChange={(value) => update("posted_within_days", value ? Number(value) : undefined)}>
            <option value="">Any date</option>
            <option value="7">Last 7 days</option>
            <option value="14">Last 14 days</option>
            <option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option>
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

      <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white">
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
              <thead className="bg-neutral-50 text-left text-[11px] uppercase text-neutral-500">
                <tr>
                  <th className="w-[20%] px-3 py-2 font-medium">Role</th>
                  <th className="w-[17%] px-3 py-2 font-medium">Firm</th>
                  <th className="w-[12%] px-3 py-2 font-medium">Posted</th>
                  <th className="w-[15%] px-3 py-2 font-medium">Category</th>
                  <th className="w-[20%] px-3 py-2 font-medium">Signals</th>
                  <th className="w-[10%] px-3 py-2 font-medium">Technology</th>
                  <th className="w-[6%] px-3 py-2 font-medium">Source</th>
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

function JobListingRow({ posting }: { posting: PifJobPostingResult }) {
  return (
    <tr className="hover:bg-neutral-50">
      <td data-label="Role" className="min-w-0 px-3 py-3">
        <div className="line-clamp-2 font-medium text-neutral-900">{display(posting.title)}</div>
        <div className="mt-0.5 truncate text-[11px] text-neutral-500">{[posting.location, posting.employment_type].filter(Boolean).join(" · ") || "—"}</div>
      </td>
      <td data-label="Firm" className="min-w-0 px-3 py-3">
        <Link href={`/firms/${encodeURIComponent(posting.firm_id)}`} className="block truncate text-blue-600 hover:underline">{display(posting.firm_name)}</Link>
        <div className="truncate text-[11px] text-neutral-400">{formatLabel(posting.entity_type ?? "unknown")}</div>
      </td>
      <td data-label="Posted" className="px-3 py-3 text-xs text-neutral-600">{formatDateOnly(posting.posted_date)}</td>
      <td data-label="Category" className="px-3 py-3"><div className="flex flex-wrap gap-1"><JobTag value={formatLabel(posting.role_category ?? "other")} />{posting.gtm_relevance && <JobTag value={`${formatLabel(posting.gtm_relevance)} GTM`} emphasis={posting.gtm_relevance === "high"} />}</div></td>
      <td data-label="Signals" className="min-w-0 px-3 py-3"><div className="flex flex-wrap gap-1">{posting.trigger_tags.length ? posting.trigger_tags.map((tag) => <JobTag key={tag} value={formatLabel(tag)} />) : <span className="text-xs text-neutral-400">—</span>}</div></td>
      <td data-label="Technology" className="min-w-0 px-3 py-3"><div className="flex flex-wrap gap-1">{posting.technology_mentions.length ? posting.technology_mentions.map((technology) => <JobTag key={technology} value={technology} emphasis />) : <span className="text-xs text-neutral-400">—</span>}</div></td>
      <td data-label="Source" className="px-3 py-3">{posting.source_url ? <a href={posting.source_url} target="_blank" rel="noreferrer" title={posting.source_name} aria-label={`Open source for ${posting.title}`} className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-neutral-200 text-blue-600 hover:bg-blue-50"><ExternalLink className="h-3.5 w-3.5" /></a> : <span className="text-xs text-neutral-400">—</span>}</td>
    </tr>
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
      <div className="space-y-3 rounded-xl border border-neutral-200 bg-white p-3">
        <div className="flex flex-wrap items-end gap-2 border-b border-neutral-100 pb-3">
          <label className="min-w-64 flex-1 text-[11px] font-medium uppercase text-neutral-400">
            Saved search
            <select
              value={activeSavedSearchId}
              onChange={(event) => {
                const search = savedSearches.find((item) => item.id === event.target.value);
                if (search) onApplySavedSearch(search);
              }}
              disabled={savedSearchPending}
              className="mt-1 w-full rounded-md border border-neutral-200 bg-white px-2 py-1.5 text-sm normal-case text-neutral-800 focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
            >
              <option value="">Select saved search</option>
              {savedSearches.map((search) => (
                <option key={search.id} value={search.id}>{search.name}</option>
              ))}
            </select>
          </label>
          <label className="min-w-64 flex-1 text-[11px] font-medium uppercase text-neutral-400">
            New search name
            <input
              value={newSearchName}
              onChange={(event) => setNewSearchName(event.target.value)}
              placeholder="Name these criteria"
              className="mt-1 w-full rounded-md border border-neutral-200 px-2 py-1.5 text-sm normal-case text-neutral-800 placeholder:text-neutral-400 focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
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
            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-neutral-900 px-3 text-xs font-medium text-white hover:bg-neutral-800 disabled:opacity-40"
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

      <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white">
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
              <thead className="bg-neutral-50 text-left text-[11px] uppercase text-neutral-500">
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
                  <tr key={`${person.firm_id ?? "firm"}-${person.email ?? person.name}-${index}`} className="hover:bg-neutral-50">
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
  const linkedInUrl = safeLinkedInUrl(person.linkedin);
  const href = linkedInUrl || linkedInSearchUrl(person);
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
      {linkedInUrl ? <ExternalLink className="h-3.5 w-3.5" /> : <Search className="h-3.5 w-3.5" />}
    </a>
  );
}

function FirmTableRows({
  firm,
  expanded,
  onToggle,
  onViewContacts,
  onAuthError,
}: {
  firm: PifInfoResponse;
  expanded: boolean;
  onToggle: () => void;
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
    <>
      <tr className="hover:bg-neutral-50">
        <td className="px-2 py-3">
          <button
            type="button"
            onClick={onToggle}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-neutral-200 text-neutral-500 hover:bg-white"
            aria-label={expanded ? "Collapse firm details" : "Expand firm details"}
          >
            <ChevronDown className={cn("h-4 w-4 transition", expanded && "rotate-180")} />
          </button>
        </td>
        <td data-label="Firm" className="min-w-0 px-2 py-3">
          <div className="flex min-w-0 items-center gap-1.5">
            <div className="truncate font-medium text-neutral-900">{firm.firm_name}</div>
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
      {expanded && (
        <tr>
          <td colSpan={11} className="bg-neutral-50 px-4 py-4">
            <FirmDetail initialFirm={firm} onAuthError={onAuthError} />
          </td>
        </tr>
      )}
    </>
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
    <div className="rounded-xl border border-neutral-200 bg-white p-3">
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
              className="h-8 w-20 rounded-md border border-neutral-200 px-2 text-sm text-neutral-900 outline-none focus:border-neutral-400"
            />
          </label>
          <button
            type="button"
            onClick={onQueue}
            disabled={pending}
            className="inline-flex items-center gap-1.5 rounded-md bg-neutral-900 px-3 py-2 text-xs font-medium text-white hover:bg-neutral-800 disabled:opacity-40"
          >
            {pending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {buttonLabel}
          </button>
        </div>
      </div>
      {run && (
        <div className="mt-3 rounded-md border border-neutral-200 bg-neutral-50">
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

function SelectedFirmPanel({
  pifId,
  onClear,
  onAuthError,
}: {
  pifId: string;
  onClear: () => void;
  onAuthError: () => void;
}) {
  const firmQuery = useQuery({
    queryKey: ["emailtag", "selected-firm", pifId],
    queryFn: () => getMirroredFirm(pifId),
    enabled: Boolean(pifId),
  });

  useEffect(() => {
    if (isAuthError(firmQuery.error)) onAuthError();
  }, [firmQuery.error, onAuthError]);

  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex flex-col gap-2 border-b border-neutral-200 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-neutral-400">Selected firm</div>
          <div className="mt-0.5 font-mono text-xs text-neutral-500">{pifId}</div>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="inline-flex items-center justify-center rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
        >
          Back to list
        </button>
      </div>
      {firmQuery.isLoading && (
        <div className="flex items-center gap-2 px-4 py-6 text-sm text-neutral-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading firm detail...
        </div>
      )}
      {firmQuery.isError && !isAuthError(firmQuery.error) && (
        <div className="px-4 py-6 text-sm text-rose-600">
          {firmQuery.error instanceof Error ? firmQuery.error.message : "Could not load firm."}
        </div>
      )}
      {firmQuery.data && (
        <div className="p-4">
          <FirmDetail initialFirm={firmQuery.data} onAuthError={onAuthError} />
        </div>
      )}
    </section>
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

  return (
    <div className="space-y-4 rounded-xl border border-neutral-200 bg-white p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="text-base font-semibold text-neutral-900">{firm.firm_name}</div>
            <span className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
              firm.manually_added ? "bg-amber-50 text-amber-700" : "bg-neutral-100 text-neutral-500",
            )}>
              {firm.manually_added ? "Manually added" : "Synced"}
            </span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-neutral-500">
            <span>Updated {formatDateTime(firm.updated_at)}</span>
            <span>Created {formatDateTime(firm.created_at)}</span>
            {firm.website_status && <span>{formatLabel(firm.website_status)}</span>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <ActionButton onClick={() => exportFirm.mutate("json")} pending={exportFirm.isPending} icon={<FileJson className="h-3.5 w-3.5" />}>
            JSON
          </ActionButton>
          <ActionButton onClick={() => exportFirm.mutate("csv")} pending={exportFirm.isPending} icon={<Download className="h-3.5 w-3.5" />}>
            CSV
          </ActionButton>
          {websiteUrl && (
            <a href={websiteUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 px-2.5 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50">
              <ExternalLink className="h-3.5 w-3.5" />
              Website
            </a>
          )}
        </div>
      </div>

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

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <Metric label="Research" value={firm.research_status ?? "unknown"} detail={formatDateTime(firm.last_researched_at)} />
        <Metric label="Staff" value={firm.staff_research_status ?? "unknown"} detail={`${firm.staff?.length ?? 0} staff`} />
        <Metric label="First contacted" value={firm.first_contacted_precise_at ? formatDateTime(firm.first_contacted_precise_at) : "—"} detail="linked external email" />
        <Metric label="ICP" value={firm.icp_tier ? `Tier ${firm.icp_tier}` : "—"} detail={firm.icp_score == null ? "No score" : `${firm.icp_score}/100`} />
        <Metric label="Website confidence" value={firm.website_confidence == null ? "—" : `${Math.round(firm.website_confidence * 100)}%`} detail={firm.website_source ?? "No source"} />
      </div>

      <InfoBlock title="Website resolution">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <KeyValue label="Canonical" value={firm.canonical_website ?? "Missing"} />
          <KeyValue label="Raw website" value={firm.website ?? "Missing"} />
          <KeyValue label="Status" value={firm.website_status ?? "Missing"} />
          <KeyValue label="Source" value={firm.website_source ?? "Unknown"} />
          <KeyValue label="Confidence" value={firm.website_confidence == null ? "Unknown" : `${Math.round(firm.website_confidence * 100)}%`} />
          <KeyValue label="First contacted" value={formatDateTime(firm.first_contacted_precise_at)} />
          <KeyValue label="Updated" value={formatDateTime(firm.updated_at)} />
        </div>
      </InfoBlock>

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

        <CollapsibleInfoBlock title="Front conversation IDs" count={firm.conversation_ids?.length ?? 0} defaultOpen={false}>
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

      <InfoBlock
        title="Vendor Stack"
        action={
          <ActionButton
            onClick={() => vendorDetection.mutate()}
            pending={fullEnrichmentRunning}
            icon={<RefreshCw className={cn("h-3.5 w-3.5", fullEnrichmentRunning && "animate-spin")} />}
          >
            Run full enrichment
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

      <div className="grid gap-4 xl:grid-cols-3">
        <PeopleList title="Leadership" empty="No leadership records." items={firm.leadership ?? []} />
        <PeopleList title="Staff" empty="No staff records." items={firm.staff ?? []} />
        <ExtractedContacts contacts={firm.contacts ?? []} />
      </div>

      <div className="flex flex-wrap gap-2">
        <ActionButton onClick={() => research.mutate("leadership")} pending={fullEnrichmentRunning} icon={<Play className="h-3.5 w-3.5" />}>
          Run full enrichment
        </ActionButton>
        <ActionButton onClick={() => behavior.mutate()} pending={behavior.isPending} icon={<Sparkles className="h-3.5 w-3.5" />}>
          Analyze behavior
        </ActionButton>
        <ActionButton onClick={() => score.mutate()} pending={score.isPending} icon={<BarChart3 className="h-3.5 w-3.5" />}>
          Score ICP
        </ActionButton>
      </div>

      <FirmReviewsPanel
        pifId={firm.id}
        firmName={firm.firm_name}
        address={firm.addresses?.[0] ?? null}
      />

      <FirmCommunicationsPanel pifId={firm.id} />
      <FirmCallsPanel pifId={firm.id} />

      <div className="grid gap-4 xl:grid-cols-2">
        <JsonViewer title="Research data" value={firm.research_data} />
        <JsonViewer title="Behavioral data" value={firm.behavioral_data} />
      </div>

      <FirmDangerZone pifId={firm.id} firmName={firm.firm_name} />
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

function MetricTile({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-neutral-200 bg-white px-4 py-3">
      <div className="flex items-center gap-2 text-[10px] font-medium uppercase text-neutral-400">
        {icon}
        {label}
      </div>
      <div className="mt-2 text-xl font-semibold text-neutral-900">{value}</div>
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="rounded-md border border-neutral-200 bg-neutral-50 px-3 py-2">
      <div className="text-[10px] font-medium uppercase text-neutral-400">{label}</div>
      <div className="mt-1 text-sm font-semibold text-neutral-900">{value}</div>
      <div className="mt-0.5 truncate text-xs text-neutral-500">{detail}</div>
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

function PeopleList({
  title,
  items,
  empty,
}: {
  title: string;
  items: Array<{ name: string; title: string; email: string | null; phone: string | null; linkedin: string | null; bio: string | null }>;
  empty: string;
}) {
  return (
    <InfoBlock title={title}>
      {items.length === 0 && <div className="text-xs text-neutral-400">{empty}</div>}
      <div className="space-y-2">
        {items.map((person, index) => (
          <div key={`${person.name}-${index}`} className="rounded-md bg-neutral-50 p-2">
            <div className="text-sm font-medium text-neutral-900">{person.name}</div>
            <div className="text-xs text-neutral-500">{display(person.title)}</div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-neutral-500">
              {person.email && <span>{person.email}</span>}
              {person.phone && <span>{person.phone}</span>}
              {person.linkedin && (
                <a href={person.linkedin} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">
                  LinkedIn
                </a>
              )}
            </div>
            {person.bio && <p className="mt-1 line-clamp-3 text-xs text-neutral-600">{person.bio}</p>}
          </div>
        ))}
      </div>
    </InfoBlock>
  );
}

function ExtractedContacts({ contacts }: { contacts: PifInfoResponse["contacts"] }) {
  return (
    <InfoBlock title="Extracted Contacts">
      {contacts.length === 0 && <div className="text-xs text-neutral-400">No extracted contacts.</div>}
      <div className="space-y-2">
        {contacts.map((contact, index) => (
          <div key={`${contact.name}-${index}`} className="rounded-md bg-neutral-50 p-2 text-xs">
            <div className="font-medium text-neutral-900">{display(contact.name)}</div>
            <div className="text-neutral-500">{display(contact.title)}</div>
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
