"use client";

import { useEffect, useState, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Phone,
  PhoneOff,
  Mic,
  MicOff,
  User,
  Bot,
  Clock,
} from "lucide-react";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { formatDuration } from "@/lib/utils";
import type { CallLog } from "@/types";

interface ActiveCallCardProps {
  call: CallLog | null;
  status: string | null;
  transcript: Array<{ speaker: string; text: string }>;
  isRecording: boolean;
  audioLevel: number;
  onEndCall: () => void;
  onToggleMic: () => void;
  lastCallInfo?: { patientName: string; duration: number } | null;
  isTwilioMode?: boolean;
}

export function ActiveCallCard({
  call,
  status,
  transcript,
  isRecording,
  audioLevel,
  onEndCall,
  onToggleMic,
  lastCallInfo,
  isTwilioMode,
}: ActiveCallCardProps) {
  const [duration, setDuration] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Update duration every second
  useEffect(() => {
    if (!call) {
      setDuration(0);
      return;
    }

    const startTime = call.started_at ? new Date(call.started_at).getTime() : Date.now();
    const interval = setInterval(() => {
      setDuration(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);

    return () => clearInterval(interval);
  }, [call]);

  // Auto-scroll transcript
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [transcript]);

  // Show last call transcript if no active call but transcript exists
  if (!call && transcript.length > 0) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-lg">
              <PhoneOff className="h-5 w-5 text-muted-foreground" />
              Call Ended
            </CardTitle>
            {lastCallInfo && (
              <Badge variant="outline" className="flex items-center gap-1 tabular-nums text-xs">
                <Clock className="h-3 w-3" />
                {formatDuration(lastCallInfo.duration)}
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {lastCallInfo && (
            <div className="rounded-lg bg-muted/50 p-3">
              <p className="text-sm font-medium">{lastCallInfo.patientName}</p>
              <p className="text-xs text-muted-foreground mt-0.5">Call completed</p>
            </div>
          )}

          {/* Transcript from ended call */}
          <div className="space-y-2">
            <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Transcript</h4>
            <ScrollArea className="h-[250px] rounded-lg border bg-muted/20 p-3">
              <div ref={scrollRef} className="space-y-2.5">
                {transcript.map((entry, index) => (
                  <div
                    key={index}
                    className={`flex gap-2 ${
                      entry.speaker === "ai" ? "justify-start" : "justify-end"
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
            </ScrollArea>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!call) {
    return (
      <Card className="border-dashed">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-lg">
            <Phone className="h-5 w-5" />
            Active Call
            <InfoTooltip content="Shows the current call in progress with live transcript. In web mode, use your microphone to speak as the patient." />
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <Phone className="h-10 w-10 mb-3 opacity-15" />
            <p className="text-sm font-medium">No active call</p>
            <p className="text-xs mt-1">Select a patient from the queue to start</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-emerald-500/40 shadow-sm shadow-emerald-500/5">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-lg">
            <div className="relative">
              <Phone className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
              <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            </div>
            Active Call
          </CardTitle>
          <Badge variant="success" className="flex items-center gap-1 tabular-nums text-xs">
            <Clock className="h-3 w-3" />
            {formatDuration(duration)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Patient Info */}
        <div className="rounded-lg bg-muted/50 p-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">{call.patient_name}</p>
              <p className="text-xs text-muted-foreground tabular-nums mt-0.5">{call.phone}</p>
            </div>
            <Badge variant="outline" className="text-xs flex items-center gap-1">
              P{call.priority_bucket}
              <InfoTooltip content="Priority bucket: P1=Abandoned/No AI, P2=Abandoned/AI called, P3=Called in/No AI, P4=Never contacted. Lower = higher priority." />
            </Badge>
          </div>
        </div>

        {/* Status */}
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">Status</span>
          <div className="flex items-center gap-2">
            {isTwilioMode && <Badge variant="outline" className="text-[10px] px-1.5 py-0">Twilio</Badge>}
            <span className="font-medium">{status || "Connected"}</span>
          </div>
        </div>

        <Separator />

        {/* Audio Controls — hidden in Twilio mode (audio handled by Twilio) */}
        {!isTwilioMode && (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <Button
                variant={isRecording ? "default" : "outline"}
                size="sm"
                className="h-8 text-xs"
                onClick={onToggleMic}
              >
                {isRecording ? (
                  <>
                    <Mic className="h-3.5 w-3.5 mr-1.5" />
                    Mic On
                  </>
                ) : (
                  <>
                    <MicOff className="h-3.5 w-3.5 mr-1.5" />
                    Muted
                  </>
                )}
              </Button>
              {isRecording && (
                <div className="flex items-center gap-0.5 h-5">
                  {[...Array(5)].map((_, i) => (
                    <div
                      key={i}
                      className="audio-bar w-0.5 bg-emerald-500 rounded-full"
                      style={{
                        height: `${Math.max(3, audioLevel * 20 * (0.5 + Math.random() * 0.5))}px`,
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
            <Button variant="destructive" size="sm" className="h-8 text-xs" onClick={onEndCall}>
              <PhoneOff className="h-3.5 w-3.5 mr-1.5" />
              End Call
            </Button>
          </div>
        )}

        <Separator />

        {/* Live Transcript */}
        <div className="space-y-2">
          <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Live Transcript</h4>
          <ScrollArea className="h-[200px] rounded-lg border bg-muted/20 p-3">
            <div ref={scrollRef} className="space-y-2.5">
              {transcript.length === 0 ? (
                <p className="text-xs text-muted-foreground text-center py-6">
                  Waiting for conversation...
                </p>
              ) : (
                transcript.map((entry, index) => (
                  <div
                    key={index}
                    className={`flex gap-2 ${
                      entry.speaker === "ai" ? "justify-start" : "justify-end"
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
                ))
              )}
            </div>
          </ScrollArea>
        </div>
      </CardContent>
    </Card>
  );
}
