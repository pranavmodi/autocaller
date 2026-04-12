"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Activity,
  Ban,
  Phone,
  PhoneOff,
  UserX,
  MonitorOff,
  Clock,
  Zap,
  CheckCircle,
  XCircle,
  Pause,
  Wifi,
  WifiOff,
  MessageSquare,
  AlertTriangle,
  Radio,
} from "lucide-react";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { formatTime } from "@/lib/utils";
import type { DispatcherDecision } from "@/hooks/useWebSocket";

interface DispatcherEventsCardProps {
  events: DispatcherDecision[];
}

const decisionConfig: Record<
  string,
  { label: string; icon: typeof Activity; variant: "default" | "secondary" | "destructive" | "outline" | "success" | "warning" }
> = {
  // Dispatcher decisions
  blocked: { label: "BLOCKED", icon: Ban, variant: "warning" },
  dispatched: { label: "DISPATCH", icon: Phone, variant: "success" },
  starting_call: { label: "STARTING", icon: Phone, variant: "default" },
  call_started: { label: "CALL START", icon: Zap, variant: "success" },
  call_ended: { label: "CALL END", icon: PhoneOff, variant: "secondary" },
  call_active: { label: "IN CALL", icon: Phone, variant: "default" },
  start_failed: { label: "START FAILED", icon: AlertTriangle, variant: "destructive" },
  no_candidate: { label: "NO PATIENTS", icon: UserX, variant: "secondary" },
  no_frontend_connected: { label: "NO FRONTEND", icon: MonitorOff, variant: "destructive" },
  dispatch_timeout: { label: "TIMEOUT", icon: Clock, variant: "destructive" },
  waiting: { label: "WAITING", icon: Pause, variant: "outline" },
  waiting_for_voice_client: { label: "WAITING", icon: Pause, variant: "outline" },
  self_healed: { label: "SELF HEALED", icon: CheckCircle, variant: "secondary" },
  started: { label: "STARTED", icon: CheckCircle, variant: "success" },
  stopped: { label: "STOPPED", icon: XCircle, variant: "destructive" },
  system_enabled: { label: "ENABLED", icon: CheckCircle, variant: "success" },
  system_disabled: { label: "DISABLED", icon: XCircle, variant: "destructive" },
  config_updated: { label: "CONFIG", icon: Activity, variant: "secondary" },
  // Voice/Realtime events
  voice_connecting: { label: "CONNECTING", icon: Wifi, variant: "secondary" },
  voice_connected: { label: "CONNECTED", icon: Wifi, variant: "success" },
  voice_disconnected: { label: "DISCONNECTED", icon: WifiOff, variant: "destructive" },
  voice_error: { label: "VOICE ERROR", icon: AlertTriangle, variant: "destructive" },
  voice_message: { label: "VOICE", icon: MessageSquare, variant: "outline" },
  twilio_blocked: { label: "TWILIO BLOCKED", icon: Ban, variant: "warning" },
  twilio_calling: { label: "TWILIO", icon: Radio, variant: "default" },
  openai_session: { label: "OPENAI", icon: Zap, variant: "success" },
  sms_sent: { label: "SMS SENT", icon: MessageSquare, variant: "success" },
  sms_failed: { label: "SMS FAILED", icon: AlertTriangle, variant: "destructive" },
};

export function DispatcherEventsCard({ events }: DispatcherEventsCardProps) {
  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-lg">
            <Activity className="h-5 w-5" />
            Dispatcher Events
            <InfoTooltip content="Real-time log of dispatcher decisions. Shows when calls are dispatched, blocked (and why), or when the system state changes." />
          </CardTitle>
          {events.length > 0 && (
            <span className="text-xs text-muted-foreground tabular-nums">
              {events.length} event{events.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex-1 p-0">
        <ScrollArea className="h-[350px]">
          <div className="space-y-1 px-6 pb-6">
            {events.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                <Activity className="h-10 w-10 mb-3 opacity-15" />
                <p className="text-sm font-medium">No events yet</p>
                <p className="text-xs mt-1">Dispatcher decisions will stream here</p>
              </div>
            ) : (
              events.map((event, index) => {
                const config = decisionConfig[event.decision] || {
                  label: event.decision.toUpperCase(),
                  icon: Activity,
                  variant: "outline" as const,
                };
                const Icon = config.icon;

                return (
                  <div
                    key={`${event.timestamp}-${index}`}
                    className="flex items-start gap-3 rounded-lg bg-muted/40 px-3 py-2"
                  >
                    <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-background mt-0.5">
                      <Icon className="h-3 w-3 text-muted-foreground" />
                    </div>
                    <div className="flex-1 min-w-0 space-y-0.5">
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant={config.variant} className="text-[10px] px-1.5 py-0 font-mono">
                          {config.label}
                        </Badge>
                        <span className="text-[10px] text-muted-foreground tabular-nums">
                          {formatTime(event.timestamp)}
                        </span>
                        {(event.repeatCount ?? 0) > 1 && (
                          <span className="text-[10px] text-muted-foreground tabular-nums">
                            ×{event.repeatCount}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-foreground/80 leading-relaxed">
                        {event.detail}
                      </p>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
