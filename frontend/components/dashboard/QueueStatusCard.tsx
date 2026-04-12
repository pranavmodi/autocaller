"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Users,
  Phone,
  Clock,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Wifi,
  WifiOff,
  Activity,
} from "lucide-react";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import type { QueueState } from "@/types";

interface QueueStatusCardProps {
  queueState: QueueState | null;
  source?: "simulation" | "live";
}

export function QueueStatusCard({ queueState, source = "simulation" }: QueueStatusCardProps) {
  if (!queueState) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Activity className="h-5 w-5" />
            Queue Status
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-8">
            <p className="text-sm text-muted-foreground">Loading queue data...</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-lg">
            <Activity className="h-5 w-5" />
            Queue Status
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge
              variant={source === "live" ? "default" : "secondary"}
              className="text-xs"
            >
              {source === "live" ? "Live FreePBX" : "Simulation"}
            </Badge>
            {queueState.ami_connected ? (
              <Badge variant="success" className="flex items-center gap-1 text-xs">
                <Wifi className="h-3 w-3" />
                AMI
              </Badge>
            ) : (
              <Badge variant="destructive" className="flex items-center gap-1 text-xs">
                <WifiOff className="h-3 w-3" />
                AMI
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Metrics Grid */}
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-lg bg-muted/50 p-3 space-y-1">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Users className="h-3.5 w-3.5" />
              Agents Available
              <InfoTooltip content="Total agents logged in and ready to take calls across all queues. At least 1 is needed for outbound." />
            </div>
            <p className="text-2xl font-semibold tabular-nums">{queueState.global_agents_available}</p>
            <p className="text-xs text-muted-foreground">
              across all queues
            </p>
          </div>
          <div className="rounded-lg bg-muted/50 p-3 space-y-1">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Phone className="h-3.5 w-3.5" />
              Calls Waiting
              <InfoTooltip content="Total inbound calls in queue waiting for an agent. Must be below threshold for outbound to be allowed." />
            </div>
            <p className="text-2xl font-semibold tabular-nums">{queueState.global_calls_waiting}</p>
          </div>
          <div className="rounded-lg bg-muted/50 p-3 space-y-1">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              Max Holdtime
              <InfoTooltip content="Longest any caller has been waiting in seconds. Must be below threshold for outbound." />
            </div>
            <p className="text-2xl font-semibold tabular-nums">{queueState.global_max_holdtime}s</p>
          </div>
          <div className="rounded-lg bg-muted/50 p-3 space-y-1">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              Stable Polls
              <InfoTooltip content="Consecutive queue polls where conditions were met. Once threshold reached, outbound calls can begin." />
            </div>
            <p className="text-2xl font-semibold tabular-nums">{queueState.stable_polls_count}/3</p>
          </div>
        </div>

        <Separator />

        {/* Outbound Status */}
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium flex items-center gap-1.5">
            Outbound Allowed
            <InfoTooltip content="Final gate for outbound calls. All conditions must be met: AMI connected, agents available, calls waiting and holdtime below thresholds, stable polls reached." />
          </span>
          {queueState.outbound_allowed ? (
            <Badge variant="success" className="flex items-center gap-1">
              <CheckCircle className="h-3 w-3" />
              Yes
            </Badge>
          ) : (
            <Badge variant="destructive" className="flex items-center gap-1">
              <XCircle className="h-3 w-3" />
              No
            </Badge>
          )}
        </div>

        {!queueState.outbound_allowed && (
          <div className="flex items-start gap-2.5 rounded-lg border border-orange-200 bg-orange-50 p-3 text-sm text-orange-800 dark:border-orange-900/50 dark:bg-orange-950/30 dark:text-orange-200">
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
            <p className="text-xs leading-relaxed">
              {!queueState.ami_connected
                ? "AMI connection lost. Outbound disabled for safety."
                : queueState.global_agents_available === 0
                ? "No agents available to handle transfers."
                : queueState.global_calls_waiting > 1
                ? "Queue has calls waiting. Outbound paused."
                : queueState.stable_polls_count < 3
                ? `Waiting for stable conditions (${queueState.stable_polls_count}/3 polls).`
                : "Conditions not met for outbound calls."}
            </p>
          </div>
        )}

        <Separator />

        {/* Individual Queues */}
        <div className="space-y-2">
          <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Queues</h4>
          <div className="space-y-1.5">
            {queueState.queues.map((queue) => (
              <div
                key={queue.Queue}
                className="flex items-center justify-between rounded-md bg-muted/40 px-3 py-2 text-sm"
              >
                <span className="font-medium text-sm">{queue.Queue}</span>
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <span>{queue.AvailableAgents} avail</span>
                  <span>{queue.Calls} waiting</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
