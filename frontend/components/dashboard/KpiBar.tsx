"use client";

import { Card, CardContent } from "@/components/ui/card";
import { PhoneCall, PhoneForwarded, MessageSquare } from "lucide-react";
import type { TodayKpis } from "@/types";

interface KpiBarProps {
  kpis: TodayKpis | null;
}

export function KpiBar({ kpis }: KpiBarProps) {
  const calls = kpis?.total_calls ?? 0;
  const transferred = kpis?.transferred ?? 0;
  const voicemails = kpis?.voicemails ?? 0;
  const sms = kpis?.sms ?? 0;

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Card className="flex items-center">
        <CardContent className="flex items-center gap-4 p-4 w-full">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-blue-50 dark:bg-blue-950/40">
            <PhoneCall className="h-5 w-5 text-blue-600 dark:text-blue-400" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground uppercase tracking-wide font-medium">
              Calls Today
            </p>
            <p className="text-2xl font-semibold tabular-nums leading-tight">{calls}</p>
          </div>
        </CardContent>
      </Card>

      <Card className="flex items-center">
        <CardContent className="flex items-center gap-4 p-4 w-full">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-emerald-50 dark:bg-emerald-950/40">
            <PhoneForwarded className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground uppercase tracking-wide font-medium">
              Transferred
            </p>
            <p className="text-2xl font-semibold tabular-nums leading-tight">{transferred}</p>
          </div>
        </CardContent>
      </Card>

      <Card className="flex items-center">
        <CardContent className="flex items-center gap-4 p-4 w-full">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-amber-50 dark:bg-amber-950/40">
            <MessageSquare className="h-5 w-5 text-amber-600 dark:text-amber-400" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground uppercase tracking-wide font-medium">
              VM / SMS Sent
            </p>
            <p className="text-2xl font-semibold tabular-nums leading-tight">
              {voicemails} <span className="text-muted-foreground/60 text-lg">/</span> {sms}
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
