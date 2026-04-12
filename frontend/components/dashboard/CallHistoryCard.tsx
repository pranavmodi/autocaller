"use client";

import { useState, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  History,
  RefreshCw,
  Phone,
  PhoneForwarded,
  PhoneMissed,
  PhoneOff,
  MessageSquare,
  User,
  Bot,
  CalendarDays,
  ChevronDown,
  NotebookPen,
  Loader2,
  FileText,
  Clock,
  X,
  ArrowRightLeft,
  ShieldAlert,
  Mail,
  Activity,
  Search,
  Play,
} from "lucide-react";
import { formatDate, formatTime, formatDuration } from "@/lib/utils";
import type { CallLog } from "@/types";

interface CallHistoryCardProps {
  calls: CallLog[];
  callsTotal: number;
  onRefresh: () => void;
  onLoadMore: () => void;
  hasMore: boolean;
}

const outcomeConfig: Record<
  string,
  {
    label: string;
    icon: typeof Phone;
    variant: "default" | "secondary" | "destructive" | "outline" | "success" | "warning";
    color: string;
  }
> = {
  transferred: { label: "Transferred", icon: PhoneForwarded, variant: "success", color: "text-emerald-600 bg-emerald-50" },
  callback_requested: { label: "Callback", icon: MessageSquare, variant: "secondary", color: "text-blue-600 bg-blue-50" },
  no_answer: { label: "No Answer", icon: PhoneMissed, variant: "warning", color: "text-amber-600 bg-amber-50" },
  voicemail: { label: "Voicemail", icon: MessageSquare, variant: "warning", color: "text-amber-600 bg-amber-50" },
  wrong_number: { label: "Wrong Number", icon: PhoneOff, variant: "destructive", color: "text-red-600 bg-red-50" },
  disconnected: { label: "Disconnected", icon: PhoneOff, variant: "destructive", color: "text-red-600 bg-red-50" },
  completed: { label: "Completed", icon: Phone, variant: "default", color: "text-slate-600 bg-slate-50" },
  failed: { label: "Failed", icon: PhoneOff, variant: "destructive", color: "text-red-600 bg-red-50" },
  in_progress: { label: "In Progress", icon: Phone, variant: "default", color: "text-blue-600 bg-blue-50" },
};

// Call Status (high-level: did the call connect at all?)
const statusConfig: Record<
  string,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" | "success" | "warning" }
> = {
  called: { label: "Called", variant: "success" },
  failed: { label: "Failed", variant: "destructive" },
  in_progress: { label: "In Progress", variant: "default" },
};

// Call Disposition (detailed: what happened during the call)
const dispositionConfig: Record<
  string,
  { label: string; icon: typeof Phone; color: string }
> = {
  transferred: { label: "Transferred to Scheduler", icon: PhoneForwarded, color: "text-emerald-600 bg-emerald-50" },
  voicemail_left: { label: "Voicemail Left", icon: MessageSquare, color: "text-amber-600 bg-amber-50" },
  no_answer: { label: "No Answer", icon: PhoneMissed, color: "text-amber-600 bg-amber-50" },
  hung_up: { label: "Hung Up", icon: PhoneOff, color: "text-orange-600 bg-orange-50" },
  callback_requested: { label: "Callback Requested", icon: MessageSquare, color: "text-blue-600 bg-blue-50" },
  wrong_number: { label: "Wrong Number", icon: PhoneOff, color: "text-red-600 bg-red-50" },
  completed: { label: "Completed", icon: Phone, color: "text-slate-600 bg-slate-50" },
  disconnected_number: { label: "Disconnected Number", icon: PhoneOff, color: "text-red-600 bg-red-50" },
  technical_error: { label: "Technical Error", icon: ShieldAlert, color: "text-red-600 bg-red-50" },
  in_progress: { label: "In Progress", icon: Phone, color: "text-blue-600 bg-blue-50" },
};

interface GroupedCalls {
  dateKey: string;
  dateLabel: string;
  calls: CallLog[];
}

type DateFilter = "all" | "today" | "yesterday" | "7days" | "custom";

function inferPreferredCallbackFromTranscript(call: CallLog): string | null {
  if (!call.transcript?.length) return null;

  const systemCapture = call.transcript.find(
    (entry) =>
      entry.speaker === "system" &&
      entry.text.toLowerCase().startsWith("preferred callback captured:")
  );
  if (systemCapture) {
    return systemCapture.text.split(":").slice(1).join(":").trim() || null;
  }

  const recent = call.transcript.slice(-8).map((t) => t.text.toLowerCase());
  const marker = recent.find(
    (t) =>
      (t.includes("call me") || t.includes("call you back") || t.includes("callback")) &&
      (t.includes("tomorrow") || t.includes("today") || t.includes("pm") || t.includes("am") || t.includes("hour") || t.includes("minute"))
  );
  if (marker) return marker;
  return null;
}

const DISPLAY_TIMEZONE = "America/Los_Angeles";

/** Format a Date as YYYY-MM-DD in Pacific time. */
function toDateKey(d: Date): string {
  // Use Intl to get the date parts in Pacific time
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: DISPLAY_TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d); // returns "YYYY-MM-DD" in en-CA locale
  return parts;
}

function getDateKeyFromCall(call: CallLog): string {
  const source = call.started_at || call.ended_at;
  if (!source) return "unknown-date";
  return toDateKey(new Date(source));
}

function getDateLabel(dateKey: string): string {
  if (dateKey === "unknown-date") return "Unknown Date";
  const today = new Date();
  const todayKey = toDateKey(today);
  const yesterday = new Date(today.getTime() - 86400000);
  const yesterdayKey = toDateKey(yesterday);

  if (dateKey === todayKey) return "Today";
  if (dateKey === yesterdayKey) return "Yesterday";
  // Parse and format via the shared formatDate (already Pacific-aware)
  return formatDate(new Date(`${dateKey}T12:00:00`));
}

export function CallHistoryCard({ calls, callsTotal, onRefresh, onLoadMore, hasMore }: CallHistoryCardProps) {
  const [loadingMore, setLoadingMore] = useState(false);
  const [transcriptCall, setTranscriptCall] = useState<CallLog | null>(null);
  const [eventsCall, setEventsCall] = useState<CallLog | null>(null);
  const [dateFilter, setDateFilter] = useState<DateFilter>("all");
  const [customDate, setCustomDate] = useState<string>("");
  const [collapsedDates, setCollapsedDates] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [dispositionFilter, setDispositionFilter] = useState<string>("all");
  const [playingCallId, setPlayingCallId] = useState<string | null>(null);

  // Compute date boundaries
  const todayKey = toDateKey(new Date());
  const yesterdayDate = new Date();
  yesterdayDate.setDate(yesterdayDate.getDate() - 1);
  const yesterdayKey = toDateKey(yesterdayDate);
  const sevenDaysAgo = new Date();
  sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
  const sevenDaysKey = toDateKey(sevenDaysAgo);

  // Group + filter calls by date and search query
  const groupedCalls = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const byDate = new Map<string, CallLog[]>();
    for (const call of calls) {
      const key = getDateKeyFromCall(call);

      // Apply date filter
      if (dateFilter === "today" && key !== todayKey) continue;
      if (dateFilter === "yesterday" && key !== yesterdayKey) continue;
      if (dateFilter === "7days" && key !== "unknown-date" && key < sevenDaysKey) continue;
      if (dateFilter === "custom" && customDate && key !== customDate) continue;

      // Apply call status filter
      if (statusFilter !== "all" && call.call_status !== statusFilter) continue;

      // Apply call disposition filter
      if (dispositionFilter !== "all" && call.call_disposition !== dispositionFilter) continue;

      // Apply search filter (name, patient id, phone, order id, status, disposition, mock)
      if (q) {
        const statusLabel = statusConfig[call.call_status]?.label || call.call_status;
        const dispositionLabel = dispositionConfig[call.call_disposition]?.label || call.call_disposition;
        const haystack = [
          call.patient_name,
          call.patient_id,
          call.phone,
          call.order_id,
          call.outcome,
          call.call_status,
          call.call_disposition,
          statusLabel,
          dispositionLabel,
          call.mock_mode ? "mock" : "",
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(q)) continue;
      }

      const existing = byDate.get(key) || [];
      existing.push(call);
      byDate.set(key, existing);
    }

    const sortedKeys = Array.from(byDate.keys()).sort((a, b) => (a < b ? 1 : -1));
    const groups: GroupedCalls[] = [];
    for (const key of sortedKeys) {
      groups.push({
        dateKey: key,
        dateLabel: getDateLabel(key),
        calls: byDate.get(key) || [],
      });
    }
    return groups;
  }, [calls, dateFilter, customDate, searchQuery, statusFilter, dispositionFilter, todayKey, yesterdayKey, sevenDaysKey]);

  const filteredCallCount = groupedCalls.reduce((sum, g) => sum + g.calls.length, 0);

  const isExpanded = (dateKey: string, index: number) =>
    index === 0 ? !collapsedDates.has(dateKey) : collapsedDates.has(dateKey);

  const toggleDate = (dateKey: string) => {
    setCollapsedDates((prev) => {
      const next = new Set(prev);
      next.has(dateKey) ? next.delete(dateKey) : next.add(dateKey);
      return next;
    });
  };

  const handleFilterChange = (filter: DateFilter) => {
    setDateFilter(filter);
    if (filter !== "custom") setCustomDate("");
    setCollapsedDates(new Set());
  };

  const handleCustomDateChange = (value: string) => {
    setCustomDate(value);
    setDateFilter("custom");
    setCollapsedDates(new Set());
  };

  // Notes for transcript modal
  const transcriptNotes: string[] = [];
  if (transcriptCall) {
    const preferred =
      transcriptCall.preferred_callback_time || inferPreferredCallbackFromTranscript(transcriptCall);
    if (preferred) {
      transcriptNotes.push(`Preferred callback: ${preferred}`);
    } else if (transcriptCall.outcome === "callback_requested") {
      transcriptNotes.push("Patient requested a callback.");
    }
    if (transcriptCall.error_message) {
      transcriptNotes.push(`Call issue: ${transcriptCall.error_message}`);
    }
  }

  return (
    <>
      <Card className="flex flex-col">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-lg">
              <History className="h-5 w-5" />
              Call History
            </CardTitle>
            <div className="flex items-center gap-2">
              {callsTotal > 0 && (() => {
                const isFiltered =
                  dateFilter !== "all" ||
                  !!searchQuery ||
                  statusFilter !== "all" ||
                  dispositionFilter !== "all";
                let label: string;
                let n: number;
                if (isFiltered) {
                  // Filters apply to already-loaded calls only
                  n = filteredCallCount;
                  label = `${filteredCallCount} of ${calls.length} loaded`;
                } else if (calls.length < callsTotal) {
                  // Some calls loaded, more available on the server
                  n = callsTotal;
                  label = `${calls.length} of ${callsTotal}`;
                } else {
                  // All calls loaded
                  n = callsTotal;
                  label = `${callsTotal}`;
                }
                return (
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {label} call{n !== 1 ? "s" : ""}
                  </span>
                );
              })()}
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onRefresh}>
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>

          {/* Search bar */}
          {calls.length > 0 && (
            <div className="relative pt-2">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 mt-1 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
              <Input
                type="text"
                placeholder="Search by name, patient ID, phone, order ID, or outcome..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-8 pl-8 pr-8 text-xs"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 mt-1 text-muted-foreground hover:text-foreground"
                  aria-label="Clear search"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          )}

          {/* Date filter toolbar */}
          {calls.length > 0 && (
            <div className="flex items-center gap-2 pt-2 flex-wrap">
              <div className="flex items-center rounded-lg border bg-muted/30 p-0.5 gap-0.5">
                {(
                  [
                    { key: "all", label: "All" },
                    { key: "today", label: "Today" },
                    { key: "yesterday", label: "Yesterday" },
                    { key: "7days", label: "7 Days" },
                  ] as const
                ).map(({ key, label }) => (
                  <button
                    key={key}
                    onClick={() => handleFilterChange(key)}
                    className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                      dateFilter === key
                        ? "bg-background text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="relative">
                <Input
                  type="date"
                  value={customDate}
                  onChange={(e) => handleCustomDateChange(e.target.value)}
                  className="h-7 w-[150px] text-xs pl-2 pr-7"
                  max={todayKey}
                />
                {dateFilter === "custom" && customDate && (
                  <button
                    onClick={() => handleFilterChange("all")}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>

              {/* Call Status dropdown */}
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="h-7 rounded-md border bg-background px-2 text-xs cursor-pointer"
                aria-label="Filter by call status"
              >
                <option value="all">All Statuses</option>
                <option value="called">Called</option>
                <option value="failed">Failed</option>
                <option value="in_progress">In Progress</option>
              </select>

              {/* Call Disposition dropdown */}
              <select
                value={dispositionFilter}
                onChange={(e) => setDispositionFilter(e.target.value)}
                className="h-7 rounded-md border bg-background px-2 text-xs cursor-pointer"
                aria-label="Filter by call disposition"
              >
                <option value="all">All Dispositions</option>
                <option value="transferred">Transferred to Scheduler</option>
                <option value="voicemail_left">Voicemail Left</option>
                <option value="no_answer">No Answer</option>
                <option value="hung_up">Hung Up</option>
                <option value="callback_requested">Callback Requested</option>
                <option value="wrong_number">Wrong Number</option>
                <option value="completed">Completed</option>
                <option value="disconnected_number">Disconnected Number</option>
                <option value="technical_error">Technical Error</option>
              </select>
            </div>
          )}
        </CardHeader>

        <CardContent className="flex-1 p-0">
          <ScrollArea className="h-[520px]">
            <div className="space-y-3 px-6 pb-6 pt-2">
              {calls.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                  <History className="h-12 w-12 mb-3 opacity-10" />
                  <p className="text-sm font-medium">No calls yet</p>
                  <p className="text-xs mt-1">Completed calls will appear here</p>
                </div>
              ) : groupedCalls.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                  {searchQuery ? (
                    <>
                      <Search className="h-12 w-12 mb-3 opacity-10" />
                      <p className="text-sm font-medium">No calls match your search</p>
                      <p className="text-xs mt-1">Try different search terms</p>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="mt-3 text-xs"
                        onClick={() => setSearchQuery("")}
                      >
                        Clear search
                      </Button>
                    </>
                  ) : (
                    <>
                      <CalendarDays className="h-12 w-12 mb-3 opacity-10" />
                      <p className="text-sm font-medium">No calls for this date</p>
                      <p className="text-xs mt-1">Try a different date or clear the filter</p>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="mt-3 text-xs"
                        onClick={() => handleFilterChange("all")}
                      >
                        Show all calls
                      </Button>
                    </>
                  )}
                </div>
              ) : (
                groupedCalls.map((group, groupIndex) => (
                  <Collapsible
                    key={group.dateKey}
                    open={isExpanded(group.dateKey, groupIndex)}
                    onOpenChange={() => toggleDate(group.dateKey)}
                  >
                    {/* Date group header */}
                    <CollapsibleTrigger className="flex w-full items-center justify-between rounded-lg border bg-muted/30 px-3 py-2 hover:bg-muted/50 transition-colors text-left group">
                      <div className="flex items-center gap-2">
                        <ChevronDown
                          className={`h-3.5 w-3.5 text-muted-foreground shrink-0 transition-transform duration-200 ${
                            isExpanded(group.dateKey, groupIndex) ? "" : "-rotate-90"
                          }`}
                        />
                        <CalendarDays className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="text-sm font-medium">{group.dateLabel}</span>
                      </div>
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0 tabular-nums">
                        {group.calls.length} call{group.calls.length !== 1 ? "s" : ""}
                      </Badge>
                    </CollapsibleTrigger>

                    {/* Call rows */}
                    <CollapsibleContent>
                      <div className="space-y-1.5 pt-1.5 ml-2 border-l-2 border-muted pl-3">
                        {group.calls.map((call) => {
                          // Prefer new status/disposition; fall back to legacy outcome
                          const dispCfg =
                            dispositionConfig[call.call_disposition] ||
                            outcomeConfig[call.outcome] ||
                            outcomeConfig.completed;
                          const statusCfg = statusConfig[call.call_status] || statusConfig.in_progress;
                          const Icon = dispCfg.icon;
                          const preferred =
                            call.preferred_callback_time || inferPreferredCallbackFromTranscript(call);

                          return (
                            <div
                              key={call.call_id}
                              className="group/row rounded-lg border bg-card px-3 py-2.5 hover:shadow-sm transition-all"
                            >
                              <div className="flex items-center justify-between gap-3">
                                {/* Left: icon + info */}
                                <div className="flex items-center gap-3 min-w-0">
                                  <div
                                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${dispCfg.color}`}
                                  >
                                    <Icon className="h-3.5 w-3.5" />
                                  </div>
                                  <div className="min-w-0">
                                    <div className="flex items-center gap-2 flex-wrap">
                                      <p className="text-sm font-medium truncate">
                                        {call.patient_name}
                                      </p>
                                      <Badge
                                        variant={statusCfg.variant}
                                        className="text-[10px] px-1.5 py-0 shrink-0"
                                      >
                                        {statusCfg.label}
                                      </Badge>
                                      <Badge
                                        variant="outline"
                                        className="text-[10px] px-1.5 py-0 shrink-0"
                                      >
                                        {dispCfg.label}
                                      </Badge>
                                      {call.mock_mode && (
                                        <Badge
                                          variant="outline"
                                          className="text-[10px] px-1.5 py-0 shrink-0 border-orange-300 bg-orange-50 text-orange-700 dark:border-orange-800 dark:bg-orange-950/40 dark:text-orange-300"
                                          title="This call was placed in mock mode (redirected to a test number)"
                                        >
                                          MOCK
                                        </Badge>
                                      )}
                                    </div>
                                    <div className="flex items-center gap-1.5 mt-0.5">
                                      <span className="text-xs text-muted-foreground tabular-nums">
                                        {call.started_at ? formatTime(call.started_at) : "—"}
                                      </span>
                                      <span className="text-muted-foreground/40">·</span>
                                      <span className="text-xs text-muted-foreground font-mono">
                                        {call.patient_id}
                                      </span>
                                      <span className="text-muted-foreground/40">·</span>
                                      <span className="text-xs text-muted-foreground tabular-nums">
                                        {call.phone || "No phone"}
                                      </span>
                                      <span className="text-muted-foreground/40">·</span>
                                      <span className="text-xs text-muted-foreground tabular-nums flex items-center gap-1">
                                        <Clock className="h-3 w-3" />
                                        {formatDuration(call.duration_seconds)}
                                      </span>
                                    </div>
                                  </div>
                                </div>

                                {/* Right: notes + transcript button */}
                                <div className="flex items-center gap-2 shrink-0">
                                  {preferred && (
                                    <span className="hidden sm:flex items-center gap-1 text-[11px] text-muted-foreground max-w-[160px] truncate">
                                      <NotebookPen className="h-3 w-3 shrink-0" />
                                      {preferred}
                                    </span>
                                  )}
                                  {call.has_recording && (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      className="h-7 gap-1.5 text-xs opacity-70 group-hover/row:opacity-100 transition-opacity"
                                      onClick={() =>
                                        setPlayingCallId(playingCallId === call.call_id ? null : call.call_id)
                                      }
                                      title="Play call recording"
                                    >
                                      <Play className="h-3 w-3" />
                                      <span className="hidden sm:inline">
                                        {playingCallId === call.call_id ? "Hide" : "Audio"}
                                      </span>
                                    </Button>
                                  )}
                                  {call.transcript.some((e) => e.speaker === "system") && (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      className="h-7 gap-1.5 text-xs opacity-70 group-hover/row:opacity-100 transition-opacity"
                                      onClick={() => setEventsCall(call)}
                                    >
                                      <NotebookPen className="h-3 w-3" />
                                      <span className="hidden sm:inline">Events</span>
                                    </Button>
                                  )}
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    className="h-7 gap-1.5 text-xs opacity-70 group-hover/row:opacity-100 transition-opacity"
                                    onClick={() => setTranscriptCall(call)}
                                  >
                                    <FileText className="h-3 w-3" />
                                    <span className="hidden sm:inline">Transcript</span>
                                  </Button>
                                </div>
                              </div>

                              {/* Inline audio player */}
                              {playingCallId === call.call_id && call.has_recording && (
                                <div className="mt-2 ml-11">
                                  <audio
                                    controls
                                    autoPlay
                                    className="w-full h-8"
                                    src={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/calls/${call.call_id}/audio`}
                                  >
                                    Your browser does not support the audio element.
                                  </audio>
                                </div>
                              )}

                              {/* Error message — red for failed calls, muted for called calls with notes */}
                              {call.error_message && call.call_status === "failed" && (
                                <div className="flex items-start gap-1.5 mt-2 ml-11 px-2 py-1.5 rounded bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900">
                                  <ShieldAlert className="h-3 w-3 text-red-600 dark:text-red-400 shrink-0 mt-0.5" />
                                  <div className="min-w-0">
                                    {call.error_code && (
                                      <div className="text-[10px] font-mono text-red-700 dark:text-red-400 uppercase">
                                        {call.error_code}
                                      </div>
                                    )}
                                    <div className="text-xs text-red-700 dark:text-red-300 break-words">
                                      {call.error_message}
                                    </div>
                                  </div>
                                </div>
                              )}

                              {/* Action badges */}
                              {(call.transfer_attempted || call.voicemail_left || call.sms_sent) && (
                                <div className="flex gap-1.5 mt-2 ml-11">
                                  {call.transfer_attempted && (
                                    <Badge
                                      variant={call.transfer_success ? "success" : "warning"}
                                      className="text-[10px] px-1.5 py-0"
                                    >
                                      Transfer {call.transfer_success ? "OK" : "Tried"}
                                    </Badge>
                                  )}
                                  {call.voicemail_left && (
                                    <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                                      VM Left
                                    </Badge>
                                  )}
                                  {call.sms_sent && (
                                    <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                                      SMS Sent
                                    </Badge>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </CollapsibleContent>
                  </Collapsible>
                ))
              )}
              {hasMore && groupedCalls.length > 0 && (
                <div className="flex justify-center pt-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs text-muted-foreground"
                    disabled={loadingMore}
                    onClick={async () => {
                      setLoadingMore(true);
                      try {
                        await onLoadMore();
                      } finally {
                        setLoadingMore(false);
                      }
                    }}
                  >
                    {loadingMore ? <Loader2 className="h-3 w-3 mr-1.5 animate-spin" /> : null}
                    Load older calls
                  </Button>
                </div>
              )}
            </div>
          </ScrollArea>
        </CardContent>
      </Card>

      {/* Transcript Modal */}
      <Dialog open={!!transcriptCall} onOpenChange={() => setTranscriptCall(null)}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-hidden flex flex-col gap-0">
          {transcriptCall && (() => {
            const config = outcomeConfig[transcriptCall.outcome] || outcomeConfig.completed;
            const TIcon = config.icon;
            return (
              <>
                {/* Header */}
                <DialogHeader className="pb-3">
                  <DialogTitle className="text-base font-semibold">Transcript</DialogTitle>
                </DialogHeader>

                {/* Call summary bar */}
                <div className="rounded-lg border bg-muted/30 px-4 py-3 mb-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`flex h-9 w-9 items-center justify-center rounded-full ${config.color}`}>
                        <TIcon className="h-4 w-4" />
                      </div>
                      <div>
                        <p className="text-sm font-semibold">{transcriptCall.patient_name}</p>
                        <p className="text-xs text-muted-foreground tabular-nums">
                          {transcriptCall.phone}
                          {transcriptCall.started_at && ` · ${formatDate(transcriptCall.started_at)} ${formatTime(transcriptCall.started_at)}`}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground tabular-nums flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {formatDuration(transcriptCall.duration_seconds)}
                      </span>
                      <Badge variant={config.variant} className="text-xs">
                        {config.label}
                      </Badge>
                    </div>
                  </div>

                  {/* Notes + actions */}
                  {(transcriptNotes.length > 0 || transcriptCall.transfer_attempted || transcriptCall.voicemail_left || transcriptCall.sms_sent) && (
                    <>
                      <Separator className="my-2.5" />
                      <div className="space-y-1.5">
                        {transcriptNotes.map((note, idx) => (
                          <p key={idx} className="text-xs text-muted-foreground flex items-center gap-1.5">
                            <NotebookPen className="h-3 w-3 shrink-0" />
                            {note}
                          </p>
                        ))}
                        {(transcriptCall.transfer_attempted || transcriptCall.voicemail_left || transcriptCall.sms_sent) && (
                          <div className="flex gap-1.5 pt-0.5">
                            {transcriptCall.transfer_attempted && (
                              <Badge variant={transcriptCall.transfer_success ? "success" : "warning"} className="text-[10px]">
                                Transfer {transcriptCall.transfer_success ? "Success" : "Attempted"}
                              </Badge>
                            )}
                            {transcriptCall.voicemail_left && <Badge variant="secondary" className="text-[10px]">VM Left</Badge>}
                            {transcriptCall.sms_sent && <Badge variant="secondary" className="text-[10px]">SMS Sent</Badge>}
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>

                {/* Transcript messages */}
                <div className="flex-1 min-h-0 overflow-y-auto rounded-lg border bg-muted/10">
                  <div className="p-4 space-y-3">
                    {transcriptCall.transcript.filter((e) => e.speaker !== "system").length === 0 ? (
                      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                        <MessageSquare className="h-8 w-8 mb-2 opacity-15" />
                        <p className="text-xs">No transcript available</p>
                      </div>
                    ) : (
                      transcriptCall.transcript.filter((e) => e.speaker !== "system").map((entry, index) => (
                        <div
                          key={index}
                          className={`flex gap-2.5 ${entry.speaker === "patient" ? "justify-end" : "justify-start"}`}
                        >
                          {entry.speaker === "ai" && (
                            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary mt-0.5">
                              <Bot className="h-3.5 w-3.5" />
                            </div>
                          )}
                          <div
                            className={`rounded-xl px-3.5 py-2 text-sm max-w-[75%] ${
                              entry.speaker === "ai"
                                ? "bg-muted"
                                : entry.speaker === "patient"
                                  ? "bg-primary text-primary-foreground"
                                  : "bg-amber-50 text-amber-900 border border-amber-200"
                            }`}
                          >
                            <p className="leading-relaxed">{entry.text}</p>
                            <p className="text-[10px] opacity-60 mt-1 tabular-nums">
                              {entry.timestamp ? formatTime(entry.timestamp) : ""}
                            </p>
                          </div>
                          {entry.speaker === "patient" && (
                            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary mt-0.5">
                              <User className="h-3.5 w-3.5" />
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </>
            );
          })()}
        </DialogContent>
      </Dialog>

      {/* Events Modal */}
      <Dialog open={!!eventsCall} onOpenChange={() => setEventsCall(null)}>
        <DialogContent className="max-w-lg max-h-[70vh] overflow-hidden flex flex-col gap-0">
          {eventsCall && (() => {
            const config = outcomeConfig[eventsCall.outcome] || outcomeConfig.completed;
            const EIcon = config.icon;
            const systemEntries = eventsCall.transcript.filter((e) => e.speaker === "system");

            const categorize = (text: string) => {
              const t = text.toLowerCase();
              if (t.includes("transfer")) return { icon: ArrowRightLeft, color: "text-blue-500 bg-blue-50" };
              if (t.includes("sms")) return { icon: Mail, color: "text-violet-500 bg-violet-50" };
              if (t.includes("fail") || t.includes("error") || t.includes("blocked")) return { icon: ShieldAlert, color: "text-red-500 bg-red-50" };
              return { icon: Activity, color: "text-slate-500 bg-slate-50" };
            };

            return (
              <>
                <DialogHeader className="pb-3">
                  <DialogTitle className="text-base font-semibold">Call Events</DialogTitle>
                </DialogHeader>

                {/* Call summary bar */}
                <div className="rounded-lg border bg-muted/30 px-4 py-3 mb-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`flex h-9 w-9 items-center justify-center rounded-full ${config.color}`}>
                        <EIcon className="h-4 w-4" />
                      </div>
                      <div>
                        <p className="text-sm font-semibold">{eventsCall.patient_name}</p>
                        <p className="text-xs text-muted-foreground tabular-nums">
                          {eventsCall.phone}
                          {eventsCall.started_at && ` · ${formatDate(eventsCall.started_at)} ${formatTime(eventsCall.started_at)}`}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-[10px] tabular-nums">
                        {systemEntries.length} event{systemEntries.length !== 1 ? "s" : ""}
                      </Badge>
                      <Badge variant={config.variant} className="text-xs">
                        {config.label}
                      </Badge>
                    </div>
                  </div>
                </div>

                {/* Timeline */}
                <div className="flex-1 min-h-0 overflow-y-auto rounded-lg border bg-muted/10">
                  <div className="p-4">
                    {systemEntries.length === 0 ? (
                      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                        <Activity className="h-8 w-8 mb-2 opacity-15" />
                        <p className="text-xs">No events recorded</p>
                      </div>
                    ) : (
                      <div className="relative">
                        {/* Timeline line */}
                        <div className="absolute left-[13px] top-3 bottom-3 w-px bg-border" />

                        <div className="space-y-3">
                          {systemEntries.map((entry, idx) => {
                            const cat = categorize(entry.text);
                            const CatIcon = cat.icon;
                            return (
                              <div key={idx} className="flex items-start gap-3 relative">
                                <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${cat.color} z-10 ring-2 ring-background`}>
                                  <CatIcon className="h-3.5 w-3.5" />
                                </div>
                                <div className="flex-1 min-w-0 pt-0.5">
                                  <p className="text-sm text-foreground/80 leading-snug break-words">{entry.text}</p>
                                  {entry.timestamp && (
                                    <p className="text-[10px] text-muted-foreground tabular-nums mt-0.5">
                                      {formatTime(entry.timestamp)}
                                    </p>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </>
            );
          })()}
        </DialogContent>
      </Dialog>
    </>
  );
}
