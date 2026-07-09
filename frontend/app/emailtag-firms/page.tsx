"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import type React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  BarChart3,
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
  LogIn,
  LogOut,
  Mail,
  PhoneCall,
  Play,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Sparkles,
  Star,
  Trash2,
  Users,
} from "lucide-react";
import { CommsTable } from "@/components/CommsTable";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import {
  deleteFirm,
  getFirmCalls,
  getFirmReviews,
  listFirmCommunications,
  putFirmReviews,
  type DeleteFirmResult,
} from "@/lib/api";
import {
  ENTITY_TYPE_LABELS,
  EmailtagAuthError,
  analyzeBehavior,
  checkEmailtagAuth,
  detectVendors,
  downloadEmailtagExport,
  getFirm,
  getFullEnrichmentStatus,
  getResearchStatus,
  listPifInfo,
  listPifPeople,
  loginEmailtag,
  logoutEmailtag,
  scoreFirm,
  startFullEnrichment,
  startResearch,
  startStaffResearch,
  type ExportFormat,
  type PifInfoListParams,
  type PifInfoListResponse,
  type PifInfoResponse,
  type PifPeopleListParams,
  type PifPersonResult,
  type PifTier,
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
type FirstContactPeriod = "any" | "last_1_month" | "last_6_months" | "custom";
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
  research_status: string;
  icp_tier: "" | PifTier;
  entity_type: string;
  recently_researched: string;
  website_presence: WebsitePresence;
  research_presence: StatusPresence;
  staff_presence: StatusPresence;
  behavior_presence: SimplePresence;
  icp_presence: SimplePresence;
  vendor_presence: SimplePresence;
  first_contact_period: FirstContactPeriod;
  first_contacted_from: string;
  first_contacted_to: string;
  active_only: boolean;
}

const DEFAULT_FILTERS: FiltersState = {
  search: "",
  sort_by: "updated_at",
  research_status: "",
  icp_tier: "",
  entity_type: "",
  recently_researched: "",
  website_presence: "any",
  research_presence: "any",
  staff_presence: "any",
  behavior_presence: "any",
  icp_presence: "any",
  vendor_presence: "any",
  first_contact_period: "any",
  first_contacted_from: "",
  first_contacted_to: "",
  active_only: true,
};

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

function formatLabel(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function safeWebsiteUrl(value: string | null) {
  if (!value) return null;
  return value.startsWith("http://") || value.startsWith("https://") ? value : `https://${value}`;
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

function extractState(address: string | null | undefined): string {
  if (!address) return "";
  const match = address.match(/\b([A-Z]{2})\b\s*\d{5}(?:-\d{4})?\b/);
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

function getRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : null;
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
    research_status: filters.research_status.trim() || undefined,
    icp_tier: filters.icp_tier || undefined,
    entity_type: filters.entity_type.trim() || undefined,
    recently_researched:
      filters.recently_researched.trim() && Number.isFinite(recently) ? recently : undefined,
    website_presence: filters.website_presence,
    research_presence: filters.research_presence,
    staff_presence: filters.staff_presence,
    behavior_presence: filters.behavior_presence,
    icp_presence: filters.icp_presence,
    vendor_presence: filters.vendor_presence,
    first_contacted_from: firstContact.from,
    first_contacted_to: firstContact.to,
    active_only: filters.active_only,
  };
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
      Loading EmailTag firms...
    </div>
  );
}

function EmailtagFirmsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const selectedFirmId = searchParams.get("firm") ?? "";
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [batchResearchLimit, setBatchResearchLimit] = useState("10");
  const [batchResearchRun, setBatchResearchRun] = useState<BatchResearchRun | null>(null);
  const [filters, setFilters] = useState<FiltersState>(DEFAULT_FILTERS);
  const [page, setPage] = useState(1);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [peopleFilters, setPeopleFilters] = useState<PifPeopleListParams>({
    source: "all",
    page: 1,
    page_size: 10,
  });
  const [peopleOpen, setPeopleOpen] = useState(false);

  const authQuery = useQuery({
    queryKey: ["emailtag-auth"],
    queryFn: checkEmailtagAuth,
    retry: false,
  });

  useEffect(() => {
    if (authQuery.data?.authenticated) setAuthenticated(true);
    if (isAuthError(authQuery.error)) setAuthenticated(false);
  }, [authQuery.data, authQuery.error]);

  const login = useMutation({
    mutationFn: () => loginEmailtag(username.trim(), password),
    onSuccess: async () => {
      setPassword("");
      await queryClient.invalidateQueries({ queryKey: ["emailtag-auth"] });
      setAuthenticated(true);
    },
  });

  const logout = useMutation({
    mutationFn: logoutEmailtag,
    onSettled: () => {
      setAuthenticated(false);
      queryClient.removeQueries({ queryKey: ["emailtag"] });
    },
  });

  const listParams = useMemo(() => filtersToParams(filters, page), [filters, page]);

  useEffect(() => {
    if (selectedFirmId) setExpandedId(selectedFirmId);
  }, [selectedFirmId]);

  const setSelectedFirm = (pifId: string | null) => {
    const params = new URLSearchParams(searchParams.toString());
    if (pifId) {
      params.set("firm", pifId);
    } else {
      params.delete("firm");
    }
    const query = params.toString();
    router.push(query ? `/emailtag-firms?${query}` : "/emailtag-firms");
    setExpandedId(pifId);
  };

  const firmsQuery = useQuery({
    queryKey: ["emailtag", "firms", listParams],
    queryFn: () => listPifInfo(listParams),
    enabled: authenticated === true,
    refetchInterval: 60_000,
  });

  useEffect(() => {
    if (isAuthError(firmsQuery.error)) setAuthenticated(false);
  }, [firmsQuery.error]);

  const peopleQuery = useQuery({
    queryKey: ["emailtag", "people", peopleFilters],
    queryFn: () => listPifPeople(peopleFilters),
    enabled: authenticated === true && peopleOpen,
  });

  useEffect(() => {
    if (isAuthError(peopleQuery.error)) setAuthenticated(false);
  }, [peopleQuery.error]);

  const exportAll = useMutation({
    mutationFn: (format: ExportFormat) => downloadEmailtagExport({ format, include_merged: false }),
    onSuccess: ({ blob, filename }) => downloadBlob(blob, filename),
    onError: (error) => {
      if (isAuthError(error)) setAuthenticated(false);
    },
  });

  const queueMissingResearch = useMutation({
    mutationFn: async () => {
      const requested = Math.max(1, Math.min(100, Number(batchResearchLimit) || 1));
      const selected: PifInfoResponse[] = [];
      let lookupPage = 1;
      let totalPages = 1;

      while (selected.length < requested && lookupPage <= totalPages) {
        const payload = await listPifInfo({
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
    onError: (error) => {
      if (isAuthError(error)) setAuthenticated(false);
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
      authenticated === true &&
      Boolean(batchTaskKey) &&
      Boolean(batchResearchRun?.rows.some((row) => row.task_id && !TERMINAL_TASK_STATUSES.has(row.status))),
    refetchInterval: (query) => {
      const statuses = query.state.data?.map((item) => item.status.status) ?? [];
      return statuses.length > 0 && statuses.every((status) => TERMINAL_TASK_STATUSES.has(status)) ? false : 5_000;
    },
  });

  useEffect(() => {
    if (isAuthError(batchStatusQuery.error)) setAuthenticated(false);
  }, [batchStatusQuery.error]);

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

  function updateFilter<K extends keyof FiltersState>(key: K, value: FiltersState[K]) {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  }

  if (authenticated === null && authQuery.isLoading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-sm text-neutral-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Checking EmailTag session...
      </div>
    );
  }

  if (authenticated !== true) {
    return (
      <div className="mx-auto flex min-h-[60vh] max-w-sm items-center">
        <form
          className="w-full rounded-xl border border-neutral-200 bg-white p-5 shadow-sm"
          onSubmit={(event) => {
            event.preventDefault();
            login.mutate();
          }}
        >
          <div className="mb-5">
            <h1 className="text-lg font-semibold">EmailTag Firms</h1>
            <p className="mt-1 text-sm text-neutral-500">
              Sign in with PIFStats credentials to load firm intelligence.
            </p>
          </div>
          <div className="space-y-3">
            <label className="block text-xs font-medium text-neutral-600">
              Username
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="mt-1 w-full rounded-md border border-neutral-200 px-3 py-2 text-sm focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
                autoComplete="username"
              />
            </label>
            <label className="block text-xs font-medium text-neutral-600">
              Password
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="mt-1 w-full rounded-md border border-neutral-200 px-3 py-2 text-sm focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
                autoComplete="current-password"
              />
            </label>
          </div>
          {login.isError && (
            <div className="mt-3 flex items-start gap-2 rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-700">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {login.error instanceof Error ? login.error.message : "Login failed"}
            </div>
          )}
          <button
            type="submit"
            disabled={login.isPending || !username.trim() || !password}
            className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-40"
          >
            {login.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogIn className="h-4 w-4" />}
            Sign in
          </button>
        </form>
      </div>
    );
  }

  const data = firmsQuery.data;
  const firms = data?.items ?? [];
  const selectedFirmOnPage = Boolean(selectedFirmId && firms.some((firm) => firm.id === selectedFirmId));
  const totalPages = data?.total_pages ?? 1;
  const pageSummary = {
    missingWebsite: firms.filter((firm) => !(firm.canonical_website ?? firm.website)).length,
    scored: firms.filter((firm) => firm.icp_score != null).length,
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-xl font-semibold">EmailTag Firms</h1>
          <p className="text-sm text-neutral-500">
            {data?.total?.toLocaleString() ?? "—"} authenticated PIFStats firms from EmailTag.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void firmsQuery.refetch()}
            disabled={firmsQuery.isFetching}
            className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-40"
          >
            {firmsQuery.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
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
          <button
            type="button"
            onClick={() => logout.mutate()}
            disabled={logout.isPending}
            className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-3 py-1.5 text-xs font-medium text-neutral-500 hover:bg-neutral-50 disabled:opacity-40"
          >
            <LogOut className="h-3.5 w-3.5" />
            Logout
          </button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTile icon={<Database className="h-4 w-4" />} label="Matching firms" value={data?.total ?? 0} />
        <MetricTile icon={<SlidersHorizontal className="h-4 w-4" />} label="Showing" value={visibleRange(data)} />
        <MetricTile icon={<Globe className="h-4 w-4" />} label="Missing websites on page" value={pageSummary.missingWebsite} />
        <MetricTile icon={<BarChart3 className="h-4 w-4" />} label="Scored on page" value={pageSummary.scored} />
      </div>

      <BatchResearchPanel
        limit={batchResearchLimit}
        setLimit={setBatchResearchLimit}
        onQueue={() => queueMissingResearch.mutate()}
        pending={queueMissingResearch.isPending}
        result={queueMissingResearch.data}
        error={queueMissingResearch.error}
        run={batchResearchRun}
        polling={batchStatusQuery.isFetching}
      />

      <FilterBar filters={filters} updateFilter={updateFilter} clearFilters={() => {
        setFilters(DEFAULT_FILTERS);
        setPage(1);
      }} />

      <PeoplePanel
        open={peopleOpen}
        setOpen={setPeopleOpen}
        filters={peopleFilters}
        setFilters={setPeopleFilters}
        items={peopleQuery.data?.items ?? []}
        loading={peopleQuery.isLoading}
      />

      {selectedFirmId && !selectedFirmOnPage && (
        <SelectedFirmPanel
          pifId={selectedFirmId}
          onClear={() => setSelectedFirm(null)}
          onAuthError={() => setAuthenticated(false)}
        />
      )}

      <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white">
        {firmsQuery.isLoading && (
          <div className="px-5 py-8 text-center text-xs text-neutral-400">Loading EmailTag firms...</div>
        )}
        {firmsQuery.isError && !isAuthError(firmsQuery.error) && (
          <div className="px-5 py-8 text-center text-xs text-rose-600">
            {firmsQuery.error instanceof Error ? firmsQuery.error.message : "EmailTag firm list failed"}
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
                    onAuthError={() => setAuthenticated(false)}
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
    </div>
  );
}

function FilterBar({
  filters,
  updateFilter,
  clearFilters,
}: {
  filters: FiltersState;
  updateFilter: <K extends keyof FiltersState>(key: K, value: FiltersState[K]) => void;
  clearFilters: () => void;
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
        <InputField label="Research status" value={filters.research_status} onChange={(value) => updateFilter("research_status", value)} placeholder="completed" />
        <SelectField label="ICP tier" value={filters.icp_tier} onChange={(value) => updateFilter("icp_tier", value as "" | PifTier)}>
          <option value="">Any</option>
          <option value="A">A</option>
          <option value="B">B</option>
          <option value="C">C</option>
          <option value="D">D</option>
        </SelectField>
        <InputField label="Entity type" value={filters.entity_type} onChange={(value) => updateFilter("entity_type", value)} placeholder="pi_law_firm" />
        <InputField label="Recently researched" value={filters.recently_researched} onChange={(value) => updateFilter("recently_researched", value)} placeholder="days" inputMode="numeric" />
        <SelectField label="Website" value={filters.website_presence} onChange={(value) => updateFilter("website_presence", value as WebsitePresence)}>
          {WEBSITE_PRESENCE.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
        </SelectField>
        <SelectField label="Research" value={filters.research_presence} onChange={(value) => updateFilter("research_presence", value as StatusPresence)}>
          {STATUS_PRESENCE.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
        </SelectField>
        <SelectField label="Staff" value={filters.staff_presence} onChange={(value) => updateFilter("staff_presence", value as StatusPresence)}>
          {STATUS_PRESENCE.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
        </SelectField>
        <SelectField label="Behavior" value={filters.behavior_presence} onChange={(value) => updateFilter("behavior_presence", value as SimplePresence)}>
          {PRESENCE.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
        </SelectField>
        <SelectField label="ICP" value={filters.icp_presence} onChange={(value) => updateFilter("icp_presence", value as SimplePresence)}>
          {PRESENCE.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
        </SelectField>
        <SelectField label="Vendors" value={filters.vendor_presence} onChange={(value) => updateFilter("vendor_presence", value as SimplePresence)}>
          {PRESENCE.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
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

function PeoplePanel({
  open,
  setOpen,
  filters,
  setFilters,
  items,
  loading,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
  filters: PifPeopleListParams;
  setFilters: React.Dispatch<React.SetStateAction<PifPeopleListParams>>;
  items: PifPersonResult[];
  loading: boolean;
}) {
  return (
    <div className="rounded-xl border border-neutral-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-neutral-800"
      >
        <span className="inline-flex items-center gap-2">
          <Users className="h-4 w-4 text-neutral-400" />
          People search
        </span>
        <ChevronDown className={cn("h-4 w-4 text-neutral-400 transition", open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-3 border-t border-neutral-100 p-3">
          <div className="grid gap-2 md:grid-cols-4">
            <InputField label="Name" value={filters.name ?? ""} onChange={(value) => setFilters((current) => ({ ...current, name: value || undefined, page: 1 }))} />
            <InputField label="Title" value={filters.title ?? ""} onChange={(value) => setFilters((current) => ({ ...current, title: value || undefined, page: 1 }))} />
            <InputField label="Role" value={filters.role_category ?? ""} onChange={(value) => setFilters((current) => ({ ...current, role_category: value || undefined, page: 1 }))} />
            <SelectField label="Source" value={filters.source ?? "all"} onChange={(value) => setFilters((current) => ({ ...current, source: value as PeopleSource, page: 1 }))}>
              <option value="all">All</option>
              <option value="leadership">Leadership</option>
              <option value="staff">Staff</option>
            </SelectField>
          </div>
          {loading && <div className="py-4 text-center text-xs text-neutral-400">Searching people...</div>}
          {!loading && items.length === 0 && <div className="py-4 text-center text-xs text-neutral-400">No people found.</div>}
          <div className="divide-y divide-neutral-100">
            {items.map((person, index) => (
              <div key={`${person.name}-${person.firm_id ?? index}`} className="flex flex-col gap-1 py-2 text-sm sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="font-medium text-neutral-900">{person.name}</div>
                  <div className="text-xs text-neutral-500">
                    {display(person.title)}
                    {person.firm_name ? ` · ${person.firm_name}` : ""}
                    {person.role_category ? ` · ${person.role_category}` : ""}
                  </div>
                </div>
                <div className="text-xs text-neutral-500">
                  {person.email ?? person.phone ?? person.linkedin ?? person.source ?? ""}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FirmTableRows({
  firm,
  expanded,
  onToggle,
  onAuthError,
}: {
  firm: PifInfoResponse;
  expanded: boolean;
  onToggle: () => void;
  onAuthError: () => void;
}) {
  const queryClient = useQueryClient();
  const [enrichmentTaskId, setEnrichmentTaskId] = useState<string | null>(null);
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
    const status = enrichmentStatus.data?.status;
    if (status && TERMINAL_TASK_STATUSES.has(status)) {
      void queryClient.invalidateQueries({ queryKey: ["emailtag", "firm", firm.id] });
      void queryClient.invalidateQueries({ queryKey: ["emailtag", "firms"] });
    }
  }, [enrichmentStatus.data?.status, firm.id, queryClient]);

  useEffect(() => {
    if (isAuthError(enrichmentStatus.error)) onAuthError();
  }, [enrichmentStatus.error, onAuthError]);

  const enrichmentRunning = enrichment.isPending || isWorkflowRunning(enrichmentStatus.data?.status);

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
          <div className="truncate font-medium text-neutral-900">{firm.firm_name}</div>
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
          <ActionButton
            onClick={() => enrichment.mutate()}
            pending={enrichmentRunning}
            icon={<Sparkles className="h-3.5 w-3.5" />}
          >
            <span className="xl:hidden">Enrich</span>
            <span className="hidden xl:inline">Run full enrichment</span>
          </ActionButton>
          <TaskStatus label="Enrichment" status={enrichmentStatus.data?.status} message={undefined} compact />
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
  limit,
  setLimit,
  onQueue,
  pending,
  result,
  error,
  run,
  polling,
}: {
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
          <div className="text-sm font-semibold text-neutral-900">Queue missing firm research</div>
          <div className="mt-1 text-xs text-neutral-500">
            Most recently updated firms first, only where research has never been started.
          </div>
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
            Queue research
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
    queryFn: () => getFirm(pifId),
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
  const [researchTaskId, setResearchTaskId] = useState<string | null>(null);
  const [vendorBaseline, setVendorBaseline] = useState<string | null>(null);
  const [vendorPolling, setVendorPolling] = useState(false);

  const firmQuery = useQuery({
    queryKey: ["emailtag", "firm", initialFirm.id],
    queryFn: () => getFirm(initialFirm.id),
    initialData: initialFirm,
    refetchInterval: vendorPolling ? 3_000 : false,
  });

  const firm = firmQuery.data ?? initialFirm;

  useEffect(() => {
    if (vendorPolling && vendorBaseline && firm.updated_at !== vendorBaseline) {
      setVendorPolling(false);
      setVendorBaseline(null);
    }
  }, [firm.updated_at, vendorBaseline, vendorPolling]);

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
    onMutate: () => {
      setVendorBaseline(firm.updated_at);
      setVendorPolling(true);
    },
    onError: (error) => {
      setVendorPolling(false);
      if (isAuthError(error)) onAuthError();
    },
  });

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
  const enrichmentSteps = buildEnrichmentSteps(firm);

  return (
    <div className="space-y-4 rounded-xl border border-neutral-200 bg-white p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-base font-semibold text-neutral-900">{firm.firm_name}</div>
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

      <TaskStatus label="Research" status={researchStatus.data?.status} message={researchStatus.data?.message} />

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
        <InfoBlock title="Contact data">
          <KeyValue label="Emails" value={firm.emails?.join(", ") || "—"} />
          <KeyValue label="Phones" value={firm.phones?.join(", ") || "—"} />
          <KeyValue label="Fax" value={firm.fax ?? "—"} />
          <KeyValue label="Addresses" value={firm.addresses?.join(" · ") || "—"} />
          <KeyValue label="Extraction notes" value={firm.extraction_notes ?? "—"} />
        </InfoBlock>

        <InfoBlock title="Front conversation IDs">
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
        </InfoBlock>
      </div>

      <InfoBlock
        title="Vendor Stack"
        action={
          <ActionButton onClick={() => vendorDetection.mutate()} pending={vendorDetection.isPending || vendorPolling} icon={<RefreshCw className={cn("h-3.5 w-3.5", vendorPolling && "animate-spin")} />}>
            Detect vendors
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

      <div className="grid gap-4 xl:grid-cols-3">
        <PeopleList title="Leadership" empty="No leadership records." items={firm.leadership ?? []} />
        <PeopleList title="Staff" empty="No staff records." items={firm.staff ?? []} />
        <ExtractedContacts contacts={firm.contacts ?? []} />
      </div>

      <div className="flex flex-wrap gap-2">
        <ActionButton onClick={() => research.mutate("leadership")} pending={research.isPending} icon={<Play className="h-3.5 w-3.5" />}>
          Research leadership
        </ActionButton>
        <ActionButton onClick={() => research.mutate("staff")} pending={research.isPending} icon={<Users className="h-3.5 w-3.5" />}>
          Research staff
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

function FirmReviewsPanel({
  pifId,
  firmName,
  address,
}: {
  pifId: string;
  firmName: string;
  address: string | null;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["firm-reviews", pifId],
    queryFn: () => getFirmReviews(pifId),
  });

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
}: {
  label: string;
  status?: string;
  message?: string;
  compact?: boolean;
}) {
  if (!status && !message) return null;
  return (
    <div className={cn("flex items-start gap-2 rounded-md bg-neutral-50 text-xs text-neutral-600", compact ? "mt-1 px-2 py-1" : "px-3 py-2")}>
      <Loader2 className={cn("mt-0.5 h-3.5 w-3.5", status && !TERMINAL_TASK_STATUSES.has(status) && "animate-spin")} />
      <span>
        <span className="font-medium">{label}:</span> {status ? formatLabel(status) : ""}
        {message ? ` · ${message}` : ""}
      </span>
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

function buildEnrichmentSteps(firm: PifInfoResponse): WorkflowStepInfo[] {
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
  if (status === "completed") return "completed";
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
