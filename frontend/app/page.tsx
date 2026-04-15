"use client";

import Link from "next/link";
import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getDispatcherStatus,
  toggleDispatcher,
  startDispatcherBatch,
  listCalls,
  listLeads,
  getSettings,
  setSystemEnabled,
  setMockMode,
  setVoiceProvider,
  setDispatcherCooldown,
  setIVRNavigate,
} from "@/lib/api";
import { useDashboardEvents } from "@/hooks/useDashboardEvents";
import { OutcomePill } from "@/components/OutcomePill";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function NowPage() {
  const qc = useQueryClient();
  const { lastDecision } = useDashboardEvents();

  const dispatcher = useQuery({
    queryKey: ["dispatcher-status"],
    queryFn: getDispatcherStatus,
    refetchInterval: 5_000,
  });
  const running = dispatcher.data?.running ?? false;

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => toggleDispatcher(enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dispatcher-status"] }),
  });

  const startBatch = useMutation({
    mutationFn: (count: number) => startDispatcherBatch(count),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dispatcher-status"] }),
  });

  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
    refetchInterval: 15_000,
  });
  const systemEnabled = Boolean(settings.data?.system_enabled);
  const mockOn = Boolean(settings.data?.mock_mode);
  const mockPhone = String(settings.data?.mock_phone ?? "");
  const ivrNavigateOn = Boolean(settings.data?.ivr_navigate_enabled);
  const voiceProvider =
    (settings.data?.voice_provider as "openai" | "gemini" | undefined) ?? "openai";
  const voiceModel = String(settings.data?.voice_model ?? "");

  const toggleSystem = useMutation({
    mutationFn: (enabled: boolean) => setSystemEnabled(enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
  const toggleMock = useMutation({
    mutationFn: (enabled: boolean) => setMockMode(enabled, mockPhone),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
  const toggleIVR = useMutation({
    mutationFn: (enabled: boolean) => setIVRNavigate(enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
  const switchVoice = useMutation({
    mutationFn: (next: "openai" | "gemini") => setVoiceProvider(next),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
  const cooldownServer =
    Number(
      (settings.data?.dispatcher_settings as Record<string, unknown> | undefined)
        ?.cooldown_seconds ?? 0,
    ) || 0;
  const [cooldownDraft, setCooldownDraft] = useState<number | null>(null);
  const effectiveCooldown = cooldownDraft ?? cooldownServer;
  const saveCooldown = useMutation({
    mutationFn: (secs: number) => setDispatcherCooldown(secs),
    onSuccess: () => {
      setCooldownDraft(null);
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  const recentCalls = useQuery({
    queryKey: ["recent-calls", 3],
    queryFn: () => listCalls(3, 0),
    refetchInterval: 10_000,
  });

  const nextUp = useQuery({
    queryKey: ["leads-next"],
    queryFn: listLeads,
    refetchInterval: 10_000,
  });

  const [batchCount, setBatchCount] = useState<number>(5);

  const latestReason = lastDecision?.detail ?? dispatcher.data?.recent_decisions?.[0]?.detail ?? "—";

  return (
    <div className="space-y-6">
      {/* Note: active-call UI + auto-listen pill live in the global
          ActiveCallOverlay (root layout), so they appear on every page
          — not just here. */}

      {/* Global controls */}
      <section className="rounded-lg border border-neutral-200 bg-white p-5">
        <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
          Controls
        </h2>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <ControlRow
            label="System enabled"
            description="Master switch. When off, the dispatcher won't place any calls even if it's 'running'."
            checked={systemEnabled}
            disabled={toggleSystem.isPending || settings.isLoading}
            onToggle={(v) => toggleSystem.mutate(v)}
            accent={systemEnabled ? "green" : "red"}
          />
          <ControlRow
            label={`Mock mode${mockOn && mockPhone ? ` → ${mockPhone}` : ""}`}
            description="Redirect every call to your mock phone instead of the lead's real number. Turn OFF for real outbound."
            checked={mockOn}
            disabled={toggleMock.isPending || settings.isLoading}
            onToggle={(v) => toggleMock.mutate(v)}
            accent={mockOn ? "amber" : "neutral"}
          />
          <ControlRow
            label="IVR navigation"
            description="When a phone tree is detected, press digits with an LLM to reach a human instead of hanging up. Respects identity-claim rules; caps at 3 menu hops / 60 s."
            checked={ivrNavigateOn}
            disabled={toggleIVR.isPending || settings.isLoading}
            onToggle={(v) => toggleIVR.mutate(v)}
            accent={ivrNavigateOn ? "green" : "neutral"}
          />
        </div>
        <div className="mt-3 flex items-center justify-between gap-3 rounded-md border border-neutral-100 p-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-neutral-900">Voice backend</span>
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-[10px] font-semibold",
                  voiceProvider === "gemini"
                    ? "bg-violet-50 text-violet-700"
                    : "bg-sky-50 text-sky-700",
                )}
              >
                {voiceProvider}
              </span>
              {voiceModel && (
                <span className="truncate text-[10px] text-neutral-500">
                  {voiceModel}
                </span>
              )}
            </div>
            <p className="mt-0.5 text-xs text-neutral-500">
              Realtime voice provider for the next call. OpenAI Realtime vs Gemini Live.
              Overridden per-call by the dispatcher or CLI --voice flag.
            </p>
          </div>
          <div className="flex overflow-hidden rounded-md border border-neutral-200 text-xs">
            <button
              type="button"
              disabled={switchVoice.isPending || settings.isLoading}
              onClick={() => switchVoice.mutate("openai")}
              className={cn(
                "px-3 py-1.5 font-medium transition",
                voiceProvider === "openai"
                  ? "bg-sky-600 text-white"
                  : "bg-white text-neutral-700 hover:bg-neutral-50",
              )}
            >
              OpenAI
            </button>
            <button
              type="button"
              disabled={switchVoice.isPending || settings.isLoading}
              onClick={() => switchVoice.mutate("gemini")}
              className={cn(
                "border-l border-neutral-200 px-3 py-1.5 font-medium transition",
                voiceProvider === "gemini"
                  ? "bg-violet-600 text-white"
                  : "bg-white text-neutral-700 hover:bg-neutral-50",
              )}
            >
              Gemini
            </button>
          </div>
        </div>
      </section>

      {/* Dispatcher + batch */}
      <section className="rounded-lg border border-neutral-200 bg-white p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
              Dispatcher
            </h2>
            <div className="mt-1 flex items-center gap-3">
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold",
                  running
                    ? "bg-emerald-50 text-emerald-700"
                    : "bg-neutral-100 text-neutral-600",
                )}
              >
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    running ? "animate-pulse bg-emerald-500" : "bg-neutral-400",
                  )}
                />
                {running ? "running" : "stopped"}
              </span>
              <span className="text-sm text-neutral-700">
                {dispatcher.data?.state ?? "—"}
              </span>
              {dispatcher.data?.batch?.target && (
                <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-700">
                  batch {dispatcher.data.batch.placed}/{dispatcher.data.batch.target}
                </span>
              )}
            </div>
            <p className="mt-2 text-xs text-neutral-500 line-clamp-2">
              latest: <span className="text-neutral-700">{latestReason}</span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-neutral-500">auto-dial</span>
            <Switch
              checked={running}
              disabled={toggle.isPending}
              onCheckedChange={(v) => toggle.mutate(v)}
            />
          </div>
        </div>

        {/* Batch launcher */}
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-neutral-100 pt-3">
          <label className="text-xs text-neutral-600">
            Batch size:{" "}
            <input
              type="number"
              min={1}
              max={200}
              value={batchCount}
              onChange={(e) => setBatchCount(Math.max(1, parseInt(e.target.value || "1", 10)))}
              className="w-16 rounded border border-neutral-300 px-1.5 py-0.5 text-sm"
              disabled={running}
            />
          </label>
          <label
            className="text-xs text-neutral-600"
            title="Seconds to wait after a call ends before the next one is placed"
          >
            Cooldown (s):{" "}
            <input
              type="number"
              min={0}
              max={3600}
              value={effectiveCooldown}
              onChange={(e) =>
                setCooldownDraft(Math.max(0, parseInt(e.target.value || "0", 10)))
              }
              className="w-16 rounded border border-neutral-300 px-1.5 py-0.5 text-sm"
              disabled={saveCooldown.isPending}
            />
          </label>
          {cooldownDraft !== null && cooldownDraft !== cooldownServer && (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => saveCooldown.mutate(cooldownDraft)}
                disabled={saveCooldown.isPending}
                className="gap-1.5"
              >
                Save cooldown
              </Button>
              <button
                type="button"
                onClick={() => setCooldownDraft(null)}
                className="text-[11px] text-neutral-500 underline-offset-2 hover:underline"
              >
                cancel
              </button>
            </>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={() => startBatch.mutate(batchCount)}
            disabled={running || startBatch.isPending}
            className="gap-1.5"
          >
            Start batch of {batchCount}
          </Button>
          {dispatcher.data?.batch?.target && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => toggle.mutate(false)}
              disabled={!running}
              className="gap-1.5 text-rose-700"
            >
              Stop batch
            </Button>
          )}
          <span className="ml-auto text-[11px] text-neutral-400">
            auto-stops after N calls placed · cooldown applies between each call
          </span>
        </div>
      </section>

      {/* Active call UI lives in the global ActiveCallOverlay — floats
          on every page with minimize/expand. */}

      {/* Next up + Recent calls, two-column on desktop */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Next up */}
        <section className="rounded-lg border border-neutral-200 bg-white p-5">
          <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
            Next up
          </h2>
          <div className="mt-3 space-y-2">
            {nextUp.isLoading && (
              <p className="text-xs text-neutral-400">loading…</p>
            )}
            {nextUp.data?.patients?.slice(0, 3).map((l) => (
              <div
                key={l.patient_id}
                className="flex items-center justify-between rounded-md border border-neutral-100 p-3"
              >
                <div>
                  <div className="text-sm font-medium">{l.name}</div>
                  <div className="text-xs text-neutral-500">
                    {l.firm_name ?? "—"}
                    {l.state ? ` · ${l.state}` : ""}
                    {l.title ? ` · ${l.title}` : ""}
                  </div>
                </div>
                <span className="rounded bg-neutral-100 px-2 py-0.5 text-[10px] font-medium text-neutral-600">
                  P{l.priority_bucket}
                </span>
              </div>
            ))}
            {nextUp.data && (nextUp.data.patients?.length ?? 0) === 0 && (
              <p className="text-xs text-neutral-400">No eligible leads.</p>
            )}
          </div>
        </section>

        {/* Recent calls */}
        <section className="rounded-lg border border-neutral-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
              Recent calls
            </h2>
            <Link href="/calls" className="text-xs text-neutral-500 hover:underline">
              view all →
            </Link>
          </div>
          <div className="mt-3 space-y-2">
            {recentCalls.isLoading && (
              <p className="text-xs text-neutral-400">loading…</p>
            )}
            {recentCalls.data?.calls?.map((c) => (
              <Link
                key={c.call_id}
                href={`/calls/${c.call_id}`}
                className="flex items-center justify-between rounded-md border border-neutral-100 p-3 hover:bg-neutral-50"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">
                    {c.patient_name}
                    {c.firm_name && (
                      <span className="ml-2 text-xs font-normal text-neutral-500">
                        · {c.firm_name}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-neutral-500">
                    {c.started_at
                      ? formatDistanceToNow(new Date(c.started_at), { addSuffix: true })
                      : ""}
                    {" · "}
                    {c.duration_seconds}s
                  </div>
                </div>
                <OutcomePill outcome={c.outcome} />
              </Link>
            ))}
            {recentCalls.data && (recentCalls.data.calls?.length ?? 0) === 0 && (
              <p className="text-xs text-neutral-400">No calls yet.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function ControlRow({
  label,
  description,
  checked,
  disabled,
  onToggle,
  accent,
}: {
  label: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  onToggle: (v: boolean) => void;
  accent: "green" | "red" | "amber" | "neutral";
}) {
  const pill = {
    green: "bg-emerald-50 text-emerald-700",
    red: "bg-rose-50 text-rose-700",
    amber: "bg-amber-50 text-amber-700",
    neutral: "bg-neutral-100 text-neutral-600",
  }[accent];
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border border-neutral-100 p-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-neutral-900">{label}</span>
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-semibold",
              pill,
            )}
          >
            {checked ? "ON" : "OFF"}
          </span>
        </div>
        <p className="mt-0.5 text-xs text-neutral-500">{description}</p>
      </div>
      <Switch
        checked={checked}
        disabled={disabled}
        onCheckedChange={onToggle}
      />
    </div>
  );
}
