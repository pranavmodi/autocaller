"use client";

import { useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  MessageSquare,
  RefreshCw,
  ChevronDown,
  Bot,
  User,
  Phone,
  PhoneForwarded,
  PhoneMissed,
  PhoneOff,
  Loader2,
} from "lucide-react";
import { formatDate, formatTime } from "@/lib/utils";
import type { CallLog } from "@/types";

interface TranscriptBrowserCardProps {
  calls: CallLog[];
  onRefresh: () => void;
  onLoadMore: () => void;
  hasMore: boolean;
}

const outcomeConfig: Record<
  string,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" | "success" | "warning" }
> = {
  transferred: { label: "Transferred", variant: "success" },
  callback_requested: { label: "Callback", variant: "secondary" },
  no_answer: { label: "No Answer", variant: "warning" },
  voicemail: { label: "Voicemail", variant: "warning" },
  wrong_number: { label: "Wrong Number", variant: "destructive" },
  disconnected: { label: "Disconnected", variant: "destructive" },
  completed: { label: "Completed", variant: "default" },
  failed: { label: "Failed", variant: "destructive" },
};

interface DateGroup {
  dateKey: string;
  dateLabel: string;
  calls: CallLog[];
}

export function TranscriptBrowserCard({ calls, onRefresh, onLoadMore, hasMore }: TranscriptBrowserCardProps) {
  const [loadingMore, setLoadingMore] = useState(false);
  const dateGroups = useMemo(() => {
    const filtered = calls.filter((c) => c.outcome !== "in_progress");

    const groups = new Map<string, CallLog[]>();
    for (const call of filtered) {
      const dateKey = call.started_at
        ? new Date(call.started_at).toDateString()
        : "Unknown";
      if (!groups.has(dateKey)) groups.set(dateKey, []);
      groups.get(dateKey)!.push(call);
    }

    const result: DateGroup[] = Array.from(groups.entries()).map(
      ([dateKey, groupCalls]) => ({
        dateKey,
        dateLabel:
          dateKey === "Unknown"
            ? "Unknown Date"
            : formatDate(groupCalls[0].started_at!),
        calls: groupCalls,
      })
    );

    // Sort most recent first
    result.sort((a, b) => {
      if (a.dateKey === "Unknown") return 1;
      if (b.dateKey === "Unknown") return -1;
      return new Date(b.dateKey).getTime() - new Date(a.dateKey).getTime();
    });

    return result;
  }, [calls]);

  // Most recent date expanded by default
  const [expandedDates, setExpandedDates] = useState<Set<string>>(new Set());

  const isExpanded = (dateKey: string, index: number) =>
    index === 0 ? !expandedDates.has(dateKey) : expandedDates.has(dateKey);

  const toggleDate = (dateKey: string, index: number) => {
    setExpandedDates((prev) => {
      const next = new Set(prev);
      if (index === 0) {
        // First group: expanded by default, toggle means collapse
        next.has(dateKey) ? next.delete(dateKey) : next.add(dateKey);
      } else {
        // Other groups: collapsed by default, toggle means expand
        next.has(dateKey) ? next.delete(dateKey) : next.add(dateKey);
      }
      return next;
    });
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-lg">
            <MessageSquare className="h-5 w-5" />
            Transcripts
          </CardTitle>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onRefresh}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="max-h-[600px]">
          <div className="px-6 pb-6 space-y-3">
            {dateGroups.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                <MessageSquare className="h-10 w-10 mb-3 opacity-15" />
                <p className="text-sm font-medium">No transcripts yet</p>
                <p className="text-xs mt-1">Call transcripts will appear here</p>
              </div>
            ) : (
              dateGroups.map((group, groupIndex) => (
                <Collapsible
                  key={group.dateKey}
                  open={isExpanded(group.dateKey, groupIndex)}
                  onOpenChange={() => toggleDate(group.dateKey, groupIndex)}
                >
                  <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-lg px-3 py-2 hover:bg-muted/50 transition-colors text-left">
                    <ChevronDown
                      className={`h-4 w-4 text-muted-foreground shrink-0 transition-transform duration-200 ${
                        isExpanded(group.dateKey, groupIndex) ? "" : "-rotate-90"
                      }`}
                    />
                    <span className="text-sm font-medium">{group.dateLabel}</span>
                    <span className="text-xs text-muted-foreground">
                      ({group.calls.length} call{group.calls.length !== 1 ? "s" : ""})
                    </span>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <div className="space-y-3 pt-2 pl-3">
                      {group.calls.map((call) => {
                        const config = outcomeConfig[call.outcome] || outcomeConfig.completed;

                        return (
                          <div
                            key={call.call_id}
                            className="rounded-lg border bg-muted/20 overflow-hidden"
                          >
                            {/* Call header */}
                            <div className="flex items-center justify-between px-4 py-2.5 bg-muted/40">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium">
                                  {call.patient_name}
                                </span>
                                <span className="text-xs text-muted-foreground tabular-nums">
                                  {call.started_at ? formatTime(call.started_at) : "—"}
                                </span>
                              </div>
                              <Badge variant={config.variant} className="text-[10px] px-1.5 py-0">
                                {config.label}
                              </Badge>
                            </div>

                            {/* Transcript */}
                            <div className="px-4 py-3">
                              {call.transcript.filter((e) => e.speaker !== "system").length === 0 ? (
                                <p className="text-xs text-muted-foreground italic">
                                  No transcript recorded
                                </p>
                              ) : (
                                <div className="space-y-2">
                                  {call.transcript.filter((e) => e.speaker !== "system").map((entry, i) => (
                                    <div
                                      key={i}
                                      className={`flex gap-2 ${
                                        entry.speaker === "ai"
                                          ? "justify-start"
                                          : "justify-end"
                                      }`}
                                    >
                                      {entry.speaker === "ai" && (
                                        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                                          <Bot className="h-3 w-3" />
                                        </div>
                                      )}
                                      <div
                                        className={`rounded-lg px-3 py-1.5 text-sm max-w-[80%] ${
                                          entry.speaker === "ai"
                                            ? "bg-muted"
                                            : "bg-primary text-primary-foreground"
                                        }`}
                                      >
                                        {entry.text}
                                      </div>
                                      {entry.speaker === "patient" && (
                                        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-secondary">
                                          <User className="h-3 w-3" />
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              ))
            )}
            {hasMore && dateGroups.length > 0 && (
              <div className="flex justify-center pt-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-xs text-muted-foreground"
                  disabled={loadingMore}
                  onClick={async () => {
                    setLoadingMore(true);
                    try { await onLoadMore(); } finally { setLoadingMore(false); }
                  }}
                >
                  {loadingMore ? (
                    <Loader2 className="h-3 w-3 mr-1.5 animate-spin" />
                  ) : null}
                  Load older transcripts
                </Button>
              </div>
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
